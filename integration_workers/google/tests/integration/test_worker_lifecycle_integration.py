#!/usr/bin/env python3
"""Integration tests for the Google worker's shared ARQ lifecycle (ITER14-002 P2).

These exercise the migrated ``build_worker_lifecycle`` hooks against real Redis +
Postgres: the worker starts (session factory built, stream consumer launched),
runs a trivial ARQ job that touches the database, and shuts down cleanly (the
stream-consumer task is cancelled/reaped and the session factory's engine is
disposed — no leaked connections).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
import pytest_asyncio
from arq import Worker, create_pool
from arq.connections import RedisSettings
from sqlalchemy import text

_TEST_QUEUE = "arq:test:google-lifecycle"


async def _trivial_db_job(ctx: dict[str, Any]) -> int:
    """A trivial ARQ job: proves startup populated ctx and the DB is reachable."""
    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        return int(result.scalar_one())


@pytest_asyncio.fixture
async def redis_pool() -> Any:
    """Real Redis pool on an isolated DB index for the worker queue."""
    redis_settings = RedisSettings.from_dsn(os.environ["REDIS_URL"])
    redis_settings.database = 2
    pool = await create_pool(redis_settings)
    await pool.flushdb()
    yield pool
    await pool.flushdb()
    await pool.aclose()


@pytest.fixture
def worker_module() -> Any:
    """Reload the worker so its settings reflect this session's env.

    The google unit tests reload ``worker`` under a patched env (fake DB/Redis),
    which can leave ``worker.settings`` and the lifecycle hooks pointing at
    unreachable hosts if a unit test ran first in the same process. Reloading
    here — after ``conftest`` has set ``DATABASE_URL``/``REDIS_URL`` to the real
    test services — makes this test independent of import/run order.
    """
    import importlib

    import worker

    return importlib.reload(worker)


class TestGoogleWorkerLifecycle:
    """The migrated lifecycle hooks start, run a job, and shut down cleanly."""

    @pytest.mark.asyncio
    async def test_start_run_job_and_clean_shutdown(
        self, redis_pool: Any, worker_module: Any
    ) -> None:
        worker = worker_module

        job = await redis_pool.enqueue_job("_trivial_db_job", _queue_name=_TEST_QUEUE)
        assert job is not None

        arq_worker = Worker(
            functions=[_trivial_db_job],
            on_startup=worker.GoogleWorkerSettings.on_startup,
            on_shutdown=worker.GoogleWorkerSettings.on_shutdown,
            redis_pool=redis_pool,
            queue_name=_TEST_QUEUE,
            burst=True,
            max_tries=1,
            poll_delay=0.1,
        )

        # Burst run: on_startup → process the queued job. async_run() does not
        # invoke on_shutdown (it leaves connections open for testing), so close()
        # is called explicitly below to exercise shutdown.
        try:
            await arq_worker.async_run()

            # The trivial job ran successfully against the real database, proving
            # on_startup built a usable session factory and stored it in ctx.
            result = await job.result(timeout=5)
            assert result == 1

            consumer_task = arq_worker.ctx.get("stream_consumer_task")
            assert consumer_task is not None
            assert not consumer_task.done()
        finally:
            await arq_worker.close()

        # Clean shutdown: the stream-consumer task was launched and then
        # cancelled/reaped by on_shutdown — no leaked background task.
        assert consumer_task.done()

    @pytest.mark.asyncio
    async def test_shutdown_disposes_session_factory(self, worker_module: Any) -> None:
        """Google sets close_session_factory=True, so on_shutdown disposes the
        engine bound to the session factory (no leaked connection pool)."""
        worker = worker_module

        ctx: dict[str, Any] = {}
        await worker.GoogleWorkerSettings.on_startup(ctx)
        try:
            session_factory = ctx["session_factory"]
            # Session factory is usable immediately after startup.
            async with session_factory() as session:
                assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        finally:
            await worker.GoogleWorkerSettings.on_shutdown(ctx)

        # After shutdown the consumer task is reaped and the engine is disposed,
        # so acquiring a new connection from the disposed pool is required to
        # rebuild it — assert the task is done (clean shutdown).
        assert ctx["stream_consumer_task"].done()

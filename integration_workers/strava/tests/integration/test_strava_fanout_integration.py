"""Integration tests for the non-blocking Strava fan-out (ITER14-003 Phase 4).

These exercise the real data + queue path: ``sync_strava_activities`` owns its
parent ``sync_jobs`` row, persists child rows and dispatches jobs against **real
Redis**, marks the parent ``IN_PROGRESS`` and returns immediately; the batch jobs
update their own child row and increment the parent counters against **real
Postgres**; and the shared reconciler then finalises the parent. Only the
external Strava SaaS (auth resolution + sync service) is stubbed — the database,
repository and Redis queue are real.

Isolation: a ``session_factory`` bound to the rolled-back ``async_connection``
(savepoint mode) backs every worker session, so all commits unwind at teardown.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from arq import create_pool
from arq.connections import RedisSettings
from core_shared.integration_constants import STRAVA_ARQ_QUEUE_NAME
from core_shared.models.sync_job import SyncJobStatus
from core_shared.repositories.sync_job_repository import SyncJobRepository
from core_shared.sync_reconciliation import reconcile_parents

from .conftest import get_workspace_env

os.environ.setdefault(
    "REDIS_URL",
    f"redis://localhost:{get_workspace_env().get('REDIS_TEST_PORT', '6380')}",
)

_BATCH_RESULT = {"synced": 1, "skipped": 0, "failed": 0}


def _async_gen(items: list[Any]) -> Any:
    def _gen(*_a: Any, **_k: Any) -> Any:
        async def _inner() -> Any:
            for item in items:
                yield item

        return _inner()

    return _gen


@pytest_asyncio.fixture
async def redis_pool() -> AsyncIterator[Any]:
    """Real Redis pool on a dedicated DB index for the fan-out queue.

    Mirrors the Immich fan-out suite's isolation: the test Redis is already
    per-workspace via ``REDIS_TEST_PORT``, and this suite uses its own DB index
    (6) so its ``flushdb`` never disturbs other suites. Queue assertions check
    for *our* child job ids as a subset, so they never assume exclusive ownership.
    """
    redis_settings = RedisSettings.from_dsn(os.environ["REDIS_URL"])
    redis_settings.database = 6
    pool = await create_pool(redis_settings)
    await pool.flushdb()
    yield pool
    await pool.flushdb()
    await pool.aclose()


@pytest_asyncio.fixture
async def session_factory(async_connection: Any) -> Any:
    """A worker-style session factory bound to the rolled-back test connection."""
    from sqlalchemy.ext.asyncio import AsyncSession

    @asynccontextmanager
    async def _factory() -> AsyncIterator[Any]:
        async with AsyncSession(
            async_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    return _factory


@pytest_asyncio.fixture
async def repo(async_connection: Any) -> SyncJobRepository:
    return SyncJobRepository(async_connection)


@asynccontextmanager
async def _stubbed_strava(
    *, list_batches: list[Any] | None, sync_side: Any
) -> AsyncIterator[None]:
    """Patch the external Strava collaborators for the duration of the block.

    ``list_batches`` configures the orchestrator listing generator (or ``None``
    for a batch-only run); ``sync_side`` configures ``sync_activity_batch``
    (a return value or an exception ``side_effect``).
    """
    sync_service = MagicMock()
    if list_batches is not None:
        sync_service.list_activity_batches = _async_gen(list_batches)
    sync_service.sync_activity_batch = (
        AsyncMock(side_effect=sync_side)
        if isinstance(sync_side, BaseException)
        else AsyncMock(return_value=sync_side)
    )
    sync_service._api_client = MagicMock()
    sync_service._api_client.close = AsyncMock()

    with (
        patch(
            "worker._resolve_user_by_id",
            AsyncMock(
                return_value={
                    "encrypted_access_token": "a",
                    "encrypted_refresh_token": "r",
                }
            ),
        ),
        patch("worker._create_sync_service", return_value=sync_service),
    ):
        yield


def _ctx(
    session_factory: Any, redis_pool: Any, job_id: str, **extra: Any
) -> dict[str, Any]:
    return {
        "session_factory": session_factory,
        "redis": redis_pool,
        "settings": MagicMock(),
        "job_id": job_id,
        "job_try": 1,
        "max_tries": 5,
        **extra,
    }


def _worker_fn(name: str) -> Any:
    import worker

    return getattr(worker, name)


async def _dispatch(
    *,
    batches: list[Any],
    session_factory: Any,
    redis_pool: Any,
    parent_id: str,
) -> dict[str, Any]:
    """Run the orchestrator under stubbed Strava and return its result dict."""
    async with _stubbed_strava(list_batches=batches, sync_side=_BATCH_RESULT):
        result: dict[str, Any] = await _worker_fn("sync_strava_activities")(
            _ctx(session_factory, redis_pool, parent_id), "user-1", "full"
        )
    return result


async def _run_child(
    child_job_id: str,
    *,
    session_factory: Any,
    redis_pool: Any,
    parent_id: str,
    error: Exception | None = None,
    job_try: int = 1,
) -> None:
    """Run one batch child under stubbed Strava (raises if ``error`` is set)."""
    async with _stubbed_strava(
        list_batches=None, sync_side=error if error else _BATCH_RESULT
    ):
        ctx = _ctx(session_factory, redis_pool, child_job_id, job_try=job_try)
        await _worker_fn("sync_strava_activity_batch")(ctx, "user-1", [1], parent_id)


async def _complete_all_children(
    repo: SyncJobRepository,
    *,
    session_factory: Any,
    redis_pool: Any,
    parent_id: str,
) -> None:
    for child in await repo.list_children(parent_id):
        await _run_child(
            child.job_id,
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )


async def _reconcile(repo: SyncJobRepository) -> dict[str, int]:
    return await reconcile_parents(
        repo, now=datetime.now(UTC), stale_after_seconds=1800.0
    )


@pytest.mark.integration
class TestStravaFanout:
    """Strava activity fan-out dispatch, counters, and reconciliation end-to-end."""

    @pytest.mark.asyncio
    async def test_fanout_dispatches_persists_children_and_reconciles_completed(
        self, repo: SyncJobRepository, session_factory: Any, redis_pool: Any
    ) -> None:
        parent_id = "strava-int-complete"

        result = await _dispatch(
            batches=[[1, 2], [3, 4]],
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )

        # Returned immediately as IN_PROGRESS with the parent owned + children
        # persisted and dispatched.
        assert result["status"] == "in_progress"
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.IN_PROGRESS.value
        assert parent.integration_source == "strava"
        assert parent.expected_children == 2
        children = await repo.list_children(parent_id)
        assert len(children) == 2
        assert all(c.parent_job_id == parent_id for c in children)
        # Subset check: our two children were dispatched on the real queue.
        queued_ids = {
            j.job_id
            for j in await redis_pool.queued_jobs(queue_name=STRAVA_ARQ_QUEUE_NAME)
        }
        assert {c.job_id for c in children} <= queued_ids

        # Children complete → counters increment → reconciler completes the parent.
        await _complete_all_children(
            repo,
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.completed_children == 2

        assert (await _reconcile(repo))["completed"] == 1
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_failed_child_reconciles_parent_to_failed(
        self, repo: SyncJobRepository, session_factory: Any, redis_pool: Any
    ) -> None:
        parent_id = "strava-int-fail"
        await _dispatch(
            batches=[[1], [2]],
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )

        ok, bad = await repo.list_children(parent_id)
        await _run_child(
            ok.job_id,
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )
        # The other child fails on its final attempt.
        with pytest.raises(RuntimeError):
            await _run_child(
                bad.job_id,
                session_factory=session_factory,
                redis_pool=redis_pool,
                parent_id=parent_id,
                error=RuntimeError("boom"),
                job_try=5,
            )

        assert (await _reconcile(repo))["failed"] == 1
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.FAILED.value
        assert parent.error_message

    @pytest.mark.asyncio
    async def test_large_fanout_completes_with_correct_totals(
        self, repo: SyncJobRepository, session_factory: Any, redis_pool: Any
    ) -> None:
        parent_id = "strava-int-large"
        await _dispatch(
            batches=[[i] for i in range(25)],
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )

        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.expected_children == 25

        await _complete_all_children(
            repo,
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.completed_children == 25

        await _reconcile(repo)
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_orchestrator_retry_is_idempotent(
        self, repo: SyncJobRepository, session_factory: Any, redis_pool: Any
    ) -> None:
        """Re-running the orchestrator (ARQ retry) must not duplicate or error.

        The deterministic child ids + plain-INSERT ``create`` would raise a
        duplicate-key error on a naive retry; the orchestrator skips already
        persisted children instead.
        """
        parent_id = "strava-int-retry"
        first = await _dispatch(
            batches=[[1], [2]],
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )
        assert first["status"] == "in_progress"

        # Second run with the same parent + same drained batches (a retry). It
        # must not raise a duplicate-key error and must leave exactly 2 children.
        second = await _dispatch(
            batches=[[1], [2]],
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )
        assert second["status"] == "in_progress"

        children = await repo.list_children(parent_id)
        assert len(children) == 2
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.expected_children == 2
        assert parent.status == SyncJobStatus.IN_PROGRESS.value

    @pytest.mark.asyncio
    async def test_parent_row_persisted_before_drain_rate_limit(
        self, repo: SyncJobRepository, session_factory: Any, redis_pool: Any
    ) -> None:
        """A rate limit during the drain still leaves an in-flight parent row.

        The orchestrator commits the parent ``running`` row before draining, so
        the dashboard shows the sync even while the ARQ retry is deferred.
        """
        from arq import Retry

        from strava_rate_limiter import StravaRateLimitError

        parent_id = "strava-int-predrain"

        def _raising_gen(*_a: Any, **_k: Any) -> Any:
            async def _inner() -> Any:
                raise StravaRateLimitError("rate limited", retry_after=60)
                yield  # pragma: no cover - makes this an async generator

            return _inner()

        sync_service = MagicMock()
        sync_service.list_activity_batches = _raising_gen
        sync_service._api_client = MagicMock()
        sync_service._api_client.close = AsyncMock()

        with (
            patch(
                "worker._resolve_user_by_id",
                AsyncMock(
                    return_value={
                        "encrypted_access_token": "a",
                        "encrypted_refresh_token": "r",
                    }
                ),
            ),
            patch("worker._create_sync_service", return_value=sync_service),
        ):
            with pytest.raises(Retry):
                await _worker_fn("sync_strava_activities")(
                    _ctx(session_factory, redis_pool, parent_id), "user-1", "full"
                )

        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.RUNNING.value
        assert parent.integration_source == "strava"
        # No children persisted yet — the drain never produced any.
        assert await repo.list_children(parent_id) == []

    @pytest.mark.asyncio
    async def test_zero_batches_marks_parent_completed(
        self, repo: SyncJobRepository, session_factory: Any, redis_pool: Any
    ) -> None:
        parent_id = "strava-int-empty"
        result = await _dispatch(
            batches=[],
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )

        assert result["status"] == "completed"
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.COMPLETED.value
        assert parent.expected_children == 0
        assert await repo.list_children(parent_id) == []

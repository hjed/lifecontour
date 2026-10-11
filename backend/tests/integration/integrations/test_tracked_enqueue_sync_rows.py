"""Integration tests: a tracked job's ``sync_jobs`` row exists before it is queued.

A worker can pick a job up the moment it is queued. If its row is not committed
by then, the worker's status updates match nothing and its fan-out children hit
the ``parent_job_id`` foreign key (#1587). The fake ARQ pool here reads the row
at the instant of ``enqueue_job``, through the same real PostgreSQL connection
the service wrote it on.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from arq.connections import RedisSettings
from core_shared.models.sync_job import SyncJob, SyncJobStatus
from core_shared.repositories.sync_job_repository import SyncJobRepository
from core_shared.tracked_enqueue import enqueue_tracked_job
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.integrations.exceptions import JobEnqueueError
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.config import Settings


class _SavepointDatabaseManager:
    """Hands out sessions joined to the test transaction, so commits are savepoints."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        session = AsyncSession(
            bind=self._conn, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()


class _RowCheckingPool:
    """A fake ARQ pool that records the job's row as it stood when queued."""

    def __init__(
        self,
        conn: AsyncConnection,
        *,
        returns_job: bool = True,
        runs_then_raises: bool = False,
    ) -> None:
        self._conn = conn
        self._returns_job = returns_job
        self._runs_then_raises = runs_then_raises
        self.row_at_enqueue: SyncJob | None = None
        self.hset = AsyncMock()
        self.expire = AsyncMock()

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any:
        self.row_at_enqueue = await SyncJobRepository(self._conn).get_by_job_id(
            kwargs["_job_id"]
        )
        if self._runs_then_raises:
            # Redis accepted the job and a worker started it, but the reply was lost.
            await SyncJobRepository(self._conn).update_status(
                job_id=kwargs["_job_id"], status=SyncJobStatus.RUNNING.value
            )
            raise ConnectionError("reply lost")
        return MagicMock(job_id=kwargs["_job_id"]) if self._returns_job else None


def _service(conn: AsyncConnection, pool: _RowCheckingPool) -> TaskQueueService:
    return TaskQueueService(
        redis_settings=RedisSettings(),
        settings=Settings(task_queue_user_job_expiry_hours=24),
        db_manager=_SavepointDatabaseManager(conn),  # type: ignore[arg-type]
        redis_pool=pool,  # type: ignore[arg-type]
        worker_type="strava",
    )


@pytest.mark.integration
class TestTrackedEnqueueSyncRows:
    """Real-database ordering of the row write and the enqueue."""

    @pytest.mark.asyncio
    async def test_row_is_queued_before_the_job_is_enqueued(
        self, clean_database: AsyncConnection
    ) -> None:
        pool = _RowCheckingPool(clean_database)

        job_id = await _service(clean_database, pool).enqueue_strava_sync(
            user_id="user-1"
        )

        assert pool.row_at_enqueue is not None
        assert pool.row_at_enqueue.job_id == job_id
        assert pool.row_at_enqueue.status == SyncJobStatus.QUEUED.value
        assert pool.row_at_enqueue.integration_source == "strava"
        assert pool.row_at_enqueue.user_id == "user-1"
        pool.hset.assert_awaited_once_with("user_jobs:user-1", job_id, "enqueued")

    @pytest.mark.asyncio
    async def test_job_not_enqueued_leaves_a_failed_row(
        self, clean_database: AsyncConnection
    ) -> None:
        pool = _RowCheckingPool(clean_database, returns_job=False)
        service = _service(clean_database, pool)

        with pytest.raises(JobEnqueueError):
            await service.enqueue_strava_sync(user_id="user-1")

        assert pool.row_at_enqueue is not None
        row = await SyncJobRepository(clean_database).get_by_job_id(
            pool.row_at_enqueue.job_id
        )
        assert row is not None
        assert row.status == SyncJobStatus.FAILED.value
        assert row.completed_at is not None
        assert row.error_message == "Job was not enqueued"
        pool.hset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_enqueue_never_overwrites_a_job_a_worker_started(
        self, clean_database: AsyncConnection
    ) -> None:
        """An enqueue error with an unknown outcome leaves a started row alone."""
        pool = _RowCheckingPool(clean_database, runs_then_raises=True)
        service = _service(clean_database, pool)

        with pytest.raises(ConnectionError):
            await service.enqueue_strava_sync(user_id="user-1")

        assert pool.row_at_enqueue is not None
        row = await SyncJobRepository(clean_database).get_by_job_id(
            pool.row_at_enqueue.job_id
        )
        assert row is not None
        assert row.status == SyncJobStatus.RUNNING.value
        assert row.error_message is None

    @pytest.mark.asyncio
    async def test_fail_if_queued_only_fails_a_queued_row(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncJobRepository(clean_database)
        for job_id, status in (("queued-1", "queued"), ("running-1", "running")):
            await repo.create(
                job_id=job_id,
                user_id="user-1",
                integration_source="strava",
                sync_type="full",
                status=status,
            )
        completed_at = datetime.now(UTC)

        failed_queued = await repo.fail_if_queued(
            job_id="queued-1", completed_at=completed_at, error_message="boom"
        )
        failed_running = await repo.fail_if_queued(
            job_id="running-1", completed_at=completed_at, error_message="boom"
        )

        assert (failed_queued, failed_running) == (True, False)
        queued = await repo.get_by_job_id("queued-1")
        running = await repo.get_by_job_id("running-1")
        assert queued is not None
        assert running is not None
        assert (queued.status, queued.error_message) == ("failed", "boom")
        assert queued.completed_at is not None
        assert (running.status, running.error_message) == ("running", None)

    @pytest.mark.asyncio
    async def test_accepts_a_session_that_has_already_queried(
        self, clean_database: AsyncConnection
    ) -> None:
        """Worker periodic syncs reuse one session across accounts after a SELECT."""
        pool = _RowCheckingPool(clean_database)
        session = AsyncSession(
            bind=clean_database, join_transaction_mode="create_savepoint"
        )
        try:
            await session.execute(text("SELECT 1"))
            first = await enqueue_tracked_job(
                session,
                pool,
                "sync_immich_people",
                "user-1",
                "smart",
                queue_name="arq:immich",
                user_id="user-1",
                integration_source="immich",
                sync_type="smart",
            )
            second = await enqueue_tracked_job(
                session,
                pool,
                "sync_immich_people",
                "user-2",
                "smart",
                queue_name="arq:immich",
                user_id="user-2",
                integration_source="immich",
                sync_type="smart",
            )
        finally:
            await session.close()

        repo = SyncJobRepository(clean_database)
        for job_id in (first, second):
            row = await repo.get_by_job_id(job_id)
            assert row is not None
            assert row.status == SyncJobStatus.QUEUED.value

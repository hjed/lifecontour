"""Integration tests for the non-blocking Immich fan-out (ITER14-003 Phase 3).

These exercise the real data + queue path: the orchestrators
(``sync_immich_albums`` / ``sync_immich_people``) persist child ``sync_jobs``
rows and dispatch jobs against **real Redis**, mark the parent ``IN_PROGRESS``
and return immediately; the batch jobs update their own child row and increment
the parent counters against **real Postgres**; and the shared reconciler then
finalises the parent. Only the external Immich SaaS (auth/API/sync service) is
stubbed — the database, repository and Redis queue are real.

Isolation: a ``session_factory`` bound to the rolled-back ``async_connection``
(savepoint mode) backs every worker session, so all commits unwind at teardown.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from arq import create_pool
from arq.connections import RedisSettings
from core_shared.integration_constants import IMMICH_ARQ_QUEUE_NAME
from core_shared.models.sync_job import SyncJobStatus
from core_shared.repositories.sync_job_repository import SyncJobRepository
from core_shared.sync_reconciliation import reconcile_parents

from .conftest import get_workspace_env

os.environ.setdefault(
    "REDIS_URL",
    f"redis://localhost:{get_workspace_env().get('REDIS_TEST_PORT', '6380')}",
)


def _async_gen(items: list[Any]) -> Any:
    async def _gen() -> Any:
        for item in items:
            yield item

    return _gen


@pytest_asyncio.fixture
async def redis_pool() -> AsyncIterator[Any]:
    """Real Redis pool on an isolated DB index for the fan-out queue."""
    redis_settings = RedisSettings.from_dsn(os.environ["REDIS_URL"])
    redis_settings.database = 5
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


def _stub_immich(*, batches: list[Any], kind: str) -> Any:
    """Patch the external Immich collaborators; the listing yields ``batches``."""
    auth = MagicMock()
    auth.get_api_key = AsyncMock(return_value="key")
    auth.get_server_url = AsyncMock(return_value="https://immich.example.com")

    api_client = MagicMock()
    api_client.close = AsyncMock()

    sync_service = MagicMock()
    if kind == "albums":
        sync_service.list_album_id_batches = _async_gen(batches)
    else:
        sync_service.list_people_batches = _async_gen(batches)

    patches = [
        patch("worker.ImmichAuthService", return_value=auth),
        patch("worker.ImmichApiClient"),
        patch("worker.ImmichSyncService", return_value=sync_service),
    ]
    return patches, api_client, sync_service


@asynccontextmanager
async def _apply(patches: list[Any], api_client: Any) -> AsyncIterator[None]:
    started = [p.start() for p in patches]
    # The ImmichApiClient patch is the second entry; wire its create() factory.
    started[1].create.return_value = api_client
    try:
        yield
    finally:
        for p in patches:
            p.stop()


async def _seed_parent(repo: SyncJobRepository, parent_id: str) -> None:
    await repo.create(
        job_id=parent_id,
        user_id="user-1",
        integration_source="immich",
        sync_type="full",
        status=SyncJobStatus.QUEUED.value,
    )


def _batch_ctx(session_factory: Any, redis_pool: Any, job_id: str) -> dict[str, Any]:
    return {
        "session_factory": session_factory,
        "redis": redis_pool,
        "job_id": job_id,
        "job_try": 1,
        "max_tries": 5,
    }


@pytest.mark.integration
class TestImmichAlbumFanout:
    """Album fan-out dispatches, counters update, reconciler finalises."""

    @pytest.mark.asyncio
    async def test_album_fanout_returns_in_progress_and_persists_children(
        self,
        repo: SyncJobRepository,
        session_factory: Any,
        redis_pool: Any,
    ) -> None:
        from worker import sync_immich_albums

        parent_id = "albums-int-parent"
        await _seed_parent(repo, parent_id)

        patches, api_client, _svc = _stub_immich(
            batches=[["a1", "a2"], ["a3"]], kind="albums"
        )
        ctx = _batch_ctx(session_factory, redis_pool, parent_id)
        async with _apply(patches, api_client):
            result = await sync_immich_albums(ctx, "user-1", "full")

        assert result["status"] == "in_progress"

        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.IN_PROGRESS.value
        assert parent.expected_children == 2

        children = await repo.list_children(parent_id)
        assert len(children) == 2
        assert all(c.parent_job_id == parent_id for c in children)

        # Children were dispatched on the real Redis queue.
        queued = await redis_pool.queued_jobs(queue_name=IMMICH_ARQ_QUEUE_NAME)
        assert len(queued) == 2

    @pytest.mark.asyncio
    async def test_batches_complete_then_reconciler_marks_completed(
        self,
        repo: SyncJobRepository,
        session_factory: Any,
        redis_pool: Any,
    ) -> None:
        from worker import sync_immich_album_batch, sync_immich_albums

        parent_id = "albums-int-complete"
        await _seed_parent(repo, parent_id)

        patches, api_client, _svc = _stub_immich(
            batches=[["a1"], ["a2"]], kind="albums"
        )
        ctx = _batch_ctx(session_factory, redis_pool, parent_id)
        async with _apply(patches, api_client):
            await sync_immich_albums(ctx, "user-1", "full")

        children = await repo.list_children(parent_id)

        album_result = SimpleNamespace(created=1, updated=0, unchanged=0, errors=0)
        batch_patches, batch_api, batch_svc = _stub_immich(batches=[], kind="albums")
        batch_svc.sync_albums_batch = AsyncMock(return_value=album_result)
        async with _apply(batch_patches, batch_api):
            for child in children:
                child_ctx = _batch_ctx(session_factory, redis_pool, child.job_id)
                await sync_immich_album_batch(child_ctx, "user-1", ["a1"], parent_id)

        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.completed_children == 2

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )
        assert summary["completed"] == 1
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_failed_child_reconciles_parent_to_failed(
        self,
        repo: SyncJobRepository,
        session_factory: Any,
        redis_pool: Any,
    ) -> None:
        from worker import sync_immich_album_batch, sync_immich_albums

        parent_id = "albums-int-fail"
        await _seed_parent(repo, parent_id)

        patches, api_client, _svc = _stub_immich(
            batches=[["a1"], ["a2"]], kind="albums"
        )
        ctx = _batch_ctx(session_factory, redis_pool, parent_id)
        async with _apply(patches, api_client):
            await sync_immich_albums(ctx, "user-1", "full")

        children = await repo.list_children(parent_id)
        ok, bad = children[0], children[1]

        ok_result = SimpleNamespace(created=1, updated=0, unchanged=0, errors=0)
        ok_patches, ok_api, ok_svc = _stub_immich(batches=[], kind="albums")
        ok_svc.sync_albums_batch = AsyncMock(return_value=ok_result)
        async with _apply(ok_patches, ok_api):
            await sync_immich_album_batch(
                _batch_ctx(session_factory, redis_pool, ok.job_id),
                "user-1",
                ["a1"],
                parent_id,
            )

        # The other child fails on its final attempt.
        bad_patches, bad_api, bad_svc = _stub_immich(batches=[], kind="albums")
        bad_svc.sync_albums_batch = AsyncMock(side_effect=RuntimeError("boom"))
        async with _apply(bad_patches, bad_api):
            bad_ctx = _batch_ctx(session_factory, redis_pool, bad.job_id)
            bad_ctx["job_try"] = 5
            with pytest.raises(RuntimeError):
                await sync_immich_album_batch(bad_ctx, "user-1", ["a2"], parent_id)

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )
        assert summary["failed"] == 1
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.FAILED.value
        assert parent.error_message

    @pytest.mark.asyncio
    async def test_large_fanout_completes_with_correct_totals(
        self,
        repo: SyncJobRepository,
        session_factory: Any,
        redis_pool: Any,
    ) -> None:
        from worker import sync_immich_album_batch, sync_immich_albums

        parent_id = "albums-int-large"
        await _seed_parent(repo, parent_id)

        batches = [[f"a{i}"] for i in range(25)]
        patches, api_client, _svc = _stub_immich(batches=batches, kind="albums")
        ctx = _batch_ctx(session_factory, redis_pool, parent_id)
        async with _apply(patches, api_client):
            await sync_immich_albums(ctx, "user-1", "full")

        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.expected_children == 25

        children = await repo.list_children(parent_id)
        album_result = SimpleNamespace(created=1, updated=0, unchanged=0, errors=0)
        batch_patches, batch_api, batch_svc = _stub_immich(batches=[], kind="albums")
        batch_svc.sync_albums_batch = AsyncMock(return_value=album_result)
        async with _apply(batch_patches, batch_api):
            for child in children:
                await sync_immich_album_batch(
                    _batch_ctx(session_factory, redis_pool, child.job_id),
                    "user-1",
                    ["a1"],
                    parent_id,
                )

        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.completed_children == 25

        await reconcile_parents(repo, now=datetime.now(UTC), stale_after_seconds=1800.0)
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.COMPLETED.value


@pytest.mark.integration
class TestImmichPeopleFanout:
    """People fan-out persists children (previously unpersisted) and reconciles."""

    @pytest.mark.asyncio
    async def test_people_fanout_dispatches_and_reconciles_completed(
        self,
        repo: SyncJobRepository,
        session_factory: Any,
        redis_pool: Any,
    ) -> None:
        from worker import sync_immich_people, sync_immich_people_batch

        parent_id = "people-int-parent"
        await _seed_parent(repo, parent_id)

        patches, api_client, _svc = _stub_immich(
            batches=[[{"id": "p1"}], [{"id": "p2"}]], kind="people"
        )
        ctx = _batch_ctx(session_factory, redis_pool, parent_id)
        async with _apply(patches, api_client):
            result = await sync_immich_people(ctx, "user-1", "full")

        assert result["status"] == "in_progress"
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.IN_PROGRESS.value
        assert parent.expected_children == 2

        children = await repo.list_children(parent_id)
        assert len(children) == 2

        people_result = SimpleNamespace(
            created=1, linked=0, unchanged=0, updated=0, skipped=0, conflicts=0
        )
        batch_patches, batch_api, batch_svc = _stub_immich(batches=[], kind="people")
        batch_svc.sync_people_batch = AsyncMock(return_value=people_result)
        async with _apply(batch_patches, batch_api):
            for child in children:
                await sync_immich_people_batch(
                    _batch_ctx(session_factory, redis_pool, child.job_id),
                    "user-1",
                    [{"id": "p1"}],
                    parent_id,
                )

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )
        assert summary["completed"] == 1
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.COMPLETED.value

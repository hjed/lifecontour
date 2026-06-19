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


# Per-kind config so album and people fan-outs share one set of helpers.
_KINDS: dict[str, dict[str, Any]] = {
    "albums": {
        "orchestrator": "sync_immich_albums",
        "batch": "sync_immich_album_batch",
        "payload": ["a1"],
        "result": SimpleNamespace(created=1, updated=0, unchanged=0, errors=0),
    },
    "people": {
        "orchestrator": "sync_immich_people",
        "batch": "sync_immich_people_batch",
        "payload": [{"id": "p1"}],
        "result": SimpleNamespace(
            created=1, linked=0, unchanged=0, updated=0, skipped=0, conflicts=0
        ),
    },
}


def _async_gen(items: list[Any]) -> Any:
    async def _gen() -> Any:
        for item in items:
            yield item

    return _gen


@pytest_asyncio.fixture
async def redis_pool() -> AsyncIterator[Any]:
    """Real Redis pool on a dedicated DB index for the fan-out queue.

    Isolation matches the established worker integration convention
    (cf. ``test_worker_lifecycle_integration.py``): the test Redis is already
    per-workspace via ``REDIS_TEST_PORT``, and this suite uses its own DB index
    (5, distinct from the lifecycle suite's 4). ``flushdb`` gives each test a
    clean queue; queue assertions additionally check for *our* child job ids as a
    subset (below) so they never depend on exclusive ownership of the DB.
    """
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


@asynccontextmanager
async def _stubbed_immich(
    *, list_batches: list[Any] | None, sync_side: Any
) -> AsyncIterator[None]:
    """Patch the external Immich collaborators for the duration of the block.

    ``list_batches`` configures the orchestrator listing generator (or ``None``
    for a batch-only run); ``sync_side`` configures both batch sync methods
    (a return value or an exception ``side_effect``).
    """
    auth = MagicMock()
    auth.get_api_key = AsyncMock(return_value="key")
    auth.get_server_url = AsyncMock(return_value="https://immich.example.com")

    api_client = MagicMock()
    api_client.close = AsyncMock()

    sync_service = MagicMock()
    if list_batches is not None:
        sync_service.list_album_id_batches = _async_gen(list_batches)
        sync_service.list_people_batches = _async_gen(list_batches)
    mock = (
        AsyncMock(side_effect=sync_side)
        if isinstance(sync_side, BaseException)
        else AsyncMock(return_value=sync_side)
    )
    sync_service.sync_albums_batch = mock
    sync_service.sync_people_batch = mock

    with (
        patch("worker.ImmichAuthService", return_value=auth),
        patch("worker.ImmichApiClient") as api_cls,
        patch("worker.ImmichSyncService", return_value=sync_service),
    ):
        api_cls.create.return_value = api_client
        yield


async def _seed_parent(repo: SyncJobRepository, parent_id: str) -> None:
    await repo.create(
        job_id=parent_id,
        user_id="user-1",
        integration_source="immich",
        sync_type="full",
        status=SyncJobStatus.QUEUED.value,
    )


def _ctx(
    session_factory: Any, redis_pool: Any, job_id: str, **extra: Any
) -> dict[str, Any]:
    return {
        "session_factory": session_factory,
        "redis": redis_pool,
        "job_id": job_id,
        "job_try": 1,
        "max_tries": 5,
        **extra,
    }


def _worker_fn(name: str) -> Any:
    import worker

    return getattr(worker, name)


async def _dispatch(
    kind: str,
    *,
    batches: list[Any],
    session_factory: Any,
    redis_pool: Any,
    parent_id: str,
) -> dict[str, Any]:
    """Run an orchestrator under stubbed Immich and return its result dict."""
    cfg = _KINDS[kind]
    async with _stubbed_immich(list_batches=batches, sync_side=cfg["result"]):
        result: dict[str, Any] = await _worker_fn(cfg["orchestrator"])(
            _ctx(session_factory, redis_pool, parent_id), "user-1", "full"
        )
    return result


async def _run_child(
    kind: str,
    child_job_id: str,
    *,
    session_factory: Any,
    redis_pool: Any,
    parent_id: str,
    error: Exception | None = None,
    job_try: int = 1,
) -> None:
    """Run one batch child under stubbed Immich (raises if ``error`` is set)."""
    cfg = _KINDS[kind]
    async with _stubbed_immich(
        list_batches=None, sync_side=error if error else cfg["result"]
    ):
        ctx = _ctx(session_factory, redis_pool, child_job_id, job_try=job_try)
        await _worker_fn(cfg["batch"])(ctx, "user-1", cfg["payload"], parent_id)


async def _complete_all_children(
    kind: str,
    repo: SyncJobRepository,
    *,
    session_factory: Any,
    redis_pool: Any,
    parent_id: str,
) -> None:
    for child in await repo.list_children(parent_id):
        await _run_child(
            kind,
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
class TestImmichFanout:
    """Album + people fan-out dispatch, counters, and reconciliation end-to-end."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["albums", "people"])
    async def test_fanout_dispatches_persists_children_and_reconciles_completed(
        self, kind: str, repo: SyncJobRepository, session_factory: Any, redis_pool: Any
    ) -> None:
        parent_id = f"{kind}-int-complete"
        await _seed_parent(repo, parent_id)

        result = await _dispatch(
            kind,
            batches=[_KINDS[kind]["payload"], _KINDS[kind]["payload"]],
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )

        # Returned immediately as IN_PROGRESS with children persisted + dispatched.
        assert result["status"] == "in_progress"
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.IN_PROGRESS.value
        assert parent.expected_children == 2
        children = await repo.list_children(parent_id)
        assert len(children) == 2
        assert all(c.parent_job_id == parent_id for c in children)
        # Subset check: our two children were dispatched on the real queue,
        # without assuming exclusive ownership of the Redis DB index.
        queued_ids = {
            j.job_id
            for j in await redis_pool.queued_jobs(queue_name=IMMICH_ARQ_QUEUE_NAME)
        }
        assert {c.job_id for c in children} <= queued_ids

        # Children complete → counters increment → reconciler completes the parent.
        await _complete_all_children(
            kind,
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
        parent_id = "albums-int-fail"
        await _seed_parent(repo, parent_id)
        await _dispatch(
            "albums",
            batches=[["a1"], ["a2"]],
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )

        ok, bad = await repo.list_children(parent_id)
        await _run_child(
            "albums",
            ok.job_id,
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )
        # The other child fails on its final attempt.
        with pytest.raises(RuntimeError):
            await _run_child(
                "albums",
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
        parent_id = "albums-int-large"
        await _seed_parent(repo, parent_id)
        await _dispatch(
            "albums",
            batches=[[f"a{i}"] for i in range(25)],
            session_factory=session_factory,
            redis_pool=redis_pool,
            parent_id=parent_id,
        )

        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.expected_children == 25

        await _complete_all_children(
            "albums",
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

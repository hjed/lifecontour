"""Integration tests for the Snipe-IT non-blocking fan-out (#1562).

The orchestrators (``sync_snipeit_assets`` / ``sync_snipeit_maintenances``)
persist a child ``sync_jobs`` row per batch, mark their parent ``in_progress``
(``completed`` when there is nothing to do, ``failed`` when they cannot run) and
dispatch the batches; each batch job marks its own row terminal and bumps the
parent counters; the shared reconciler then finalises the parent. Postgres and
the ``sync_jobs`` repository are real; only Snipe-IT (the sync service) and the
queue (a recording stub) are stubbed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from arq import Retry
from core_shared.models.sync_job import SyncJobStatus
from core_shared.repositories.sync_job_repository import SyncJobRepository
from core_shared.sync_reconciliation import reconcile_parents
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from snipeit_rate_limiter import SnipeItRateLimitError
from snipeit_sync_window import ListedRecord


@dataclass(frozen=True)
class _Kind:
    orchestrator: str
    batch: str
    list_method: str
    sync_method: str
    child_prefix: str


_KINDS = {
    "assets": _Kind(
        orchestrator="sync_snipeit_assets",
        batch="sync_snipeit_asset_batch",
        list_method="list_asset_batches",
        sync_method="sync_asset_batch",
        child_prefix="snipeit_sync_batch",
    ),
    "maintenances": _Kind(
        orchestrator="sync_snipeit_maintenances",
        batch="sync_snipeit_maintenance_batch",
        list_method="list_maintenance_batches",
        sync_method="sync_maintenance_batch",
        child_prefix="snipeit_maint_batch",
    ),
}

_OK = {"synced": 2, "skipped": 0, "failed": 0}


class _RecordingRedis:
    """Records enqueued jobs; answers each with a job carrying its ``_job_id``.

    ``answers`` overrides the answer per call, in order: ``None`` (arq already
    holds the id) or an exception to raise.
    """

    def __init__(self, answers: list[Any] | None = None) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._answers = list(answers or [])

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any:
        self.jobs.append((function, args, kwargs))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            if answer is None:
                return None
        return MagicMock(job_id=kwargs.get("_job_id"))


@pytest_asyncio.fixture
async def session_factory(async_connection: AsyncConnection) -> Any:
    """A worker-style session factory bound to the rolled-back test connection."""

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            async_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    return _factory


@pytest.fixture
def repo(async_connection: AsyncConnection) -> SyncJobRepository:
    return SyncJobRepository(async_connection)


@pytest.fixture
def user_id() -> str:
    return f"fanout-{uuid4().hex[:8]}"


async def _insert_settings(conn: AsyncConnection, user_id: str) -> None:
    await conn.execute(
        text("""
            INSERT INTO snipeit_settings (
                user_id, base_url, snipeit_user_id, webhook_token,
                created_at, updated_at
            ) VALUES (
                :user_id, 'https://snipeit.example.com', '1', :webhook_token,
                now(), now()
            )
        """),
        {"user_id": user_id, "webhook_token": f"webhook-token-{user_id}"},
    )


async def _insert_auth(conn: AsyncConnection, user_id: str) -> None:
    await conn.execute(
        text("""
            INSERT INTO user_snipe_it_auth (
                user_id, encrypted_api_key, needs_reauth, created_at, updated_at
            ) VALUES (:user_id, 'enc-api-key', FALSE, now(), now())
        """),
        {"user_id": user_id},
    )


async def _configured(conn: AsyncConnection, user_id: str) -> None:
    await _insert_settings(conn, user_id)
    await _insert_auth(conn, user_id)


async def _seed_parent(repo: SyncJobRepository, parent_id: str, user_id: str) -> None:
    await repo.create(
        job_id=parent_id,
        user_id=user_id,
        integration_source="snipeit",
        sync_type="full",
        status=SyncJobStatus.QUEUED.value,
    )


def _stub_service(
    kind: _Kind,
    *,
    batches: list[list[int]] | None = None,
    pages: list[list[ListedRecord]] | None = None,
    list_error: Exception | None = None,
    sync_result: dict[str, int] | Exception = _OK,
) -> MagicMock:
    """A stand-in for ``SnipeItSyncService`` configured for one kind.

    ``batches`` lists ids with no ``updated_at``, which every run fetches;
    ``pages`` lists records as given.
    """
    listed = pages or [
        [ListedRecord(record_id, None) for record_id in batch]
        for batch in batches or []
    ]

    async def _list() -> AsyncIterator[list[ListedRecord]]:
        for page in listed:
            yield page
        if list_error is not None:
            raise list_error

    service = MagicMock()
    setattr(service, kind.list_method, _list)
    service.reconcile_deleted_maintenances = AsyncMock(return_value=0)
    service.unsettled_maintenance_ids = AsyncMock(return_value=set())
    sync = (
        AsyncMock(side_effect=sync_result)
        if isinstance(sync_result, Exception)
        else AsyncMock(return_value=sync_result)
    )
    setattr(service, kind.sync_method, sync)
    service._api_client.close = AsyncMock()
    return service


def _ctx(
    session_factory: Any, redis: Any, job_id: str, *, job_try: int = 1
) -> dict[str, Any]:
    return {
        "session_factory": session_factory,
        "redis": redis,
        "job_id": job_id,
        "job_try": job_try,
        "max_tries": 5,
    }


def _worker_fn(name: str) -> Any:
    import worker

    return getattr(worker, name)


async def _orchestrate(
    kind: _Kind,
    service: MagicMock | Exception,
    *,
    session_factory: Any,
    redis: _RecordingRedis,
    parent_id: str,
    user_id: str,
    sync_type: str = "full",
) -> Any:
    """Run an orchestrator whose sync service is ``service`` (or raises it)."""
    stub = (
        {"side_effect": service}
        if isinstance(service, Exception)
        else {"return_value": service}
    )
    with patch("worker._create_sync_service", **stub):
        return await _worker_fn(kind.orchestrator)(
            _ctx(session_factory, redis, parent_id), user_id, sync_type
        )


async def _run_batch(
    kind: _Kind,
    service: MagicMock | Exception,
    *,
    session_factory: Any,
    child_id: str,
    user_id: str,
    ids: list[int],
    parent_id: str | None,
    job_try: int = 1,
) -> Any:
    stub = (
        {"side_effect": service}
        if isinstance(service, Exception)
        else {"return_value": service}
    )
    with patch("worker._create_sync_service", **stub):
        return await _worker_fn(kind.batch)(
            _ctx(session_factory, _RecordingRedis(), child_id, job_try=job_try),
            user_id,
            ids,
            parent_id,
        )


async def _status(repo: SyncJobRepository, job_id: str) -> Any:
    job = await repo.get_by_job_id(job_id)
    assert job is not None
    return job


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
async def test_orchestrator_persists_children_and_dispatches_them(
    kind_name: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()

    await _orchestrate(
        kind,
        _stub_service(kind, batches=[[1, 2], [], [3]]),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
    )

    parent = await _status(repo, parent_id)
    assert parent.status == SyncJobStatus.IN_PROGRESS.value
    assert parent.expected_children == 2
    assert parent.started_at is not None

    child_ids = [
        f"{kind.child_prefix}:{user_id}:{parent_id}:1",
        f"{kind.child_prefix}:{user_id}:{parent_id}:2",
    ]
    children = await repo.list_children(parent_id)
    assert sorted(c.job_id for c in children) == child_ids
    assert {c.status for c in children} == {SyncJobStatus.QUEUED.value}

    assert [(fn, args, kw["_job_id"]) for fn, args, kw in redis.jobs] == [
        (kind.batch, (user_id, [1, 2], parent_id), child_ids[0]),
        (kind.batch, (user_id, [3], parent_id), child_ids[1]),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
async def test_orchestrator_with_nothing_to_sync_completes_parent(
    kind_name: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()

    await _orchestrate(
        kind,
        _stub_service(kind, batches=[]),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
    )

    parent = await _status(repo, parent_id)
    assert parent.status == SyncJobStatus.COMPLETED.value
    assert parent.expected_children == 0
    assert redis.jobs == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
@pytest.mark.parametrize(
    ("with_settings", "with_auth", "message"),
    [
        (False, True, "Snipe-IT settings not configured"),
        (True, False, "Snipe-IT credentials not configured"),
    ],
)
async def test_orchestrator_without_configuration_fails_parent(
    kind_name: str,
    with_settings: bool,
    with_auth: bool,
    message: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    if with_settings:
        await _insert_settings(async_connection, user_id)
    if with_auth:
        await _insert_auth(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()

    await _orchestrate(
        kind,
        _stub_service(kind, batches=[[1]]),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
    )

    parent = await _status(repo, parent_id)
    assert parent.status == SyncJobStatus.FAILED.value
    assert parent.error_message == message
    assert parent.completed_at is not None
    assert redis.jobs == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
async def test_orchestrator_listing_that_fails_part_way_dispatches_nothing(
    kind_name: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()
    service = _stub_service(
        kind, batches=[[1, 2]], list_error=RuntimeError("page 2 failed")
    )

    with pytest.raises(RuntimeError, match="page 2 failed"):
        await _orchestrate(
            kind,
            service,
            session_factory=session_factory,
            redis=redis,
            parent_id=parent_id,
            user_id=user_id,
        )

    parent = await _status(repo, parent_id)
    assert parent.status == SyncJobStatus.FAILED.value
    assert parent.error_message == "page 2 failed"
    assert await repo.list_children(parent_id) == []
    assert redis.jobs == []
    service.reconcile_deleted_maintenances.assert_not_awaited()
    service._api_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_maintenance_orchestrator_reconciles_deletions_before_dispatch(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["maintenances"]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()
    service = _stub_service(kind, batches=[[10, 20], [30]])

    async def _reconcile(listed_ids: Any, _session_factory: Any) -> int:
        assert redis.jobs == [], "deletions reconcile before any batch is sent"
        assert set(listed_ids) == {10, 20, 30}
        return 0

    service.reconcile_deleted_maintenances.side_effect = _reconcile

    await _orchestrate(
        kind,
        service,
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
    )

    service.reconcile_deleted_maintenances.assert_awaited_once()
    assert len(redis.jobs) == 2


# ---------------------------------------------------------------------------
# Smart sync (#1560)
# ---------------------------------------------------------------------------

_CURSOR = "2026-10-07 09:00:00"
_CURSOR_AT = datetime(2026, 10, 7, 9)


async def _seed_completed(
    repo: SyncJobRepository,
    user_id: str,
    kind_name: str,
    *,
    cursor: str | None = _CURSOR,
    sync_type: str = "full",
    status: SyncJobStatus = SyncJobStatus.COMPLETED,
    age: timedelta = timedelta(days=1),
) -> None:
    """A finished earlier run of this kind that recorded ``cursor``."""
    job_id = f"earlier-{uuid4().hex}"
    await repo.create(
        job_id=job_id,
        user_id=user_id,
        integration_source="snipeit",
        sync_type=sync_type,
        status=SyncJobStatus.RUNNING.value,
    )
    await repo.record_listing(
        job_id, resource=kind_name, cursor=cursor, sync_type=sync_type
    )
    await repo.update_status(job_id, status.value, completed_at=datetime.now(UTC) - age)


def _pages_around_cursor() -> list[list[ListedRecord]]:
    """One record older than the overlap, one inside it, one newer."""
    return [
        [
            ListedRecord(1, _CURSOR_AT - timedelta(hours=2)),
            ListedRecord(2, _CURSOR_AT - timedelta(minutes=30)),
        ],
        [ListedRecord(3, _CURSOR_AT + timedelta(minutes=5))],
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
async def test_smart_orchestrator_dispatches_only_records_changed_since_cursor(
    kind_name: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_completed(repo, user_id, kind_name)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()

    await _orchestrate(
        kind,
        _stub_service(kind, pages=_pages_around_cursor()),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
        sync_type="smart",
    )

    assert [args[1] for _, args, _ in redis.jobs] == [[2], [3]]
    parent = await _status(repo, parent_id)
    assert (parent.sync_type, parent.sync_resource, parent.sync_cursor) == (
        "smart",
        kind_name,
        "2026-10-07 09:05:00",
    )
    assert {c.sync_type for c in await repo.list_children(parent_id)} == {"smart"}


@pytest.mark.asyncio
async def test_smart_orchestrator_ignores_the_cursor_of_a_failed_run(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["assets"]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_completed(repo, user_id, "assets", age=timedelta(days=2))
    await _seed_completed(
        repo,
        user_id,
        "assets",
        cursor="2026-10-07 12:00:00",
        status=SyncJobStatus.FAILED,
        age=timedelta(days=1),
    )
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()

    await _orchestrate(
        kind,
        _stub_service(kind, pages=_pages_around_cursor()),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
        sync_type="smart",
    )

    assert [args[1] for _, args, _ in redis.jobs] == [[2], [3]]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
@pytest.mark.parametrize(
    "earlier",
    [
        pytest.param({}, id="no-earlier-run"),
        pytest.param({"sync_type": "smart"}, id="no-full-run"),
        pytest.param({"age": timedelta(days=8)}, id="stale-full-run"),
    ],
)
async def test_smart_orchestrator_runs_as_full_when_it_cannot_resume(
    kind_name: str,
    earlier: dict[str, Any],
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    if earlier:
        await _seed_completed(repo, user_id, kind_name, **earlier)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()

    await _orchestrate(
        kind,
        _stub_service(kind, pages=_pages_around_cursor()),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
        sync_type="smart",
    )

    assert [args[1] for _, args, _ in redis.jobs] == [[1, 2], [3]]
    parent = await _status(repo, parent_id)
    assert (parent.sync_type, parent.sync_cursor) == ("full", "2026-10-07 09:05:00")
    assert {c.sync_type for c in await repo.list_children(parent_id)} == {"full"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
@pytest.mark.parametrize("table", ["snipeit_settings", "user_snipe_it_auth"])
async def test_smart_orchestrator_runs_as_full_after_settings_change(
    kind_name: str,
    table: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    """A changed URL, user mapping or API key invalidates the cursor, which
    may come from another instance's clock: it is not carried forward."""
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_completed(repo, user_id, kind_name, cursor="2026-10-08 15:00:00")
    # The test shares one transaction, so now() is the earlier run's start too.
    await async_connection.execute(
        text(
            f"UPDATE {table} SET updated_at = now() + interval '1 minute' "  # noqa: S608
            "WHERE user_id = :user_id"
        ),
        {"user_id": user_id},
    )
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()

    await _orchestrate(
        kind,
        _stub_service(kind, pages=_pages_around_cursor()),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
        sync_type="smart",
    )

    assert [args[1] for _, args, _ in redis.jobs] == [[1, 2], [3]]
    parent = await _status(repo, parent_id)
    assert (parent.sync_type, parent.sync_cursor) == ("full", "2026-10-07 09:05:00")


@pytest.mark.asyncio
async def test_smart_maintenance_orchestrator_reconciles_every_listed_record(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["maintenances"]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_completed(repo, user_id, "maintenances")
    await _seed_parent(repo, parent_id, user_id)
    service = _stub_service(kind, pages=_pages_around_cursor())

    await _orchestrate(
        kind,
        service,
        session_factory=session_factory,
        redis=_RecordingRedis(),
        parent_id=parent_id,
        user_id=user_id,
        sync_type="smart",
    )

    [call] = service.reconcile_deleted_maintenances.await_args_list
    assert set(call.args[0]) == {1, 2, 3}


@pytest.mark.asyncio
async def test_smart_maintenance_orchestrator_also_fetches_unsettled_records(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["maintenances"]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_completed(repo, user_id, "maintenances")
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()
    pages = _pages_around_cursor()
    service = _stub_service(kind, pages=pages)
    # 1 is unchanged but unsettled; 3 is both, and is fetched once.
    service.unsettled_maintenance_ids.return_value = {1, 3}

    await _orchestrate(
        kind,
        service,
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
        sync_type="smart",
    )

    [call] = service.unsettled_maintenance_ids.await_args_list
    assert call.args[0] == [record for page in pages for record in page]
    assert [args[1] for _, args, _ in redis.jobs] == [[2], [3], [1]]
    parent = await _status(repo, parent_id)
    assert parent.expected_children == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
async def test_full_orchestrator_does_not_look_for_unsettled_records(
    kind_name: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    service = _stub_service(kind, pages=_pages_around_cursor())

    await _orchestrate(
        kind,
        service,
        session_factory=session_factory,
        redis=_RecordingRedis(),
        parent_id=parent_id,
        user_id=user_id,
    )

    service.unsettled_maintenance_ids.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
async def test_smart_orchestrator_with_no_changes_carries_the_cursor_forward(
    kind_name: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_completed(repo, user_id, kind_name)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()
    unchanged = [[ListedRecord(1, _CURSOR_AT - timedelta(days=3))]]

    await _orchestrate(
        kind,
        _stub_service(kind, pages=unchanged),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
        sync_type="smart",
    )

    assert redis.jobs == []
    parent = await _status(repo, parent_id)
    assert parent.status == SyncJobStatus.COMPLETED.value
    assert (parent.sync_type, parent.sync_cursor) == ("smart", _CURSOR)


@pytest.mark.asyncio
async def test_full_orchestrator_dispatches_everything_and_records_the_cursor(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["assets"]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_completed(repo, user_id, "assets")
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()

    await _orchestrate(
        kind,
        _stub_service(kind, pages=_pages_around_cursor()),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
    )

    assert [args[1] for _, args, _ in redis.jobs] == [[1, 2], [3]]
    parent = await _status(repo, parent_id)
    assert (parent.sync_type, parent.sync_resource, parent.sync_cursor) == (
        "full",
        "assets",
        "2026-10-07 09:05:00",
    )


@pytest.mark.asyncio
async def test_maintenance_orchestrator_whose_reconciliation_fails_dispatches_nothing(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["maintenances"]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()
    service = _stub_service(kind, batches=[[10]])
    service.reconcile_deleted_maintenances.side_effect = RuntimeError("lookup failed")

    with pytest.raises(RuntimeError, match="lookup failed"):
        await _orchestrate(
            kind,
            service,
            session_factory=session_factory,
            redis=redis,
            parent_id=parent_id,
            user_id=user_id,
        )

    parent = await _status(repo, parent_id)
    assert parent.status == SyncJobStatus.FAILED.value
    assert await repo.list_children(parent_id) == []
    assert redis.jobs == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
async def test_orchestrator_whose_sync_service_cannot_be_built_fails_parent(
    kind_name: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    """Not only missing configuration: any error building the service (an
    undecryptable key, say) must not leave the parent ``running``."""
    kind = _KINDS[kind_name]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()

    with pytest.raises(ValueError, match="bad key"):
        await _orchestrate(
            kind,
            ValueError("bad key"),
            session_factory=session_factory,
            redis=redis,
            parent_id=parent_id,
            user_id=user_id,
        )

    parent = await _status(repo, parent_id)
    assert parent.status == SyncJobStatus.FAILED.value
    assert parent.error_message == "bad key"
    assert redis.jobs == []


@pytest.mark.asyncio
async def test_batches_that_cannot_be_enqueued_are_failed(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    """A queue error part-way through dispatch fails every batch not yet sent,
    so the parent finalises instead of waiting out the staleness window."""
    kind = _KINDS["assets"]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis(answers=[MagicMock(), ConnectionError("redis down")])

    with pytest.raises(ConnectionError, match="redis down"):
        await _orchestrate(
            kind,
            _stub_service(kind, batches=[[1], [2], [3]]),
            session_factory=session_factory,
            redis=redis,
            parent_id=parent_id,
            user_id=user_id,
        )

    prefix = f"{kind.child_prefix}:{user_id}:{parent_id}:"
    statuses = {
        c.job_id: (c.status, c.error_message)
        for c in await repo.list_children(parent_id)
    }
    assert statuses == {
        f"{prefix}1": (SyncJobStatus.QUEUED.value, None),
        f"{prefix}2": (
            SyncJobStatus.FAILED.value,
            "Batch was not enqueued: redis down",
        ),
        f"{prefix}3": (
            SyncJobStatus.FAILED.value,
            "Batch was not enqueued: redis down",
        ),
    }
    assert (await _status(repo, parent_id)).failed_children == 2


@pytest.mark.asyncio
async def test_batch_already_held_by_arq_is_not_counted_as_enqueued(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    """arq answers ``None`` for an id it already holds: a retried orchestrator
    re-sending a batch its first attempt queued. That batch still runs, so its
    row stays queued, but this attempt did not enqueue it."""
    kind = _KINDS["assets"]
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis(answers=[None])

    result = await _orchestrate(
        kind,
        _stub_service(kind, batches=[[1], [2]]),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
    )

    assert result["batches_enqueued"] == 1
    children = await repo.list_children(parent_id)
    assert {c.status for c in children} == {SyncJobStatus.QUEUED.value}


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------


async def _fan_out(
    kind: _Kind,
    *,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
    batches: list[list[int]],
) -> tuple[str, _RecordingRedis]:
    """Configure the user, seed a parent and run its orchestrator."""
    parent_id = f"parent-{uuid4().hex}"
    await _configured(async_connection, user_id)
    await _seed_parent(repo, parent_id, user_id)
    redis = _RecordingRedis()
    await _orchestrate(
        kind,
        _stub_service(kind, batches=batches),
        session_factory=session_factory,
        redis=redis,
        parent_id=parent_id,
        user_id=user_id,
    )
    return parent_id, redis


@pytest.mark.asyncio
@pytest.mark.parametrize("kind_name", ["assets", "maintenances"])
async def test_completed_batches_complete_the_parent_on_reconciliation(
    kind_name: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id, redis = await _fan_out(
        kind,
        async_connection=async_connection,
        session_factory=session_factory,
        repo=repo,
        user_id=user_id,
        batches=[[1, 2], [3]],
    )

    for _fn, (uid, ids, parent), kwargs in redis.jobs:
        result = await _run_batch(
            kind,
            _stub_service(kind),
            session_factory=session_factory,
            child_id=kwargs["_job_id"],
            user_id=uid,
            ids=ids,
            parent_id=parent,
        )
        assert result == _OK

    children = await repo.list_children(parent_id)
    assert {c.status for c in children} == {SyncJobStatus.COMPLETED.value}
    assert (await _status(repo, parent_id)).completed_children == 2

    await reconcile_parents(repo, now=datetime.now(UTC), stale_after_seconds=1800)

    assert (await _status(repo, parent_id)).status == SyncJobStatus.COMPLETED.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind_name", "noun"), [("assets", "assets"), ("maintenances", "maintenances")]
)
async def test_batch_with_failed_items_fails_the_parent(
    kind_name: str,
    noun: str,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS[kind_name]
    parent_id, redis = await _fan_out(
        kind,
        async_connection=async_connection,
        session_factory=session_factory,
        repo=repo,
        user_id=user_id,
        batches=[[1, 2, 3]],
    )
    _fn, (uid, ids, parent), kwargs = redis.jobs[0]
    partial = {"synced": 1, "skipped": 0, "failed": 2}

    result = await _run_batch(
        kind,
        _stub_service(kind, sync_result=partial),
        session_factory=session_factory,
        child_id=kwargs["_job_id"],
        user_id=uid,
        ids=ids,
        parent_id=parent,
    )

    assert result == partial
    child = await _status(repo, kwargs["_job_id"])
    assert child.status == SyncJobStatus.FAILED.value
    assert child.error_message == f"2 of 3 {noun} failed to sync"

    await reconcile_parents(repo, now=datetime.now(UTC), stale_after_seconds=1800)

    assert (await _status(repo, parent_id)).status == SyncJobStatus.FAILED.value


@pytest.mark.asyncio
async def test_batch_that_raises_records_child_failed_and_reraises(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["assets"]
    parent_id, redis = await _fan_out(
        kind,
        async_connection=async_connection,
        session_factory=session_factory,
        repo=repo,
        user_id=user_id,
        batches=[[1]],
    )
    _fn, (uid, ids, parent), kwargs = redis.jobs[0]

    with pytest.raises(RuntimeError, match="boom"):
        await _run_batch(
            kind,
            _stub_service(kind, sync_result=RuntimeError("boom")),
            session_factory=session_factory,
            child_id=kwargs["_job_id"],
            user_id=uid,
            ids=ids,
            parent_id=parent,
        )

    child = await _status(repo, kwargs["_job_id"])
    assert child.status == SyncJobStatus.FAILED.value
    assert child.error_message == "boom"
    assert (await _status(repo, parent_id)).failed_children == 1


@pytest.mark.asyncio
async def test_rate_limited_batch_is_retried_until_its_final_attempt(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["assets"]
    parent_id, redis = await _fan_out(
        kind,
        async_connection=async_connection,
        session_factory=session_factory,
        repo=repo,
        user_id=user_id,
        batches=[[1]],
    )
    _fn, (uid, ids, parent), kwargs = redis.jobs[0]
    child_id = kwargs["_job_id"]

    def _limited() -> MagicMock:
        return _stub_service(
            kind, sync_result=SnipeItRateLimitError("slow down", retry_after=42)
        )

    with pytest.raises(Retry) as retry:
        await _run_batch(
            kind,
            _limited(),
            session_factory=session_factory,
            child_id=child_id,
            user_id=uid,
            ids=ids,
            parent_id=parent,
            job_try=1,
        )
    assert retry.value.defer_score == 42_000
    assert (await _status(repo, child_id)).status == SyncJobStatus.QUEUED.value

    with pytest.raises(SnipeItRateLimitError):
        await _run_batch(
            kind,
            _limited(),
            session_factory=session_factory,
            child_id=child_id,
            user_id=uid,
            ids=ids,
            parent_id=parent,
            job_try=5,
        )
    assert (await _status(repo, child_id)).status == SyncJobStatus.FAILED.value
    assert (await _status(repo, parent_id)).failed_children == 1


@pytest.mark.asyncio
async def test_batch_without_credentials_records_child_failed(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["maintenances"]
    parent_id, redis = await _fan_out(
        kind,
        async_connection=async_connection,
        session_factory=session_factory,
        repo=repo,
        user_id=user_id,
        batches=[[1, 2]],
    )
    _fn, (uid, ids, parent), kwargs = redis.jobs[0]
    await async_connection.execute(
        text("DELETE FROM user_snipe_it_auth WHERE user_id = :user_id"),
        {"user_id": user_id},
    )

    result = await _run_batch(
        kind,
        _stub_service(kind),
        session_factory=session_factory,
        child_id=kwargs["_job_id"],
        user_id=uid,
        ids=ids,
        parent_id=parent,
    )

    assert result == {"synced": 0, "skipped": 0, "failed": 2}
    child = await _status(repo, kwargs["_job_id"])
    assert child.status == SyncJobStatus.FAILED.value
    assert child.error_message == "Snipe-IT credentials not configured"
    assert (await _status(repo, parent_id)).failed_children == 1


@pytest.mark.asyncio
async def test_batch_whose_sync_service_cannot_be_built_records_child_failed(
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    kind = _KINDS["assets"]
    parent_id, redis = await _fan_out(
        kind,
        async_connection=async_connection,
        session_factory=session_factory,
        repo=repo,
        user_id=user_id,
        batches=[[1]],
    )
    _fn, (uid, ids, parent), kwargs = redis.jobs[0]

    with pytest.raises(ValueError, match="bad key"):
        await _run_batch(
            kind,
            ValueError("bad key"),
            session_factory=session_factory,
            child_id=kwargs["_job_id"],
            user_id=uid,
            ids=ids,
            parent_id=parent,
        )

    child = await _status(repo, kwargs["_job_id"])
    assert child.status == SyncJobStatus.FAILED.value
    assert child.error_message == "bad key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retry_after", "expected_ms"),
    [(3600.0, 360_000), (5.0, 5_000)],
)
async def test_rate_limit_deferral_stays_inside_the_staleness_window(
    retry_after: float,
    expected_ms: int,
    async_connection: AsyncConnection,
    session_factory: Any,
    repo: SyncJobRepository,
    user_id: str,
) -> None:
    """A deferred batch does not move its parent's ``updated_at``, so every
    retry together must fit the reconciler's window (1800s over 5 tries) or the
    parent is failed as stuck before the batch runs again."""
    kind = _KINDS["assets"]
    _parent_id, redis = await _fan_out(
        kind,
        async_connection=async_connection,
        session_factory=session_factory,
        repo=repo,
        user_id=user_id,
        batches=[[1]],
    )
    _fn, (uid, ids, parent), kwargs = redis.jobs[0]

    with pytest.raises(Retry) as retry:
        await _run_batch(
            kind,
            _stub_service(
                kind,
                sync_result=SnipeItRateLimitError("slow", retry_after=retry_after),
            ),
            session_factory=session_factory,
            child_id=kwargs["_job_id"],
            user_id=uid,
            ids=ids,
            parent_id=parent,
        )

    assert retry.value.defer_score == expected_ms


@pytest.mark.asyncio
async def test_batch_without_parent_writes_no_sync_jobs(
    async_connection: AsyncConnection,
    session_factory: Any,
    user_id: str,
) -> None:
    """A batch queued before the fan-out existed carries no parent id."""
    kind = _KINDS["assets"]
    await _configured(async_connection, user_id)
    child_id = f"legacy-{uuid4().hex}"

    result = await _run_batch(
        kind,
        _stub_service(kind),
        session_factory=session_factory,
        child_id=child_id,
        user_id=user_id,
        ids=[1, 2],
        parent_id=None,
    )

    assert result == _OK
    rows = (
        await async_connection.execute(
            text("SELECT count(*) FROM sync_jobs WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
    ).scalar_one()
    assert rows == 0

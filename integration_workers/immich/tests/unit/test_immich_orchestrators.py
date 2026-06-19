"""Unit tests for the non-blocking Immich fan-out orchestrators (ITER14-003 P3).

`sync_immich_albums` and `sync_immich_people` share one code path
(`_run_immich_fanout`): drain the batch generator, persist one linked child
`sync_jobs` row per batch, set `expected_children`, mark the parent
`in_progress` and return immediately — no `asyncio.gather`. Both orchestrators
are parametrized here since they differ only in the listing method and payload
shape. The Immich auth/api/sync collaborators and `SyncJobRepository` are mocked
so the test exercises only the orchestration contract.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    db_port = os.environ.get("DB_TEST_PORT", "5432")
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test",
    )
    monkeypatch.setenv("ENCRYPTION_KEY", "testkey")


# (orchestrator name, sync_service listing attribute, batch payload factory)
_ORCHESTRATORS = [
    pytest.param(
        "sync_immich_albums",
        "list_album_id_batches",
        lambda i: [f"a{i}"],
        id="albums",
    ),
    pytest.param(
        "sync_immich_people",
        "list_people_batches",
        lambda i: [{"id": f"p{i}"}],
        id="people",
    ),
]


def _async_gen(items: list[Any]) -> Any:
    """Return a zero-arg callable producing a fresh async generator of ``items``."""

    async def _gen() -> Any:
        for item in items:
            yield item

    return _gen


def _make_ctx(job_id: str) -> tuple[dict[str, Any], MagicMock, MagicMock]:
    """Build a mock ARQ ctx plus the mock redis and enqueued-job for assertions."""
    mock_session = AsyncMock()
    mock_session.connection = AsyncMock(return_value=AsyncMock())
    mock_session.commit = AsyncMock()

    @asynccontextmanager
    async def _session_ctx() -> AsyncIterator[Any]:
        yield mock_session

    mock_redis = MagicMock()
    enqueued_job = MagicMock()
    enqueued_job.result = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value=enqueued_job)

    ctx: dict[str, Any] = {
        "session_factory": MagicMock(side_effect=lambda: _session_ctx()),
        "redis": mock_redis,
        "job_id": job_id,
    }
    return ctx, mock_redis, enqueued_job


@asynccontextmanager
async def _patched(
    *,
    repo: MagicMock,
    list_attr: str,
    batches: list[Any],
    credentials: bool = True,
) -> AsyncIterator[None]:
    """Patch the Immich collaborators; ``list_attr`` yields ``batches``."""
    auth = MagicMock()
    auth.get_api_key = AsyncMock(return_value="key" if credentials else None)
    auth.get_server_url = AsyncMock(
        return_value="https://immich.example.com" if credentials else None
    )

    api_client = MagicMock()
    api_client.close = AsyncMock()

    sync_service = MagicMock()
    setattr(sync_service, list_attr, _async_gen(batches))

    with (
        patch("worker.ImmichAuthService", return_value=auth),
        patch("worker.ImmichApiClient") as api_cls,
        patch("worker.ImmichSyncService", return_value=sync_service),
        patch("worker.SyncJobRepository", return_value=repo),
    ):
        api_cls.create.return_value = api_client
        yield


def _make_repo() -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.set_expected_children = AsyncMock()
    repo.update_status = AsyncMock()
    return repo


def _orchestrator(name: str) -> Any:
    import worker

    return getattr(worker, name)


def _statuses(repo: MagicMock) -> list[str]:
    return [
        c.kwargs.get("status") or c.args[1] for c in repo.update_status.await_args_list
    ]


@pytest.mark.parametrize(("name", "list_attr", "payload"), _ORCHESTRATORS)
class TestNonBlockingOrchestrators:
    """Both orchestrators dispatch and return without awaiting their children."""

    @pytest.mark.asyncio
    async def test_returns_in_progress_without_awaiting_children(
        self, name: str, list_attr: str, payload: Any
    ) -> None:
        ctx, mock_redis, enqueued_job = _make_ctx(f"{name}-parent")
        repo = _make_repo()
        batches = [payload(1), payload(2)]
        async with _patched(repo=repo, list_attr=list_attr, batches=batches):
            result = await _orchestrator(name)(ctx, "user-1", "full")

        assert result["status"] == "in_progress"
        assert result["batches_enqueued"] == 2
        # One enqueue per batch, and no child result was ever awaited (no gather).
        assert mock_redis.enqueue_job.await_count == 2
        enqueued_job.result.assert_not_called()

    @pytest.mark.asyncio
    async def test_persists_children_and_sets_expected_and_in_progress(
        self, name: str, list_attr: str, payload: Any
    ) -> None:
        job_id = f"{name}-parent-x"
        ctx, _redis, _job = _make_ctx(job_id)
        repo = _make_repo()
        batches = [payload(1), payload(2), payload(3)]
        async with _patched(repo=repo, list_attr=list_attr, batches=batches):
            await _orchestrator(name)(ctx, "user-1", "full")

        # One child row per batch, each linked to the parent and queued.
        assert repo.create.await_count == 3
        for call in repo.create.await_args_list:
            assert call.kwargs["parent_job_id"] == job_id
            assert call.kwargs["status"] == "queued"
        repo.set_expected_children.assert_awaited_once_with(job_id, 3)
        statuses = _statuses(repo)
        assert "in_progress" in statuses
        assert "completed" not in statuses

    @pytest.mark.asyncio
    async def test_zero_batches_marks_parent_completed(
        self, name: str, list_attr: str, payload: Any
    ) -> None:
        ctx, mock_redis, _job = _make_ctx(f"{name}-empty")
        repo = _make_repo()
        async with _patched(repo=repo, list_attr=list_attr, batches=[]):
            result = await _orchestrator(name)(ctx, "user-1", "full")

        assert result["status"] == "completed"
        mock_redis.enqueue_job.assert_not_called()
        repo.set_expected_children.assert_awaited_once_with(ctx["job_id"], 0)
        statuses = _statuses(repo)
        assert "completed" in statuses
        assert "in_progress" not in statuses

    @pytest.mark.asyncio
    async def test_missing_credentials_marks_failed(
        self, name: str, list_attr: str, payload: Any
    ) -> None:
        ctx, mock_redis, _job = _make_ctx(f"{name}-nocreds")
        repo = _make_repo()
        async with _patched(
            repo=repo, list_attr=list_attr, batches=[], credentials=False
        ):
            result = await _orchestrator(name)(ctx, "user-1", "full")

        assert result["status"] == "error"
        assert "credentials" in result["message"].lower()
        mock_redis.enqueue_job.assert_not_called()

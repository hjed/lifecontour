"""Unit tests for the non-blocking ``sync_immich_people`` orchestrator (ITER14-003 P3).

Previously ``sync_immich_people`` blocked on ``asyncio.gather`` and never
persisted its children. It now drains the people batch generator, persists one
child ``sync_jobs`` row per page linked to the parent, sets ``expected_children``,
marks the parent ``in_progress`` and returns immediately.
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


def _async_gen(items: list[Any]) -> Any:
    async def _gen() -> Any:
        for item in items:
            yield item

    return _gen


def _make_ctx(
    job_id: str = "people-parent-1",
) -> tuple[dict[str, Any], MagicMock, MagicMock]:
    mock_session = AsyncMock()
    mock_conn = AsyncMock()
    mock_session.connection = AsyncMock(return_value=mock_conn)
    mock_session.commit = AsyncMock()

    @asynccontextmanager
    async def _session_ctx() -> AsyncIterator[Any]:
        yield mock_session

    session_factory = MagicMock(side_effect=lambda: _session_ctx())

    mock_redis = MagicMock()
    enqueued_job = MagicMock()
    enqueued_job.job_id = "enqueued"
    enqueued_job.result = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value=enqueued_job)

    ctx: dict[str, Any] = {
        "session_factory": session_factory,
        "redis": mock_redis,
        "job_id": job_id,
    }
    return ctx, mock_redis, enqueued_job


@asynccontextmanager
async def _patched_collaborators(
    *,
    repo: MagicMock,
    people_batches: list[list[dict[str, Any]]],
    credentials: bool = True,
) -> AsyncIterator[None]:
    auth = MagicMock()
    auth.get_api_key = AsyncMock(return_value="key" if credentials else None)
    auth.get_server_url = AsyncMock(
        return_value="https://immich.example.com" if credentials else None
    )

    api_client = MagicMock()
    api_client.close = AsyncMock()

    sync_service = MagicMock()
    sync_service.list_people_batches = _async_gen(people_batches)

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


class TestSyncImmichPeopleNonBlocking:
    """``sync_immich_people`` dispatches and returns without awaiting children."""

    @pytest.mark.asyncio
    async def test_returns_in_progress_without_awaiting_children(self) -> None:
        from worker import sync_immich_people

        ctx, mock_redis, enqueued_job = _make_ctx()
        repo = _make_repo()
        async with _patched_collaborators(
            repo=repo, people_batches=[[{"id": "p1"}], [{"id": "p2"}]]
        ):
            result = await sync_immich_people(ctx, "user-1", "full")

        assert result["status"] == "in_progress"
        assert result["batches_enqueued"] == 2
        assert mock_redis.enqueue_job.await_count == 2
        enqueued_job.result.assert_not_called()

    @pytest.mark.asyncio
    async def test_persists_children_and_sets_expected_and_in_progress(self) -> None:
        from worker import sync_immich_people

        ctx, _redis, _job = _make_ctx(job_id="people-parent-x")
        repo = _make_repo()
        async with _patched_collaborators(
            repo=repo, people_batches=[[{"id": "p1"}], [{"id": "p2"}], [{"id": "p3"}]]
        ):
            await sync_immich_people(ctx, "user-1", "full")

        assert repo.create.await_count == 3
        for call in repo.create.await_args_list:
            assert call.kwargs["parent_job_id"] == "people-parent-x"
            assert call.kwargs["status"] == "queued"
        repo.set_expected_children.assert_awaited_once_with("people-parent-x", 3)
        statuses = [
            c.kwargs.get("status") or c.args[1]
            for c in repo.update_status.await_args_list
        ]
        assert "in_progress" in statuses
        assert "completed" not in statuses

    @pytest.mark.asyncio
    async def test_zero_batches_marks_parent_completed(self) -> None:
        from worker import sync_immich_people

        ctx, mock_redis, _job = _make_ctx()
        repo = _make_repo()
        async with _patched_collaborators(repo=repo, people_batches=[]):
            result = await sync_immich_people(ctx, "user-1", "full")

        assert result["status"] == "completed"
        mock_redis.enqueue_job.assert_not_called()
        repo.set_expected_children.assert_awaited_once_with(ctx["job_id"], 0)
        statuses = [
            c.kwargs.get("status") or c.args[1]
            for c in repo.update_status.await_args_list
        ]
        assert "completed" in statuses
        assert "in_progress" not in statuses

    @pytest.mark.asyncio
    async def test_missing_credentials_marks_failed(self) -> None:
        from worker import sync_immich_people

        ctx, mock_redis, _job = _make_ctx()
        repo = _make_repo()
        async with _patched_collaborators(
            repo=repo, people_batches=[], credentials=False
        ):
            result = await sync_immich_people(ctx, "user-1", "full")

        assert result["status"] == "error"
        assert "credentials" in result["message"].lower()
        mock_redis.enqueue_job.assert_not_called()

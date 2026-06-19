"""Unit tests for child-row + parent-counter updates in the Immich batch jobs.

After ITER14-003 Phase 3 each batch job (``sync_immich_album_batch`` /
``sync_immich_people_batch``) owns a persisted ``sync_jobs`` child row. On success
it marks its own row ``completed`` and atomically increments the parent's
``completed_children``; on a **final**-attempt failure it marks its row ``failed``
and increments ``failed_children``. A non-final failure just re-raises so ARQ
retries, without prematurely bumping a counter.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
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


def _make_ctx(*, job_id: str, job_try: int = 1, max_tries: int = 5) -> dict[str, Any]:
    mock_session = AsyncMock()
    mock_conn = AsyncMock()
    mock_session.connection = AsyncMock(return_value=mock_conn)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    @asynccontextmanager
    async def _session_ctx() -> AsyncIterator[Any]:
        yield mock_session

    return {
        "session_factory": MagicMock(side_effect=lambda: _session_ctx()),
        "job_id": job_id,
        "job_try": job_try,
        "max_tries": max_tries,
    }


def _make_repo() -> MagicMock:
    repo = MagicMock()
    repo.update_status = AsyncMock()
    repo.increment_completed_children = AsyncMock()
    repo.increment_failed_children = AsyncMock()
    return repo


@asynccontextmanager
async def _patched(
    *, repo: MagicMock, batch_result: Any, batch_error: Exception | None
) -> AsyncIterator[MagicMock]:
    auth = MagicMock()
    auth.get_api_key = AsyncMock(return_value="key")
    auth.get_server_url = AsyncMock(return_value="https://immich.example.com")

    api_client = MagicMock()
    api_client.close = AsyncMock()

    sync_service = MagicMock()
    if batch_error is not None:
        sync_service.sync_albums_batch = AsyncMock(side_effect=batch_error)
        sync_service.sync_people_batch = AsyncMock(side_effect=batch_error)
    else:
        sync_service.sync_albums_batch = AsyncMock(return_value=batch_result)
        sync_service.sync_people_batch = AsyncMock(return_value=batch_result)

    with (
        patch("worker.ImmichAuthService", return_value=auth),
        patch("worker.ImmichApiClient") as api_cls,
        patch("worker.ImmichSyncService", return_value=sync_service),
        patch("worker.SyncJobRepository", return_value=repo),
    ):
        api_cls.create.return_value = api_client
        yield sync_service


_ALBUM_RESULT = SimpleNamespace(created=1, updated=0, unchanged=0, errors=0)
_PEOPLE_RESULT = SimpleNamespace(
    created=1, linked=0, unchanged=0, updated=0, skipped=0, conflicts=0
)


class TestAlbumBatchCounters:
    @pytest.mark.asyncio
    async def test_success_marks_completed_and_increments(self) -> None:
        from worker import sync_immich_album_batch

        ctx = _make_ctx(job_id="album-child-1")
        repo = _make_repo()
        async with _patched(repo=repo, batch_result=_ALBUM_RESULT, batch_error=None):
            result = await sync_immich_album_batch(
                ctx, "user-1", ["a1"], "albums-parent-1"
            )

        assert result["status"] == "success"
        repo.update_status.assert_awaited_once()
        update_kwargs = repo.update_status.await_args.kwargs
        assert update_kwargs["job_id"] == "album-child-1"
        assert update_kwargs["status"] == "completed"
        repo.increment_completed_children.assert_awaited_once_with("albums-parent-1")
        repo.increment_failed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_final_failure_marks_failed_and_increments(self) -> None:
        from worker import sync_immich_album_batch

        ctx = _make_ctx(job_id="album-child-2", job_try=5, max_tries=5)
        repo = _make_repo()
        async with _patched(
            repo=repo, batch_result=None, batch_error=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError):
                await sync_immich_album_batch(ctx, "user-1", ["a1"], "albums-parent-1")

        repo.increment_failed_children.assert_awaited_once_with("albums-parent-1")
        repo.increment_completed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_final_failure_does_not_increment(self) -> None:
        from worker import sync_immich_album_batch

        ctx = _make_ctx(job_id="album-child-3", job_try=1, max_tries=5)
        repo = _make_repo()
        async with _patched(
            repo=repo, batch_result=None, batch_error=RuntimeError("transient")
        ):
            with pytest.raises(RuntimeError):
                await sync_immich_album_batch(ctx, "user-1", ["a1"], "albums-parent-1")

        repo.increment_failed_children.assert_not_called()
        repo.increment_completed_children.assert_not_called()


class TestPeopleBatchCounters:
    @pytest.mark.asyncio
    async def test_success_marks_completed_and_increments(self) -> None:
        from worker import sync_immich_people_batch

        ctx = _make_ctx(job_id="people-child-1")
        repo = _make_repo()
        async with _patched(repo=repo, batch_result=_PEOPLE_RESULT, batch_error=None):
            result = await sync_immich_people_batch(
                ctx, "user-1", [{"id": "p1"}], "people-parent-1"
            )

        assert result["status"] == "success"
        repo.increment_completed_children.assert_awaited_once_with("people-parent-1")
        repo.increment_failed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_final_failure_marks_failed_and_increments(self) -> None:
        from worker import sync_immich_people_batch

        ctx = _make_ctx(job_id="people-child-2", job_try=5, max_tries=5)
        repo = _make_repo()
        async with _patched(
            repo=repo, batch_result=None, batch_error=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError):
                await sync_immich_people_batch(
                    ctx, "user-1", [{"id": "p1"}], "people-parent-1"
                )

        repo.increment_failed_children.assert_awaited_once_with("people-parent-1")
        repo.increment_completed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_final_failure_does_not_increment(self) -> None:
        from worker import sync_immich_people_batch

        ctx = _make_ctx(job_id="people-child-3", job_try=2, max_tries=5)
        repo = _make_repo()
        async with _patched(
            repo=repo, batch_result=None, batch_error=RuntimeError("transient")
        ):
            with pytest.raises(RuntimeError):
                await sync_immich_people_batch(
                    ctx, "user-1", [{"id": "p1"}], "people-parent-1"
                )

        repo.increment_failed_children.assert_not_called()
        repo.increment_completed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_call_without_parent_skips_counters(self) -> None:
        from worker import sync_immich_people_batch

        ctx = _make_ctx(job_id="people-child-legacy")
        repo = _make_repo()
        async with _patched(repo=repo, batch_result=_PEOPLE_RESULT, batch_error=None):
            result = await sync_immich_people_batch(ctx, "user-1", [{"id": "p1"}])

        assert result["status"] == "success"
        repo.increment_completed_children.assert_not_called()

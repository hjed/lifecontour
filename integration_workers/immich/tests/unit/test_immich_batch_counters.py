"""Unit tests for child-row + parent-counter updates in the Immich batch jobs.

After ITER14-003 Phase 3 each batch job (``sync_immich_album_batch`` /
``sync_immich_people_batch``) owns a persisted ``sync_jobs`` child row. On success
it marks its own row ``completed`` and atomically increments the parent's
``completed_children``; on a **final**-attempt failure it marks its row ``failed``
and increments ``failed_children``. A non-final failure just re-raises so ARQ
retries, without prematurely bumping a counter. Both batch jobs share one code
path (``_run_immich_batch``) so they are parametrized here.
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


_ALBUM_RESULT = SimpleNamespace(created=1, updated=0, unchanged=0, errors=0)
_PEOPLE_RESULT = SimpleNamespace(
    created=1, linked=0, unchanged=0, updated=0, skipped=0, conflicts=0
)

# (batch func, sync_service method, batch payload, success result)
_BATCHES = [
    pytest.param(
        "sync_immich_album_batch",
        "sync_albums_batch",
        ["a1"],
        _ALBUM_RESULT,
        id="albums",
    ),
    pytest.param(
        "sync_immich_people_batch",
        "sync_people_batch",
        [{"id": "p1"}],
        _PEOPLE_RESULT,
        id="people",
    ),
]


def _make_ctx(*, job_id: str, job_try: int = 1, max_tries: int = 5) -> dict[str, Any]:
    mock_session = AsyncMock()
    mock_session.connection = AsyncMock(return_value=AsyncMock())
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
    *, repo: MagicMock, method: str, result: Any, error: Exception | None
) -> AsyncIterator[None]:
    auth = MagicMock()
    auth.get_api_key = AsyncMock(return_value="key")
    auth.get_server_url = AsyncMock(return_value="https://immich.example.com")

    api_client = MagicMock()
    api_client.close = AsyncMock()

    sync_service = MagicMock()
    setattr(
        sync_service,
        method,
        AsyncMock(side_effect=error) if error else AsyncMock(return_value=result),
    )

    with (
        patch("worker.ImmichAuthService", return_value=auth),
        patch("worker.ImmichApiClient") as api_cls,
        patch("worker.ImmichSyncService", return_value=sync_service),
        patch("worker.SyncJobRepository", return_value=repo),
    ):
        api_cls.create.return_value = api_client
        yield


def _batch(name: str) -> Any:
    import worker

    return getattr(worker, name)


@pytest.mark.parametrize(("name", "method", "payload", "result"), _BATCHES)
class TestBatchCounters:
    @pytest.mark.asyncio
    async def test_success_marks_completed_and_increments(
        self, name: str, method: str, payload: Any, result: Any
    ) -> None:
        ctx = _make_ctx(job_id=f"{name}-child-ok")
        repo = _make_repo()
        async with _patched(repo=repo, method=method, result=result, error=None):
            out = await _batch(name)(ctx, "user-1", payload, f"{name}-parent")

        assert out["status"] == "success"
        repo.update_status.assert_awaited_once()
        update_kwargs = repo.update_status.await_args.kwargs
        assert update_kwargs["job_id"] == f"{name}-child-ok"
        assert update_kwargs["status"] == "completed"
        repo.increment_completed_children.assert_awaited_once_with(f"{name}-parent")
        repo.increment_failed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_final_failure_marks_failed_and_increments(
        self, name: str, method: str, payload: Any, result: Any
    ) -> None:
        ctx = _make_ctx(job_id=f"{name}-child-fail", job_try=5, max_tries=5)
        repo = _make_repo()
        async with _patched(
            repo=repo, method=method, result=None, error=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError):
                await _batch(name)(ctx, "user-1", payload, f"{name}-parent")

        repo.increment_failed_children.assert_awaited_once_with(f"{name}-parent")
        repo.increment_completed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_final_failure_does_not_increment(
        self, name: str, method: str, payload: Any, result: Any
    ) -> None:
        ctx = _make_ctx(job_id=f"{name}-child-retry", job_try=1, max_tries=5)
        repo = _make_repo()
        async with _patched(
            repo=repo, method=method, result=None, error=RuntimeError("transient")
        ):
            with pytest.raises(RuntimeError):
                await _batch(name)(ctx, "user-1", payload, f"{name}-parent")

        repo.increment_failed_children.assert_not_called()
        repo.increment_completed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_call_without_parent_skips_counters(
        self, name: str, method: str, payload: Any, result: Any
    ) -> None:
        ctx = _make_ctx(job_id=f"{name}-child-legacy")
        repo = _make_repo()
        async with _patched(repo=repo, method=method, result=result, error=None):
            out = await _batch(name)(ctx, "user-1", payload)

        assert out["status"] == "success"
        repo.increment_completed_children.assert_not_called()
        repo.increment_failed_children.assert_not_called()


@pytest.mark.asyncio
async def test_missing_child_row_skips_counter_increment() -> None:
    """If the child row update matches no row, the parent counter is NOT bumped.

    Guards against a stray/incorrect ``ctx['job_id']`` decoupling the counter
    (and the parent's ``updated_at``) from a real terminal child row, which would
    otherwise interfere with reconciliation/staleness.
    """
    ctx = _make_ctx(job_id="missing-child")
    repo = _make_repo()
    repo.update_status = AsyncMock(return_value=None)  # no row matched
    async with _patched(
        repo=repo, method="sync_albums_batch", result=_ALBUM_RESULT, error=None
    ):
        from worker import sync_immich_album_batch

        out = await sync_immich_album_batch(ctx, "user-1", ["a1"], "some-parent")

    assert out["status"] == "success"
    repo.increment_completed_children.assert_not_called()

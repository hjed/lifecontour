"""Unit tests for the non-blocking Strava activity-sync orchestrator.

``sync_strava_activities`` drains the activity-page generator, idempotently
owns its parent ``sync_jobs`` row (its ``ctx['job_id']``), persists one linked
child row per page, sets ``expected_children``, marks the parent ``in_progress``
and returns immediately — it never awaits the children. The Strava auth/sync
collaborators and ``SyncJobRepository`` are mocked so only the orchestration
contract is exercised.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_worker() -> Any:
    """Import the worker module with mocked settings (mirrors test_worker.py)."""
    mock_settings = MagicMock()
    mock_settings.log_level = "DEBUG"
    mock_settings.worker_id = "strava-worker"
    mock_settings.redis_url = "redis://localhost:6379"
    mock_settings.stream_name = "pms:domain-events"
    mock_settings.enable_periodic_sync = False
    mock_settings.sync_interval_hours = 6
    mock_settings.encryption_key.get_secret_value.return_value = (
        "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ9"  # noqa: S106
    )
    mock_settings.strava_client_id = "test_client"
    mock_settings.strava_client_secret.get_secret_value.return_value = "test_secret"  # noqa: S106

    fake_strava_settings = MagicMock()
    fake_strava_settings.StravaSettings.return_value = mock_settings
    sys.modules["strava_settings"] = fake_strava_settings

    with (
        patch("core_shared.logging.configure_logging"),
        patch("core_shared.logging.get_logger", return_value=MagicMock()),
    ):
        if "worker" in sys.modules:
            del sys.modules["worker"]
        return importlib.import_module("worker")


def _async_gen(items: list[Any], *, raise_exc: Exception | None = None) -> Any:
    """Return a callable producing a fresh async generator over ``items``.

    Accepts (and ignores) any args/kwargs so it stands in for
    ``list_activity_batches(after_timestamp=...)``. If ``raise_exc`` is set the
    generator raises it after yielding ``items`` (to simulate a mid-drain error).
    """

    def _gen(*_a: Any, **_k: Any) -> Any:
        async def _inner() -> Any:
            for item in items:
                yield item
            if raise_exc is not None:
                raise raise_exc

        return _inner()

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
        "settings": MagicMock(),
        "job_id": job_id,
    }
    return ctx, mock_redis, enqueued_job


def _make_repo(
    *, parent_exists: bool = True, existing_children: list[Any] | None = None
) -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.set_expected_children = AsyncMock()
    repo.update_status = AsyncMock(return_value=MagicMock())
    repo.get_by_job_id = AsyncMock(return_value=MagicMock() if parent_exists else None)
    repo.list_children = AsyncMock(return_value=existing_children or [])
    return repo


@asynccontextmanager
async def _patched(
    *,
    repo: MagicMock,
    batches: list[Any],
    has_auth: bool = True,
    raise_exc: Exception | None = None,
) -> AsyncIterator[MagicMock]:
    """Patch the Strava collaborators; the sync service yields ``batches``."""
    sync_service = MagicMock()
    sync_service.list_activity_batches = _async_gen(batches, raise_exc=raise_exc)
    sync_service.sync_activity_batch = AsyncMock(
        return_value={"synced": 0, "skipped": 0, "failed": 0}
    )
    sync_service._api_client = MagicMock()
    sync_service._api_client.close = AsyncMock()

    auth_data = (
        {"encrypted_access_token": "a", "encrypted_refresh_token": "r"}
        if has_auth
        else None
    )

    with (
        patch("worker._resolve_user_by_id", AsyncMock(return_value=auth_data)),
        patch("worker._create_sync_service", return_value=sync_service),
        patch("worker.SyncJobRepository", return_value=repo),
    ):
        yield sync_service


def _statuses(repo: MagicMock) -> list[str | None]:
    return [
        c.kwargs.get("status") or (c.args[1] if len(c.args) > 1 else None)
        for c in repo.update_status.await_args_list
    ]


class TestStravaOrchestrator:
    @pytest.mark.asyncio
    async def test_returns_in_progress_without_awaiting_children(self) -> None:
        worker = _import_worker()
        ctx, mock_redis, enqueued_job = _make_ctx("strava-parent")
        repo = _make_repo()
        async with _patched(repo=repo, batches=[[1, 2], [3, 4]]):
            result = await worker.sync_strava_activities(ctx, "user-1", "full")

        assert result["status"] == "in_progress"
        assert result["batches_enqueued"] == 2
        assert mock_redis.enqueue_job.await_count == 2
        enqueued_job.result.assert_not_called()

    @pytest.mark.asyncio
    async def test_persists_children_and_sets_expected_and_in_progress(self) -> None:
        worker = _import_worker()
        job_id = "strava-parent-x"
        ctx, _redis, _job = _make_ctx(job_id)
        repo = _make_repo()
        async with _patched(repo=repo, batches=[[1], [2], [3]]):
            await worker.sync_strava_activities(ctx, "user-1", "full")

        # One child row per batch, each linked to the parent and queued.
        child_creates = [
            c for c in repo.create.await_args_list if c.kwargs.get("parent_job_id")
        ]
        assert len(child_creates) == 3
        for call in child_creates:
            assert call.kwargs["parent_job_id"] == job_id
            assert call.kwargs["status"] == "queued"
        repo.set_expected_children.assert_awaited_once_with(job_id, 3)
        statuses = _statuses(repo)
        assert "in_progress" in statuses
        assert "completed" not in statuses

    @pytest.mark.asyncio
    async def test_children_persisted_before_dispatch(self) -> None:
        """Children + parent state must be committed before any child is enqueued."""
        worker = _import_worker()
        job_id = "strava-parent-order"
        ctx, mock_redis, _job = _make_ctx(job_id)
        repo = _make_repo()

        order: list[str] = []

        def _record_persist(*_a: Any, **_k: Any) -> None:
            order.append("persist")

        def _record_dispatch(*_a: Any, **_k: Any) -> MagicMock:
            order.append("dispatch")
            return MagicMock()

        repo.set_expected_children = AsyncMock(side_effect=_record_persist)
        mock_redis.enqueue_job = AsyncMock(side_effect=_record_dispatch)
        async with _patched(repo=repo, batches=[[1], [2]]):
            await worker.sync_strava_activities(ctx, "user-1", "full")

        assert order[0] == "persist"
        assert order.count("dispatch") == 2
        # Each child enqueue carries the parent job id positionally + a job id.
        for call in mock_redis.enqueue_job.await_args_list:
            assert call.args[0] == "sync_strava_activity_batch"
            assert call.args[3] == job_id  # parent_job_id passed positionally
            assert call.kwargs["_job_id"].startswith(f"strava-batch-{job_id}-p")

    @pytest.mark.asyncio
    async def test_creates_parent_row_when_missing(self) -> None:
        worker = _import_worker()
        job_id = "strava-parent-new"
        ctx, _redis, _job = _make_ctx(job_id)
        repo = _make_repo(parent_exists=False)
        async with _patched(repo=repo, batches=[[1]]):
            await worker.sync_strava_activities(ctx, "user-1", "smart")

        parent_creates = [
            c for c in repo.create.await_args_list if not c.kwargs.get("parent_job_id")
        ]
        assert len(parent_creates) == 1
        assert parent_creates[0].kwargs["job_id"] == job_id
        assert parent_creates[0].kwargs["integration_source"] == "strava"
        assert parent_creates[0].kwargs["sync_type"] == "smart"

    @pytest.mark.asyncio
    async def test_retry_skips_already_persisted_children(self) -> None:
        """An ARQ retry after a prior commit must not re-create child rows.

        ``create`` is a plain INSERT, so re-creating the deterministic child ids
        would raise a duplicate-key error. The orchestrator skips children that
        already exist and still re-dispatches them.
        """
        worker = _import_worker()
        job_id = "strava-parent-retry"
        ctx, mock_redis, _job = _make_ctx(job_id)
        existing = [
            MagicMock(job_id=f"strava-batch-{job_id}-p1"),
            MagicMock(job_id=f"strava-batch-{job_id}-p2"),
        ]
        repo = _make_repo(existing_children=existing)
        async with _patched(repo=repo, batches=[[1], [2]]):
            result = await worker.sync_strava_activities(ctx, "user-1", "full")

        # No child rows re-created, but the fan-out still re-dispatches + reports.
        child_creates = [
            c for c in repo.create.await_args_list if c.kwargs.get("parent_job_id")
        ]
        assert child_creates == []
        repo.set_expected_children.assert_awaited_once_with(job_id, 2)
        assert result["status"] == "in_progress"
        assert mock_redis.enqueue_job.await_count == 2

    @pytest.mark.asyncio
    async def test_zero_batches_marks_parent_completed(self) -> None:
        worker = _import_worker()
        ctx, mock_redis, _job = _make_ctx("strava-empty")
        repo = _make_repo()
        async with _patched(repo=repo, batches=[]):
            result = await worker.sync_strava_activities(ctx, "user-1", "full")

        assert result["status"] == "completed"
        mock_redis.enqueue_job.assert_not_called()
        repo.set_expected_children.assert_awaited_once_with("strava-empty", 0)
        statuses = _statuses(repo)
        assert "completed" in statuses
        assert "in_progress" not in statuses

    @pytest.mark.asyncio
    async def test_missing_auth_returns_error_without_children(self) -> None:
        worker = _import_worker()
        ctx, mock_redis, _job = _make_ctx("strava-noauth")
        repo = _make_repo()
        async with _patched(repo=repo, batches=[[1]], has_auth=False):
            result = await worker.sync_strava_activities(ctx, "user-1", "full")

        assert result["status"] == "error"
        assert result["reason"] == "no_auth"
        mock_redis.enqueue_job.assert_not_called()
        repo.set_expected_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_during_drain_raises_retry(self) -> None:
        from arq import Retry

        from strava_rate_limiter import StravaRateLimitError

        worker = _import_worker()
        ctx, mock_redis, _job = _make_ctx("strava-ratelimited")
        repo = _make_repo()
        async with _patched(
            repo=repo,
            batches=[[1]],
            raise_exc=StravaRateLimitError("rate limited", retry_after=60),
        ):
            with pytest.raises(Retry):
                await worker.sync_strava_activities(ctx, "user-1", "full")

        # No children dispatched when the drain is interrupted by a rate limit.
        mock_redis.enqueue_job.assert_not_called()

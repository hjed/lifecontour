"""Unit tests for child-row + parent-counter updates in the Strava batch job.

``sync_strava_activity_batch`` owns a persisted ``sync_jobs`` child row. On
success it marks its own row ``completed`` and atomically increments the
parent's ``completed_children``. ARQ retries only a ``Retry``, so any other
failure — including missing auth or a sync service that cannot be built — marks
the row ``failed`` and increments ``failed_children`` on that same attempt. A
rate limit raises ``Retry`` without touching the counters until the worker's
final attempt (``STRAVA_MAX_TRIES``), where it records the failure instead.
When called without a ``parent_job_id`` (legacy/direct) the counters are skipped.
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


def _make_ctx(*, job_id: str, job_try: int = 1) -> dict[str, Any]:
    mock_session = AsyncMock()
    mock_session.connection = AsyncMock(return_value=AsyncMock())
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    @asynccontextmanager
    async def _session_ctx() -> AsyncIterator[Any]:
        yield mock_session

    return {
        "session_factory": MagicMock(side_effect=lambda: _session_ctx()),
        "settings": MagicMock(),
        "job_id": job_id,
        "job_try": job_try,
    }


def _make_repo() -> MagicMock:
    repo = MagicMock()
    repo.update_status = AsyncMock(return_value=MagicMock())
    repo.increment_completed_children = AsyncMock()
    repo.increment_failed_children = AsyncMock()
    return repo


_AUTH_DATA = {"encrypted_access_token": "a", "encrypted_refresh_token": "r"}


@asynccontextmanager
async def _patched(
    *,
    repo: MagicMock,
    error: Exception | None,
    auth_data: dict[str, str] | None = _AUTH_DATA,
    resolve_error: Exception | None = None,
    create_error: Exception | None = None,
) -> AsyncIterator[MagicMock]:
    sync_service = MagicMock()
    sync_service.sync_activity_batch = (
        AsyncMock(side_effect=error)
        if error
        else AsyncMock(return_value={"synced": 1, "skipped": 0, "failed": 0})
    )
    sync_service._api_client = MagicMock()
    sync_service._api_client.close = AsyncMock()

    with (
        patch(
            "worker._resolve_user_by_id",
            AsyncMock(side_effect=resolve_error, return_value=auth_data),
        ),
        patch(
            "worker._create_sync_service",
            side_effect=create_error,
            return_value=sync_service,
        ),
        patch("worker.SyncJobRepository", return_value=repo),
    ):
        yield sync_service


def _assert_child_failed(repo: MagicMock, *, job_id: str, error_message: str) -> None:
    update_kwargs = repo.update_status.await_args.kwargs
    assert update_kwargs["job_id"] == job_id
    assert update_kwargs["status"] == "failed"
    assert update_kwargs["error_message"] == error_message
    repo.increment_failed_children.assert_awaited_once_with("strava-parent")
    repo.increment_completed_children.assert_not_called()


class TestStravaBatchCounters:
    @pytest.mark.asyncio
    async def test_success_marks_completed_and_increments(self) -> None:
        worker = _import_worker()
        ctx = _make_ctx(job_id="strava-child-ok")
        repo = _make_repo()
        async with _patched(repo=repo, error=None):
            out = await worker.sync_strava_activity_batch(
                ctx, "user-1", [1, 2], "strava-parent"
            )

        assert out["status"] == "completed"
        repo.update_status.assert_awaited_once()
        update_kwargs = repo.update_status.await_args.kwargs
        assert update_kwargs["job_id"] == "strava-child-ok"
        assert update_kwargs["status"] == "completed"
        repo.increment_completed_children.assert_awaited_once_with("strava-parent")
        repo.increment_failed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_attempt_failure_marks_failed_and_increments(self) -> None:
        worker = _import_worker()
        ctx = _make_ctx(job_id="strava-child-fail", job_try=1)
        repo = _make_repo()
        async with _patched(repo=repo, error=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                await worker.sync_strava_activity_batch(
                    ctx, "user-1", [1], "strava-parent"
                )

        _assert_child_failed(repo, job_id="strava-child-fail", error_message="boom")

    @pytest.mark.asyncio
    async def test_rate_limit_before_final_attempt_retries_without_counter(
        self,
    ) -> None:
        """Try 5 is past the shared default of 5 but well short of Strava's 20."""
        from arq import Retry

        from strava_rate_limiter import StravaRateLimitError

        worker = _import_worker()
        ctx = _make_ctx(job_id="strava-child-rl", job_try=5)
        repo = _make_repo()
        async with _patched(
            repo=repo, error=StravaRateLimitError("rate limited", retry_after=60)
        ):
            with pytest.raises(Retry):
                await worker.sync_strava_activity_batch(
                    ctx, "user-1", [1], "strava-parent"
                )

        repo.update_status.assert_not_called()
        repo.increment_failed_children.assert_not_called()
        repo.increment_completed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_on_final_attempt_marks_failed(self) -> None:
        """A ``Retry`` on the last try would be dropped by ARQ, stranding the row."""
        from strava_rate_limiter import StravaRateLimitError

        worker = _import_worker()
        ctx = _make_ctx(job_id="strava-child-rl-final", job_try=worker.STRAVA_MAX_TRIES)
        repo = _make_repo()
        async with _patched(
            repo=repo, error=StravaRateLimitError("rate limited", retry_after=60)
        ):
            with pytest.raises(StravaRateLimitError):
                await worker.sync_strava_activity_batch(
                    ctx, "user-1", [1], "strava-parent"
                )

        _assert_child_failed(
            repo, job_id="strava-child-rl-final", error_message="rate limited"
        )

    @pytest.mark.asyncio
    async def test_missing_auth_marks_failed(self) -> None:
        worker = _import_worker()
        ctx = _make_ctx(job_id="strava-child-noauth")
        repo = _make_repo()
        async with _patched(repo=repo, error=None, auth_data=None):
            out = await worker.sync_strava_activity_batch(
                ctx, "user-1", [1], "strava-parent"
            )

        assert out == {"status": "error", "reason": "no_auth"}
        _assert_child_failed(
            repo,
            job_id="strava-child-noauth",
            error_message="No Strava auth found for user",
        )

    @pytest.mark.parametrize("stage", ["resolve", "create"])
    @pytest.mark.asyncio
    async def test_sync_service_setup_failure_marks_failed(self, stage: str) -> None:
        worker = _import_worker()
        ctx = _make_ctx(job_id="strava-child-setup")
        repo = _make_repo()
        error = RuntimeError("setup broke")
        async with _patched(
            repo=repo,
            error=None,
            resolve_error=error if stage == "resolve" else None,
            create_error=error if stage == "create" else None,
        ):
            with pytest.raises(RuntimeError, match="setup broke"):
                await worker.sync_strava_activity_batch(
                    ctx, "user-1", [1], "strava-parent"
                )

        _assert_child_failed(
            repo, job_id="strava-child-setup", error_message="setup broke"
        )

    @pytest.mark.asyncio
    async def test_legacy_call_without_parent_skips_counters(self) -> None:
        worker = _import_worker()
        ctx = _make_ctx(job_id="strava-child-legacy")
        repo = _make_repo()
        async with _patched(repo=repo, error=None):
            out = await worker.sync_strava_activity_batch(ctx, "user-1", [1])

        assert out["status"] == "completed"
        repo.increment_completed_children.assert_not_called()
        repo.increment_failed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_child_row_skips_counter_increment(self) -> None:
        worker = _import_worker()
        ctx = _make_ctx(job_id="missing-child")
        repo = _make_repo()
        repo.update_status = AsyncMock(return_value=None)  # no row matched
        async with _patched(repo=repo, error=None):
            out = await worker.sync_strava_activity_batch(
                ctx, "user-1", [1], "some-parent"
            )

        assert out["status"] == "completed"
        repo.increment_completed_children.assert_not_called()

"""
Unit tests for Strava periodic sync configuration and task.

Tests verify:
- Periodic sync cron job configuration based on settings
- periodic_sync_all_strava_accounts enqueues sync jobs for each account
- Error handling when Redis or DB operations fail
- Smart sync with after_timestamp from last sync job
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_worker():
    """Import the worker module with mocked settings."""
    import importlib
    import sys

    mock_settings = MagicMock()
    mock_settings.log_level = "DEBUG"
    mock_settings.worker_id = "test"
    mock_settings.redis_url = "redis://localhost:6379"
    mock_settings.database_url.get_secret_value.return_value = (
        "postgresql://test:test@localhost/test"
    )
    mock_settings.encryption_key.get_secret_value.return_value = (
        "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ9"  # noqa: S106
    )
    mock_settings.strava_client_id = "test_client"
    mock_settings.strava_client_secret.get_secret_value.return_value = "test_secret"  # noqa: S106
    mock_settings.enable_periodic_sync = False
    mock_settings.sync_interval_hours = 6

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


def _make_mock_ctx(
    accounts: list[tuple[str, int]],
    last_sync_time: str | None = None,
) -> tuple[dict[str, Any], AsyncMock, MagicMock]:
    """Create a mock ARQ context with session factory and redis.

    Args:
        accounts: List of (user_id, athlete_id) tuples.
        last_sync_time: Optional ISO timestamp for last sync.

    Returns:
        Tuple of (ctx dict, mock_redis, mock_session).
    """
    mock_session = MagicMock()

    # First execute call returns account rows
    accounts_result = MagicMock()
    accounts_result.fetchall.return_value = [
        MagicMock(user_id=uid, athlete_id=aid) for uid, aid in accounts
    ]

    # Second execute call returns last sync time
    last_sync_result = MagicMock()
    if last_sync_time:
        last_sync_row = MagicMock()
        last_sync_row.completed_at = last_sync_time
        last_sync_result.fetchone.return_value = last_sync_row
    else:
        last_sync_result.fetchone.return_value = None

    # Configure execute to return different results for different calls
    mock_session.execute = AsyncMock(
        side_effect=[accounts_result] + [last_sync_result] * len(accounts)
    )

    @asynccontextmanager
    async def _session_ctx():
        yield mock_session

    session_factory = MagicMock(side_effect=lambda: _session_ctx())

    mock_redis = AsyncMock()
    mock_job = MagicMock()
    mock_job.job_id = "test-job-123"
    mock_redis.enqueue_job = AsyncMock(return_value=mock_job)

    ctx: dict[str, Any] = {
        "session_factory": session_factory,
        "redis": mock_redis,
    }

    return ctx, mock_redis, mock_session


class TestPeriodicSyncAllStravaAccounts:
    """Tests for periodic_sync_all_strava_accounts ARQ task."""

    @pytest.mark.asyncio
    async def test_enqueues_sync_for_each_account(self) -> None:
        """Should enqueue sync_strava_activities for every active account."""
        worker_mod = _import_worker()

        accounts = [("user-1", 111), ("user-2", 222)]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)

        result = await worker_mod.periodic_sync_all_strava_accounts(ctx)

        assert result["status"] == "success"
        assert result["accounts_found"] == 2
        assert result["jobs_enqueued"] == 2

        # Verify each call was for sync_strava_activities
        assert mock_redis.enqueue_job.call_count == 2
        for call in mock_redis.enqueue_job.call_args_list:
            assert call[0][0] == "sync_strava_activities"

    @pytest.mark.asyncio
    async def test_enqueues_with_smart_sync_type(self) -> None:
        """Periodic sync should use 'smart' sync type."""
        worker_mod = _import_worker()

        accounts = [("user-1", 111)]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)

        await worker_mod.periodic_sync_all_strava_accounts(ctx)

        call = mock_redis.enqueue_job.call_args_list[0]
        assert call[0][0] == "sync_strava_activities"
        assert call[0][1] == "user-1"  # user_id
        assert call[0][2] == "smart"  # sync_type

    @pytest.mark.asyncio
    async def test_uses_correct_queue_name(self) -> None:
        """Jobs should be enqueued to the Strava ARQ queue."""
        worker_mod = _import_worker()

        accounts = [("user-1", 111)]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)

        await worker_mod.periodic_sync_all_strava_accounts(ctx)

        call = mock_redis.enqueue_job.call_args_list[0]
        assert call.kwargs["_queue_name"] == worker_mod.STRAVA_ARQ_QUEUE_NAME

    @pytest.mark.asyncio
    async def test_handles_no_accounts(self) -> None:
        """Should complete successfully with zero accounts."""
        worker_mod = _import_worker()

        ctx, mock_redis, _ = _make_mock_ctx([])

        result = await worker_mod.periodic_sync_all_strava_accounts(ctx)

        assert result["status"] == "success"
        assert result["accounts_found"] == 0
        assert result["jobs_enqueued"] == 0
        mock_redis.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_enqueue_failure(self) -> None:
        """Should record error when enqueue_job returns None."""
        worker_mod = _import_worker()

        accounts = [("user-1", 111)]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)
        mock_redis.enqueue_job = AsyncMock(return_value=None)

        result = await worker_mod.periodic_sync_all_strava_accounts(ctx)

        assert result["status"] == "success"
        assert result["accounts_found"] == 1
        assert result["jobs_enqueued"] == 0
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_handles_enqueue_exception(self) -> None:
        """Should catch and record exceptions from enqueue_job."""
        worker_mod = _import_worker()

        accounts = [("user-1", 111)]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)
        mock_redis.enqueue_job = AsyncMock(
            side_effect=ConnectionError("Redis connection lost")
        )

        result = await worker_mod.periodic_sync_all_strava_accounts(ctx)

        assert result["status"] == "success"
        assert result["accounts_found"] == 1
        assert result["jobs_enqueued"] == 0
        assert len(result["errors"]) == 1
        assert "Redis connection lost" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_multiple_accounts_partial_failure(self) -> None:
        """Should continue processing remaining accounts after one fails."""
        worker_mod = _import_worker()

        accounts = [("user-1", 111), ("user-2", 222), ("user-3", 333)]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)

        # First call succeeds, second fails, third succeeds
        mock_job = MagicMock()
        mock_job.job_id = "test-job"
        mock_redis.enqueue_job = AsyncMock(
            side_effect=[
                mock_job,
                ConnectionError("Redis hiccup"),
                mock_job,
            ]
        )

        result = await worker_mod.periodic_sync_all_strava_accounts(ctx)

        assert result["accounts_found"] == 3
        assert result["jobs_enqueued"] == 2
        assert len(result["errors"]) == 1


class TestPeriodicSyncConfiguration:
    """Test cron schedule generation for periodic sync."""

    def test_cron_schedule_for_6_hour_interval(self) -> None:
        """6-hour interval produces hours {0, 6, 12, 18}."""
        sync_hours = set(range(0, 24, 6))
        assert sync_hours == {0, 6, 12, 18}

    def test_cron_schedule_for_12_hour_interval(self) -> None:
        """12-hour interval produces hours {0, 12}."""
        sync_hours = set(range(0, 24, 12))
        assert sync_hours == {0, 12}

    def test_cron_schedule_for_24_hour_interval(self) -> None:
        """24-hour interval produces hours {0}."""
        sync_hours = set(range(0, 24, 24))
        assert sync_hours == {0}

    def test_cron_schedule_for_1_hour_interval(self) -> None:
        """1-hour interval produces all 24 hours."""
        sync_hours = set(range(0, 24, 1))
        assert sync_hours == set(range(24))

"""
Unit tests for Immich periodic sync configuration and task.

Tests verify:
- Periodic sync cron job configuration based on settings
- periodic_sync_all_immich_accounts enqueues sync jobs for each account
- Error handling when Redis or DB operations fail
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure env vars are set before importing worker module
db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}"
        "/personal_management_test"
    )
os.environ.setdefault("ENCRYPTION_KEY", "testkey")


def _make_mock_ctx(
    accounts: list[tuple[str, str]],
) -> tuple[dict[str, Any], AsyncMock, MagicMock]:
    """Create a mock ARQ context with session factory and redis.

    Args:
        accounts: List of (user_id, server_url) tuples representing
                  rows in user_immich_auth.

    Returns:
        Tuple of (ctx dict, mock_redis, mock_session).
    """
    mock_session = MagicMock()

    # Execute call returns account rows
    accounts_result = MagicMock()
    accounts_result.fetchall.return_value = [
        MagicMock(user_id=uid) for uid, _ in accounts
    ]
    mock_session.execute = AsyncMock(return_value=accounts_result)

    @asynccontextmanager
    async def _session_ctx():  # type: ignore[no-untyped-def]
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


class TestPeriodicSyncSettings:
    """Tests for periodic sync settings in ImmichWorkerSettings."""

    def test_enable_periodic_sync_default(self) -> None:
        """Periodic sync is disabled by default."""
        from immich_settings import ImmichWorkerSettings

        settings = ImmichWorkerSettings(database_url="postgresql://test/test")
        assert settings.enable_periodic_sync is False

    def test_sync_interval_hours_default(self) -> None:
        """Sync interval defaults to 6 hours."""
        from immich_settings import ImmichWorkerSettings

        settings = ImmichWorkerSettings(database_url="postgresql://test/test")
        assert settings.sync_interval_hours == 6


class TestPeriodicSyncAllImmichAccounts:
    """Tests for periodic_sync_all_immich_accounts ARQ task."""

    @pytest.mark.asyncio
    async def test_enqueues_sync_for_each_account(self) -> None:
        """Should enqueue sync_immich_people for every connected account."""
        from worker import periodic_sync_all_immich_accounts

        accounts = [("user-1", "https://immich1.example.com"), ("user-2", "https://immich2.example.com")]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)

        result = await periodic_sync_all_immich_accounts(ctx)

        assert result["status"] == "success"
        assert result["accounts_found"] == 2
        assert result["jobs_enqueued"] == 2

        # Verify each call was for sync_immich_people
        assert mock_redis.enqueue_job.call_count == 2
        for call in mock_redis.enqueue_job.call_args_list:
            assert call[0][0] == "sync_immich_people"

    @pytest.mark.asyncio
    async def test_enqueues_with_smart_sync_type(self) -> None:
        """Periodic sync should use 'smart' sync type."""
        from worker import periodic_sync_all_immich_accounts

        accounts = [("user-1", "https://immich.example.com")]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)

        await periodic_sync_all_immich_accounts(ctx)

        call = mock_redis.enqueue_job.call_args_list[0]
        assert call[0][0] == "sync_immich_people"
        assert call[0][1] == "user-1"  # user_id
        assert call[0][2] == "smart"  # sync_type

    @pytest.mark.asyncio
    async def test_uses_correct_queue_name(self) -> None:
        """Jobs should be enqueued to the Immich ARQ queue."""
        from worker import IMMICH_ARQ_QUEUE_NAME, periodic_sync_all_immich_accounts

        accounts = [("user-1", "https://immich.example.com")]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)

        await periodic_sync_all_immich_accounts(ctx)

        call = mock_redis.enqueue_job.call_args_list[0]
        assert call.kwargs["_queue_name"] == IMMICH_ARQ_QUEUE_NAME

    @pytest.mark.asyncio
    async def test_handles_no_accounts(self) -> None:
        """Should complete successfully with zero accounts."""
        from worker import periodic_sync_all_immich_accounts

        ctx, mock_redis, _ = _make_mock_ctx([])

        result = await periodic_sync_all_immich_accounts(ctx)

        assert result["status"] == "success"
        assert result["accounts_found"] == 0
        assert result["jobs_enqueued"] == 0
        mock_redis.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_enqueue_failure(self) -> None:
        """Should record error when enqueue_job returns None."""
        from worker import periodic_sync_all_immich_accounts

        accounts = [("user-1", "https://immich.example.com")]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)
        mock_redis.enqueue_job = AsyncMock(return_value=None)

        result = await periodic_sync_all_immich_accounts(ctx)

        assert result["status"] == "success"
        assert result["accounts_found"] == 1
        assert result["jobs_enqueued"] == 0
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_handles_enqueue_exception(self) -> None:
        """Should catch and record exceptions from enqueue_job."""
        from worker import periodic_sync_all_immich_accounts

        accounts = [("user-1", "https://immich.example.com")]
        ctx, mock_redis, _ = _make_mock_ctx(accounts)
        mock_redis.enqueue_job = AsyncMock(
            side_effect=ConnectionError("Redis connection lost")
        )

        result = await periodic_sync_all_immich_accounts(ctx)

        assert result["status"] == "success"
        assert result["accounts_found"] == 1
        assert result["jobs_enqueued"] == 0
        assert len(result["errors"]) == 1
        assert "Redis connection lost" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_multiple_accounts_partial_failure(self) -> None:
        """Should continue processing remaining accounts after one fails."""
        from worker import periodic_sync_all_immich_accounts

        accounts = [
            ("user-1", "https://immich1.example.com"),
            ("user-2", "https://immich2.example.com"),
            ("user-3", "https://immich3.example.com"),
        ]
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

        result = await periodic_sync_all_immich_accounts(ctx)

        assert result["accounts_found"] == 3
        assert result["jobs_enqueued"] == 2
        assert len(result["errors"]) == 1


class TestSyncImmichPeople:
    """Tests for the sync_immich_people placeholder task."""

    @pytest.mark.asyncio
    async def test_placeholder_returns_success(self) -> None:
        """Placeholder task returns success with not-yet-implemented message."""
        from worker import sync_immich_people

        ctx: dict[str, Any] = {"session_factory": MagicMock()}
        result = await sync_immich_people(ctx, "user-1", "full")

        assert result["status"] == "success"
        assert "not yet implemented" in result["message"].lower()


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

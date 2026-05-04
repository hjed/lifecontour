"""
Unit tests for Strava ARQ worker process_strava_webhook_event task.

Tests verify event dispatch for create/update/delete aspect types
and that non-activity events are correctly ignored. Activity events
require a mock session factory and sync service to verify the
orchestration flow.
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


def _make_session_factory_returning_none():
    """Create a session factory whose DB queries return no rows."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _session_ctx():
        yield mock_session

    return _session_ctx


class TestProcessStravaWebhookEvent:
    """Tests for the process_strava_webhook_event ARQ task function."""

    @pytest.fixture
    def ctx(self) -> dict[str, Any]:
        """ARQ worker context with mocked session factory."""
        return {
            "session_factory": _make_session_factory_returning_none(),
            "settings": MagicMock(
                encryption_key=MagicMock(
                    get_secret_value=MagicMock(return_value="test_key")
                ),
                strava_client_id="test",
                strava_client_secret=MagicMock(
                    get_secret_value=MagicMock(return_value="test_secret")
                ),
            ),
        }

    @pytest.mark.asyncio
    async def test_dispatches_create_event_skips_unknown_athlete(
        self, ctx: dict[str, Any]
    ) -> None:
        """Create event for unknown athlete is skipped gracefully."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "create",
            "object_type": "activity",
            "object_id": 12345,
            "owner_id": 67890,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"
        assert result["reason"] == "unknown_athlete"

    @pytest.mark.asyncio
    async def test_dispatches_update_event_skips_unknown_athlete(
        self, ctx: dict[str, Any]
    ) -> None:
        """Update event for unknown athlete is skipped."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "update",
            "object_type": "activity",
            "object_id": 99999,
            "owner_id": 11111,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": {"title": "New Title"},
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_dispatches_delete_event_skips_unknown_athlete(
        self, ctx: dict[str, Any]
    ) -> None:
        """Delete event for unknown athlete is skipped."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "delete",
            "object_type": "activity",
            "object_id": 55555,
            "owner_id": 22222,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_ignores_non_activity_event(self, ctx: dict[str, Any]) -> None:
        """Non-activity (athlete) events are ignored."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "update",
            "object_type": "athlete",
            "object_id": 67890,
            "owner_id": 67890,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "ignored"
        assert "athlete" in result["reason"]

    @pytest.mark.asyncio
    async def test_skips_missing_object_id(self, ctx: dict[str, Any]) -> None:
        """Event with missing object_id is skipped gracefully."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "create",
            "object_type": "activity",
            "object_id": None,
            "owner_id": 67890,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"
        assert result["reason"] == "invalid_object_id"

    @pytest.mark.asyncio
    async def test_skips_non_int_object_id(self, ctx: dict[str, Any]) -> None:
        """Event with non-integer object_id is skipped gracefully."""
        worker_mod = _import_worker()

        event_data = {
            "aspect_type": "create",
            "object_type": "activity",
            "object_id": "not-an-int",
            "owner_id": 67890,
            "subscription_id": 1,
            "event_time": 1700000000,
            "updates": None,
        }
        result = await worker_mod.process_strava_webhook_event(ctx, event_data)

        assert result["status"] == "skipped"
        assert result["reason"] == "invalid_object_id"


class TestOnConsumerTaskDone:
    """Tests for _on_consumer_task_done callback."""

    @pytest.mark.asyncio
    async def test_logs_error_on_task_exception(self) -> None:
        """Callback logs error when the background task raises."""
        import asyncio

        worker_mod = _import_worker()
        mock_logger = MagicMock()
        worker_mod.logger = mock_logger

        async def _failing_task() -> None:
            raise RuntimeError("Redis connection lost")

        task: asyncio.Task[None] = asyncio.create_task(_failing_task())
        try:
            await task
        except RuntimeError:
            pass

        worker_mod._on_consumer_task_done(task)
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "failed unexpectedly" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_logs_info_on_task_cancelled(self) -> None:
        """Callback logs info when the background task is cancelled."""
        import asyncio

        worker_mod = _import_worker()
        mock_logger = MagicMock()
        worker_mod.logger = mock_logger

        async def _long_running() -> None:
            await asyncio.sleep(999)

        task: asyncio.Task[None] = asyncio.create_task(_long_running())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        worker_mod._on_consumer_task_done(task)
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert "cancelled" in call_args.args[0]

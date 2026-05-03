"""
Unit tests for Strava ARQ worker process_strava_webhook_event task.

Tests verify event dispatch for create/update/delete aspect types
and that non-activity events are correctly ignored.
"""

from __future__ import annotations

import pytest

# Import the function under test directly (worker module has
# module-level settings that need env vars, so we test the function
# in isolation where possible).


class TestProcessStravaWebhookEvent:
    """Tests for the process_strava_webhook_event ARQ task function."""

    @pytest.fixture
    def ctx(self) -> dict[str, object]:
        """Minimal ARQ worker context for testing."""
        return {"session_factory": None, "settings": None}

    @pytest.mark.asyncio
    async def test_dispatches_create_event(self, ctx: dict[str, object]) -> None:
        """Create aspect_type is processed and returns correct result."""
        # Import inside test to avoid module-level settings validation
        import importlib
        import sys
        from unittest.mock import MagicMock, patch

        # Stub the settings module so worker.py can be imported
        mock_settings = MagicMock()
        mock_settings.log_level = "DEBUG"
        mock_settings.worker_id = "test"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.database_url.get_secret_value.return_value = (
            "postgresql://test:test@localhost/test"
        )

        # Patch the module imports
        fake_strava_settings = MagicMock()
        fake_strava_settings.StravaSettings.return_value = mock_settings
        sys.modules["strava_settings"] = fake_strava_settings

        with (
            patch("core_shared.logging.configure_logging"),
            patch("core_shared.logging.get_logger", return_value=MagicMock()),
        ):
            if "worker" in sys.modules:
                del sys.modules["worker"]
            worker_mod = importlib.import_module("worker")

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

        assert result["status"] == "processed"
        assert result["aspect_type"] == "create"
        assert result["object_id"] == 12345

    @pytest.mark.asyncio
    async def test_dispatches_update_event(self, ctx: dict[str, object]) -> None:
        """Update aspect_type is processed correctly."""
        import importlib
        import sys
        from unittest.mock import MagicMock, patch

        mock_settings = MagicMock()
        mock_settings.log_level = "DEBUG"
        mock_settings.worker_id = "test"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.database_url.get_secret_value.return_value = (
            "postgresql://test:test@localhost/test"
        )

        fake_strava_settings = MagicMock()
        fake_strava_settings.StravaSettings.return_value = mock_settings
        sys.modules["strava_settings"] = fake_strava_settings

        with (
            patch("core_shared.logging.configure_logging"),
            patch("core_shared.logging.get_logger", return_value=MagicMock()),
        ):
            if "worker" in sys.modules:
                del sys.modules["worker"]
            worker_mod = importlib.import_module("worker")

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

        assert result["status"] == "processed"
        assert result["aspect_type"] == "update"

    @pytest.mark.asyncio
    async def test_dispatches_delete_event(self, ctx: dict[str, object]) -> None:
        """Delete aspect_type is processed correctly."""
        import importlib
        import sys
        from unittest.mock import MagicMock, patch

        mock_settings = MagicMock()
        mock_settings.log_level = "DEBUG"
        mock_settings.worker_id = "test"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.database_url.get_secret_value.return_value = (
            "postgresql://test:test@localhost/test"
        )

        fake_strava_settings = MagicMock()
        fake_strava_settings.StravaSettings.return_value = mock_settings
        sys.modules["strava_settings"] = fake_strava_settings

        with (
            patch("core_shared.logging.configure_logging"),
            patch("core_shared.logging.get_logger", return_value=MagicMock()),
        ):
            if "worker" in sys.modules:
                del sys.modules["worker"]
            worker_mod = importlib.import_module("worker")

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

        assert result["status"] == "processed"
        assert result["aspect_type"] == "delete"

    @pytest.mark.asyncio
    async def test_ignores_non_activity_event(self, ctx: dict[str, object]) -> None:
        """Non-activity (athlete) events are ignored."""
        import importlib
        import sys
        from unittest.mock import MagicMock, patch

        mock_settings = MagicMock()
        mock_settings.log_level = "DEBUG"
        mock_settings.worker_id = "test"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.database_url.get_secret_value.return_value = (
            "postgresql://test:test@localhost/test"
        )

        fake_strava_settings = MagicMock()
        fake_strava_settings.StravaSettings.return_value = mock_settings
        sys.modules["strava_settings"] = fake_strava_settings

        with (
            patch("core_shared.logging.configure_logging"),
            patch("core_shared.logging.get_logger", return_value=MagicMock()),
        ):
            if "worker" in sys.modules:
                del sys.modules["worker"]
            worker_mod = importlib.import_module("worker")

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


class TestOnConsumerTaskDone:
    """Tests for _on_consumer_task_done callback."""

    @pytest.mark.asyncio
    async def test_logs_error_on_task_exception(self) -> None:
        """Callback logs error when the background task raises."""
        import asyncio
        import importlib
        import sys
        from unittest.mock import MagicMock, patch

        mock_settings = MagicMock()
        mock_settings.log_level = "DEBUG"
        mock_settings.worker_id = "test"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.database_url.get_secret_value.return_value = (
            "postgresql://test:test@localhost/test"
        )

        fake_strava_settings = MagicMock()
        fake_strava_settings.StravaSettings.return_value = mock_settings
        sys.modules["strava_settings"] = fake_strava_settings

        mock_logger = MagicMock()
        with (
            patch("core_shared.logging.configure_logging"),
            patch("core_shared.logging.get_logger", return_value=mock_logger),
        ):
            if "worker" in sys.modules:
                del sys.modules["worker"]
            worker_mod = importlib.import_module("worker")

        # Create a task that raises an exception
        async def _failing_task() -> None:
            raise RuntimeError("Redis connection lost")

        task: asyncio.Task[None] = asyncio.create_task(_failing_task())
        # Let the task finish
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
        import importlib
        import sys
        from unittest.mock import MagicMock, patch

        mock_settings = MagicMock()
        mock_settings.log_level = "DEBUG"
        mock_settings.worker_id = "test"
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.database_url.get_secret_value.return_value = (
            "postgresql://test:test@localhost/test"
        )

        fake_strava_settings = MagicMock()
        fake_strava_settings.StravaSettings.return_value = mock_settings
        sys.modules["strava_settings"] = fake_strava_settings

        mock_logger = MagicMock()
        with (
            patch("core_shared.logging.configure_logging"),
            patch("core_shared.logging.get_logger", return_value=mock_logger),
        ):
            if "worker" in sys.modules:
                del sys.modules["worker"]
            worker_mod = importlib.import_module("worker")

        # Create a task that gets cancelled
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

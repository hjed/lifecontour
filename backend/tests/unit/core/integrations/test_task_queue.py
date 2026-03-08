"""
Unit tests for task queue configuration.

Tests the ARQ task queue configuration and utilities
for integration workers.
"""

from typing import Any

import pytest

from app.core.integrations.task_queue import (
    TaskQueueConfig,
    WorkerSettings,
    get_redis_settings,
    get_worker_settings,
)
from app.infrastructure.config import Settings


class TestTaskQueueConfig:
    """Test cases for TaskQueueConfig."""

    def test_config_values(self) -> None:
        """Test that config has expected values."""
        assert TaskQueueConfig.QUEUE_NAME == "integration_tasks"
        assert TaskQueueConfig.MAX_JOBS == 10
        assert TaskQueueConfig.JOB_TIMEOUT == 300
        assert TaskQueueConfig.KEEP_RESULT == 3600
        assert TaskQueueConfig.MAX_TRIES == 3
        assert TaskQueueConfig.RETRY_DELAY == 60
        assert TaskQueueConfig.DLQ_MAX_SIZE == 1000
        assert TaskQueueConfig.DLQ_RETENTION == 86400 * 7


class TestRedisSettings:
    """Test cases for Redis settings."""

    def test_get_redis_settings_default(self) -> None:
        """Test getting Redis settings with default values."""
        # Create settings with default Redis URL
        settings = Settings(redis_url="redis://localhost:6379")
        redis_settings = get_redis_settings(settings)

        assert redis_settings.host == "localhost"
        assert redis_settings.port == 6379
        assert redis_settings.database == 0

    def test_get_redis_settings_custom_host_port(self) -> None:
        """Test getting Redis settings with custom host and port."""
        settings = Settings(redis_url="redis://redis-server:6380")
        redis_settings = get_redis_settings(settings)

        assert redis_settings.host == "redis-server"
        assert redis_settings.port == 6380
        assert redis_settings.database == 0

    def test_get_redis_settings_with_database_path(self) -> None:
        """Test getting Redis settings with an explicit Redis database."""
        settings = Settings(redis_url="redis://redis-server:6380/15")
        redis_settings = get_redis_settings(settings)

        assert redis_settings.host == "redis-server"
        assert redis_settings.port == 6380
        assert redis_settings.database == 15

    def test_get_redis_settings_invalid_url(self) -> None:
        """Test getting Redis settings with invalid URL format."""
        settings = Settings(redis_url="invalid://url")
        redis_settings = get_redis_settings(settings)

        # Should fall back to defaults
        assert redis_settings.host == "localhost"
        assert redis_settings.port == 6379

    def test_get_redis_settings_no_settings(self) -> None:
        """Test getting Redis settings without providing settings."""
        # Should not raise an error and use environment defaults
        redis_settings = get_redis_settings(None)

        assert redis_settings.host is not None
        assert redis_settings.port is not None
        assert redis_settings.database == 0


class TestWorkerSettings:
    """Test cases for WorkerSettings."""

    def test_worker_settings_creation(self) -> None:
        """Test creating worker settings."""
        settings = Settings(redis_url="redis://localhost:6379")
        worker_settings = WorkerSettings.create_with_settings(settings)

        assert worker_settings.redis_settings is not None
        assert worker_settings.redis_settings.host == "localhost"
        assert worker_settings.redis_settings.port == 6379
        assert worker_settings.max_jobs == TaskQueueConfig.MAX_JOBS
        assert worker_settings.job_timeout == TaskQueueConfig.JOB_TIMEOUT
        assert worker_settings.keep_result == TaskQueueConfig.KEEP_RESULT
        assert worker_settings.max_tries == TaskQueueConfig.MAX_TRIES
        assert worker_settings.retry_delay == TaskQueueConfig.RETRY_DELAY

    def test_worker_settings_functions(self) -> None:
        """Test that worker settings includes task functions."""
        worker_settings = WorkerSettings()

        assert len(worker_settings.functions) > 0
        # Should include the example task
        function_names = [func.__name__ for func in worker_settings.functions]
        assert "example_integration_task" in function_names

    def test_worker_settings_lifecycle_functions(self) -> None:
        """Test that worker settings includes lifecycle functions."""
        assert WorkerSettings.on_startup is not None
        assert WorkerSettings.on_shutdown is not None
        assert callable(WorkerSettings.on_startup)
        assert callable(WorkerSettings.on_shutdown)

    def test_get_worker_settings_convenience_function(self) -> None:
        """Test the convenience function for getting worker settings."""
        settings = Settings(redis_url="redis://test:1234")
        worker_settings = get_worker_settings(settings)

        assert isinstance(worker_settings, WorkerSettings)
        assert worker_settings.redis_settings is not None
        assert worker_settings.redis_settings.host == "test"
        assert worker_settings.redis_settings.port == 1234


@pytest.mark.asyncio
class TestTaskFunctions:
    """Test cases for task functions."""

    async def test_example_integration_task(self) -> None:
        """Test the example integration task."""
        import logging

        from app.core.integrations.task_queue import example_integration_task

        # Mock ARQ context with proper logger
        ctx = {"logger": logging.getLogger("test")}

        result = await example_integration_task(ctx, "test_integration", "ext_123")

        assert result["status"] == "success"
        assert result["integration_source"] == "test_integration"
        assert result["external_id"] == "ext_123"
        assert "processed_at" in result

    async def test_startup_function(self) -> None:
        """Test the worker startup function."""
        from app.core.integrations.task_queue import startup

        ctx: dict[str, Any] = {}
        await startup(ctx)

        # Should add logger to context
        assert "logger" in ctx
        assert ctx["logger"] is not None

    async def test_shutdown_function(self) -> None:
        """Test the worker shutdown function."""
        # Mock context with logger
        import logging

        from app.core.integrations.task_queue import shutdown

        ctx: dict[str, Any] = {"logger": logging.getLogger("test")}

        # Should not raise an error
        await shutdown(ctx)

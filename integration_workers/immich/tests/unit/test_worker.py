# ruff: noqa: E402
"""Unit tests for the Immich worker ARQ configuration."""

import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}"
        "/personal_management_test"
    )
os.environ.setdefault("ENCRYPTION_KEY", "testkey")

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq.connections import RedisSettings

from worker import WorkerSettings, _parse_redis_url, shutdown, startup


class TestWorkerSettings:
    """Tests for the WorkerSettings ARQ configuration."""

    def test_queue_name(self) -> None:
        """Worker uses the correct ARQ queue name."""
        assert WorkerSettings.queue_name == "arq:immich"

    def test_functions_list_is_empty(self) -> None:
        """Functions list is empty in Phase 2 (no sync tasks yet)."""
        assert WorkerSettings.functions == []

    def test_lifecycle_hooks_set(self) -> None:
        """Startup and shutdown hooks are configured."""
        assert WorkerSettings.on_startup is startup
        assert WorkerSettings.on_shutdown is shutdown

    def test_retry_configuration(self) -> None:
        """Retry and timeout values are configured."""
        assert WorkerSettings.max_tries == 5
        assert WorkerSettings.job_timeout == 300
        assert WorkerSettings.keep_result == 3600
        assert WorkerSettings.health_check_interval == 30


class TestParseRedisUrl:
    """Tests for the _parse_redis_url helper."""

    def test_basic_url(self) -> None:
        """Parse a basic redis URL."""
        settings: RedisSettings = _parse_redis_url("redis://localhost:6379/1")
        assert settings.host == "localhost"
        assert settings.port == 6379
        assert settings.database == 1
        assert settings.password is None

    def test_url_with_password(self) -> None:
        """Parse a redis URL with a password."""
        settings: RedisSettings = _parse_redis_url(
            "redis://:mypassword@redis-host:6380/2"
        )
        assert settings.host == "redis-host"
        assert settings.port == 6380
        assert settings.database == 2
        assert settings.password == "mypassword"

    def test_url_with_defaults(self) -> None:
        """Parse a redis URL using default port and database."""
        settings: RedisSettings = _parse_redis_url("redis://redis-server")
        assert settings.host == "redis-server"
        assert settings.port == 6379
        assert settings.database == 0


@pytest.mark.asyncio
class TestStartupHook:
    """Tests for the startup lifecycle hook."""

    @patch("core_shared.database.create_session_factory")
    @patch("stream_consumer_tasks.run_immich_stream_consumer", new_callable=AsyncMock)
    async def test_startup_creates_session_factory(
        self,
        mock_run_consumer: AsyncMock,
        mock_create_factory: MagicMock,
    ) -> None:
        """Startup creates a session factory and stores it in context."""
        mock_create_factory.return_value = MagicMock()
        ctx: dict = {}  # type: ignore[type-arg]

        await startup(ctx)

        mock_create_factory.assert_called_once()
        assert "session_factory" in ctx

        # Clean up the background task
        task = ctx.get("stream_consumer_task")
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    @patch("core_shared.database.create_session_factory")
    @patch("stream_consumer_tasks.run_immich_stream_consumer", new_callable=AsyncMock)
    async def test_startup_launches_stream_consumer(
        self,
        mock_run_consumer: AsyncMock,
        mock_create_factory: MagicMock,
    ) -> None:
        """Startup creates a background task for the stream consumer."""
        mock_create_factory.return_value = MagicMock()
        ctx: dict = {}  # type: ignore[type-arg]

        await startup(ctx)

        assert "stream_consumer_task" in ctx
        assert isinstance(ctx["stream_consumer_task"], asyncio.Task)

        # Clean up
        task = ctx["stream_consumer_task"]
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


@pytest.mark.asyncio
class TestShutdownHook:
    """Tests for the shutdown lifecycle hook."""

    async def test_shutdown_cancels_consumer_task(self) -> None:
        """Shutdown cancels the stream consumer task."""

        async def _long_running() -> None:
            await asyncio.sleep(3600)

        task = asyncio.create_task(_long_running())
        ctx: dict = {"stream_consumer_task": task}  # type: ignore[type-arg]

        await shutdown(ctx)

        assert task.cancelled()

    async def test_shutdown_with_no_task(self) -> None:
        """Shutdown handles missing consumer task gracefully."""
        ctx: dict = {}  # type: ignore[type-arg]
        await shutdown(ctx)

    async def test_shutdown_with_already_done_task(self) -> None:
        """Shutdown handles an already-completed task gracefully."""

        async def _instant() -> None:
            return

        task = asyncio.create_task(_instant())
        await task
        ctx: dict = {"stream_consumer_task": task}  # type: ignore[type-arg]

        await shutdown(ctx)

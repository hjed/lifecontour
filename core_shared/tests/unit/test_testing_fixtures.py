"""Unit tests for the shared worker test fixtures in ``core_shared.testing``.

These assert that each fixture/helper produces the expected object so the
fixtures can be relied on by every worker's test suite (ITER14-005 Phase 1).
The fixtures themselves are exercised by requesting them as test arguments,
which only works because ``core_shared.tests.conftest`` registers
``core_shared.testing`` as a pytest plugin.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from core_shared.testing import (
    make_arq_ctx,
    make_worker_settings,
)
from core_shared.worker_settings import BaseWorkerSettings


class TestMockRedis:
    """The ``mock_redis`` fixture provides an async Redis double."""

    @pytest.mark.asyncio
    async def test_is_async_mock_with_stream_ops(self, mock_redis: AsyncMock) -> None:
        assert isinstance(mock_redis, AsyncMock)
        # Stream operations the StreamClient/consumer rely on are awaitable.
        for op in (
            "xadd",
            "xreadgroup",
            "xack",
            "xgroup_create",
            "ping",
            "xpending_range",
            "xclaim",
            "xinfo_groups",
        ):
            assert inspect.iscoroutinefunction(getattr(mock_redis, op))

    @pytest.mark.asyncio
    async def test_default_return_values_are_sane(self, mock_redis: AsyncMock) -> None:
        assert await mock_redis.ping() is True
        assert await mock_redis.xadd("s", {"a": "b"}) == b"0-1"
        assert await mock_redis.xreadgroup() == []

    @pytest.mark.asyncio
    async def test_pending_retry_reads_default_to_empty_lists(
        self, mock_redis: AsyncMock
    ) -> None:
        # The StreamClient iterates these results, so they must be iterable
        # (empty) by default rather than bare mocks. This is what lets a worker
        # drive StreamConsumer.start()'s retry-pending path without extra setup.
        assert await mock_redis.xpending_range() == []
        assert await mock_redis.xclaim() == []
        assert await mock_redis.xinfo_groups() == []


class TestMakeWorkerSettings:
    """``make_worker_settings`` builds a real, deterministic ``BaseWorkerSettings``."""

    def test_returns_base_worker_settings_with_secret_db_url(self) -> None:
        settings = make_worker_settings()

        assert isinstance(settings, BaseWorkerSettings)
        assert isinstance(settings.database_url, SecretStr)
        # Default db URL is a usable asyncpg DSN, not the literal "**********".
        assert settings.database_url.get_secret_value().startswith("postgresql")
        assert settings.redis_url.startswith("redis://")
        assert settings.stream_name
        assert settings.worker_id

    def test_overrides_are_applied(self) -> None:
        settings = make_worker_settings(
            worker_id="immich-worker",
            stream_name="pms:custom",
            enable_periodic_sync=True,
        )

        assert settings.worker_id == "immich-worker"
        assert settings.stream_name == "pms:custom"
        assert settings.enable_periodic_sync is True

    def test_accepts_a_subclass(self) -> None:
        class GoogleLikeSettings(BaseWorkerSettings):
            google_client_id: str = "test-client"

        settings = make_worker_settings(
            settings_cls=GoogleLikeSettings, google_client_id="abc"
        )

        assert isinstance(settings, GoogleLikeSettings)
        assert settings.google_client_id == "abc"

    def test_does_not_read_local_env_file(self) -> None:
        # _env_file=None is forced so an ambient .env cannot leak into the model.
        settings = make_worker_settings(worker_id="isolated")
        assert settings.worker_id == "isolated"

    def test_worker_settings_fixture(self, worker_settings: BaseWorkerSettings) -> None:
        assert isinstance(worker_settings, BaseWorkerSettings)


class TestSessionFactoryMock:
    """``session_factory_mock`` mimics the async session factory workers use."""

    @pytest.mark.asyncio
    async def test_has_awaitable_close(self, session_factory_mock: Any) -> None:
        assert isinstance(session_factory_mock.close, AsyncMock)
        await session_factory_mock.close()
        session_factory_mock.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_yields_a_session_via_async_context_manager(
        self, session_factory_mock: Any
    ) -> None:
        async with session_factory_mock() as session:
            assert session is not None


class TestMakeArqCtx:
    """``make_arq_ctx`` builds the ARQ ctx dict with the lifecycle keys."""

    def test_has_lifecycle_keys(self) -> None:
        ctx = make_arq_ctx()

        assert "session_factory" in ctx
        assert "settings" in ctx
        assert isinstance(ctx["settings"], BaseWorkerSettings)

    def test_overrides_are_applied(self) -> None:
        sentinel = object()
        ctx = make_arq_ctx(session_factory=sentinel, extra="value")

        assert ctx["session_factory"] is sentinel
        assert ctx["extra"] == "value"

    def test_arq_ctx_fixture_has_keys(self, arq_ctx: dict[str, Any]) -> None:
        assert {"session_factory", "settings"} <= set(arq_ctx)

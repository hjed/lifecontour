"""Smoke test: the shared unit fixtures (``core_shared.testing``) are wired in.

Confirms this worker's top-level ``conftest.py`` registers the shared pytest
plugin, so the common scaffolding fixtures resolve as test arguments.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from core_shared.worker_settings import BaseWorkerSettings


def test_mock_redis_is_injectable(mock_redis: AsyncMock) -> None:
    assert isinstance(mock_redis, AsyncMock)


def test_worker_settings_is_base_worker_settings(
    worker_settings: BaseWorkerSettings,
) -> None:
    assert isinstance(worker_settings, BaseWorkerSettings)


def test_session_factory_mock_is_injectable(session_factory_mock: Any) -> None:
    assert isinstance(session_factory_mock.close, AsyncMock)


def test_arq_ctx_has_lifecycle_keys(arq_ctx: dict[str, Any]) -> None:
    assert {"session_factory", "settings"} <= set(arq_ctx)

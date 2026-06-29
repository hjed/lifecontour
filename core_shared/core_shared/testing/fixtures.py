"""Shared worker unit-test fixtures and factory helpers.

Every integration worker hand-rolled the same unit-test scaffolding — an
AsyncMock Redis, a mocked async session factory, an ARQ ``ctx`` dict primed with
the lifecycle keys, and a throwaway :class:`~core_shared.worker_settings.BaseWorkerSettings`.
This module defines each of those once, as plain factory helpers plus thin
pytest fixtures that wrap them.

Consumption is via the pytest plugin entry point — a worker test suite adds::

    pytest_plugins = ["core_shared.testing"]

to its top-level ``conftest.py`` and then requests ``mock_redis``,
``worker_settings``, ``session_factory_mock``, or ``arq_ctx`` directly as test
arguments. The plain ``make_*`` helpers are importable too, for tests that need
to build several instances or override deeply.

The fixtures are deliberately synchronous-construction (they return ready-made
mocks/objects), so they work under pytest-asyncio's STRICT mode without needing
``@pytest_asyncio.fixture``; the async behaviour lives in the mocks' methods.
"""

from __future__ import annotations

from typing import Any, overload
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from core_shared.worker_settings import BaseWorkerSettings

# A deterministic, valid asyncpg DSN used as the default test database URL. It is
# never connected to — the session factory is mocked — but it must parse and
# survive ``SecretStr`` round-tripping.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/personal_management_test"
)


# ---------------------------------------------------------------------------
# Redis double
# ---------------------------------------------------------------------------


def make_mock_redis() -> AsyncMock:
    """Build an ``AsyncMock`` standing in for an async ``redis.asyncio.Redis``.

    Every stream operation the ``StreamClient``/``StreamConsumer`` rely on is
    pre-seeded with a sane default return value so a worker test can drive a
    full consumer loop — including ``StreamConsumer.start()``'s pending-entry
    retry path — without configuring the mock first:

    * ``xadd`` → a message id, ``ping`` → ``True``, ``xgroup_create`` → ``True``,
      ``xack`` → ``1``, ``xlen`` → ``0``.
    * The list-returning reads ``xreadgroup``, ``xpending_range``, ``xclaim``,
      and ``xinfo_groups`` default to ``[]`` so the client's parsing loops (which
      iterate the result and call ``int(...)`` on fields) get an empty, valid
      result rather than a bare ``MagicMock`` that would raise on iteration.

    Any method not listed is still an awaitable ``AsyncMock`` returning a fresh
    mock; override return values per test as needed.
    """
    redis = AsyncMock(name="mock_redis")
    redis.ping.return_value = True
    redis.xadd.return_value = b"0-1"
    redis.xgroup_create.return_value = True
    redis.xack.return_value = 1
    redis.xlen.return_value = 0
    # List-returning reads the StreamClient iterates/parses — default to empty so
    # a consumer loop (and its retry-pending path) runs without extra setup.
    redis.xreadgroup.return_value = []
    redis.xpending_range.return_value = []
    redis.xclaim.return_value = []
    redis.xinfo_groups.return_value = []
    return redis


# ---------------------------------------------------------------------------
# Worker settings
# ---------------------------------------------------------------------------


@overload
def make_worker_settings(**overrides: Any) -> BaseWorkerSettings: ...


@overload
def make_worker_settings[SettingsT: BaseWorkerSettings](
    settings_cls: type[SettingsT], **overrides: Any
) -> SettingsT: ...


def make_worker_settings[SettingsT: BaseWorkerSettings](
    settings_cls: type[SettingsT] = BaseWorkerSettings,  # type: ignore[assignment]
    **overrides: Any,
) -> SettingsT:
    """Build a real, deterministic ``BaseWorkerSettings`` (or subclass).

    ``database_url`` defaults to :data:`DEFAULT_TEST_DATABASE_URL` wrapped in a
    ``SecretStr``; every other field uses its model default unless overridden.
    ``_env_file=None`` is forced so an ambient ``.env`` cannot leak ambient
    values into the model, keeping the object deterministic (mirrors the
    ``_make_settings`` helper in ``core_shared``'s own worker-arq tests).

    Args:
        settings_cls: The settings class to instantiate. Pass a worker's own
            ``BaseWorkerSettings`` subclass to exercise integration-specific
            fields; supply their required values via ``overrides``.
        **overrides: Field values to set, e.g. ``worker_id="immich-worker"``.
    """
    kwargs: dict[str, Any] = {
        "database_url": SecretStr(DEFAULT_TEST_DATABASE_URL),
        "_env_file": None,
    }
    kwargs.update(overrides)
    return settings_cls(**kwargs)


# ---------------------------------------------------------------------------
# Async session factory double
# ---------------------------------------------------------------------------


def make_session_factory_mock() -> MagicMock:
    """Build a mock async session factory matching the worker lifecycle contract.

    Calling the returned factory yields an async context manager
    (``async with factory() as session``) producing an ``AsyncMock`` session,
    mirroring ``async_sessionmaker`` usage. The factory also exposes an
    awaitable ``close`` (``AsyncMock``), which is what
    :func:`core_shared.worker_arq.build_worker_lifecycle` calls on shutdown when
    ``close_session_factory`` is set. The yielded session is exposed as
    ``factory.session`` for post-hoc assertions.
    """
    session = AsyncMock(name="async_session")

    context_manager = MagicMock(name="session_context_manager")
    context_manager.__aenter__ = AsyncMock(return_value=session)
    context_manager.__aexit__ = AsyncMock(return_value=None)

    factory = MagicMock(name="session_factory", return_value=context_manager)
    factory.close = AsyncMock()
    factory.session = session
    return factory


# ---------------------------------------------------------------------------
# ARQ context harness
# ---------------------------------------------------------------------------


def make_arq_ctx(**overrides: Any) -> dict[str, Any]:
    """Build an ARQ ``ctx`` dict primed with the worker lifecycle keys.

    Defaults ``session_factory`` to :func:`make_session_factory_mock` and
    ``settings`` to :func:`make_worker_settings`, matching the keys
    :func:`core_shared.worker_arq.build_worker_lifecycle` stores in ``ctx`` (the
    ``stream_consumer_task`` key is added by ``on_startup`` and so is omitted
    here unless supplied). Any keyword overrides are merged in, so a test can
    inject its own session factory, settings, or extra ctx entries.
    """
    ctx: dict[str, Any] = {
        "session_factory": make_session_factory_mock(),
        "settings": make_worker_settings(),
    }
    ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# pytest fixtures (thin wrappers over the helpers above)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    """An ``AsyncMock`` Redis double with stream ops pre-seeded.

    See :func:`make_mock_redis`.
    """
    return make_mock_redis()


@pytest.fixture
def worker_settings() -> BaseWorkerSettings:
    """A deterministic ``BaseWorkerSettings``. See :func:`make_worker_settings`."""
    return make_worker_settings()


@pytest.fixture
def session_factory_mock() -> MagicMock:
    """A mock async session factory. See :func:`make_session_factory_mock`."""
    return make_session_factory_mock()


@pytest.fixture
def arq_ctx() -> dict[str, Any]:
    """An ARQ ``ctx`` dict primed with the lifecycle keys. See :func:`make_arq_ctx`."""
    return make_arq_ctx()

"""A sample worker-style test that runs purely on the shared fixtures.

This is the spec-mandated demonstration (ITER14-005 Phase 1) that a worker can
test its ARQ lifecycle wiring using only ``core_shared.testing`` fixtures —
without hand-rolling a Redis mock, a session-factory mock, an ARQ ctx, or a fake
settings object. It mirrors how the workers exercise
``build_worker_lifecycle`` today, but sources every double from the shared
plugin.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from core_shared.worker_arq import build_worker_lifecycle
from core_shared.worker_settings import BaseWorkerSettings


@pytest.mark.asyncio
async def test_worker_lifecycle_runs_on_shared_fixtures(
    worker_settings: BaseWorkerSettings,
    session_factory_mock: Any,
    mock_redis: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive on_startup/on_shutdown using only shared fixtures."""
    import core_shared.worker_arq as worker_arq

    # The lifecycle builds its own factory; point it at the shared mock so no
    # real database engine is created.
    monkeypatch.setattr(
        worker_arq,
        "create_session_factory",
        lambda _url: session_factory_mock,
    )

    started = asyncio.Event()

    async def consumer_factory(sf: Any, s: BaseWorkerSettings) -> None:
        # A real worker would open a Redis stream here; we just prove the
        # shared mock is usable from the consumer coroutine.
        await mock_redis.ping()
        started.set()
        await asyncio.Event().wait()  # block until cancelled on shutdown

    on_startup, on_shutdown = build_worker_lifecycle(
        settings=worker_settings,
        consumer_factory=consumer_factory,
        close_session_factory=True,
    )

    ctx: dict[str, Any] = {}
    await on_startup(ctx)
    # Generous timeout: the event is set almost immediately, so the await returns
    # at once on a healthy run; the ceiling only guards against a hang and stays
    # forgiving on slow CI runners.
    await asyncio.wait_for(started.wait(), timeout=10)

    assert ctx["session_factory"] is session_factory_mock
    assert ctx["settings"] is worker_settings
    assert isinstance(ctx["stream_consumer_task"], asyncio.Task)
    mock_redis.ping.assert_awaited()

    await on_shutdown(ctx)

    assert ctx["stream_consumer_task"].cancelled()
    session_factory_mock.close.assert_awaited_once()

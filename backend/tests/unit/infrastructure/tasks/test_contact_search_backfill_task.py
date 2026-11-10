"""The contact search backfill loop survives whatever a cycle does."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from meilisearch.errors import MeilisearchError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.infrastructure.search.search_backfill_service import SearchBackfillResult
from app.infrastructure.tasks import contact_search_backfill_task as task_module
from app.infrastructure.tasks.contact_search_backfill_task import (
    run_contact_search_backfill_loop,
)

RESULT = SearchBackfillResult(examined=3, documents_written=1, failed_ids=[])


def _container() -> AsyncMock:
    engine = MagicMock(spec=AsyncEngine)
    engine.connect.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
    container = AsyncMock()
    container.get.return_value = engine
    return container


def _stop_after(sleeps: int) -> AsyncMock:
    """A sleep that lets the loop run ``sleeps`` cycles and then cancels it."""
    outcomes: list[object] = [None] * (sleeps - 1) + [asyncio.CancelledError()]
    return AsyncMock(side_effect=outcomes)


async def _run(
    backfill: AsyncMock, sleep: AsyncMock, *, interval_seconds: float = 3600
) -> None:
    with (
        patch.object(task_module, "SearchBackfillService") as service,
        patch.object(task_module.asyncio, "sleep", sleep),
    ):
        service.return_value.backfill_contacts = backfill
        with pytest.raises(asyncio.CancelledError):
            await run_contact_search_backfill_loop(
                _container(), interval_seconds=interval_seconds
            )


@pytest.mark.asyncio
async def test_a_cycle_runs_at_once_and_then_at_the_interval() -> None:
    backfill = AsyncMock(return_value=RESULT)
    sleep = _stop_after(2)

    await _run(backfill, sleep, interval_seconds=120)

    assert backfill.await_count == 2
    sleep.assert_awaited_with(120)


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(lambda: MeilisearchError("down"), id="meilisearch-outage"),
        pytest.param(lambda: TimeoutError(), id="hung-cycle"),
    ],
)
@pytest.mark.asyncio
async def test_a_failed_cycle_is_followed_by_another(
    failure: Callable[[], Exception],
) -> None:
    backfill = AsyncMock(side_effect=[failure(), RESULT])

    await _run(backfill, _stop_after(2))

    assert backfill.await_count == 2


@pytest.mark.asyncio
async def test_a_hung_cycle_is_abandoned() -> None:
    async def hang() -> SearchBackfillResult:
        await asyncio.Event().wait()
        return RESULT

    with patch.object(task_module, "CYCLE_TIMEOUT_SECONDS", 0.01):
        await _run(AsyncMock(side_effect=hang), _stop_after(1))


@pytest.mark.asyncio
async def test_cancelling_during_a_cycle_stops_the_loop() -> None:
    backfill = AsyncMock(side_effect=asyncio.CancelledError())
    sleep = AsyncMock()

    await _run(backfill, sleep)

    sleep.assert_not_awaited()

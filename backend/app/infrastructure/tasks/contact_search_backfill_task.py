"""Background task that keeps contacts findable in search.

Runs in the main backend process as a lifespan task. It starts straight away,
so a deploy repairs the index on its own, and repeats because MeiliSearch can
lose its data without the backend restarting.
"""

import asyncio

import structlog
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncEngine

from app.infrastructure.search.search_backfill_service import SearchBackfillService

logger = structlog.get_logger()

# Each request is bounded by the client's HTTP timeout; this bounds a whole cycle
# against a server that keeps answering, but too slowly to finish.
CYCLE_TIMEOUT_SECONDS = 15 * 60


async def _run_cycle(container: AsyncContainer) -> None:
    """Run one backfill on its own connection."""
    engine = await container.get(AsyncEngine)
    async with engine.connect() as connection:
        result = await SearchBackfillService(connection).backfill_contacts()
    logger.info(
        "Contact search backfill complete",
        examined=result.examined,
        documents_written=result.documents_written,
        failed_ids=result.failed_ids,
    )


async def run_contact_search_backfill_loop(
    container: AsyncContainer,
    interval_seconds: float = 3600,
) -> None:
    """Backfill contact search documents now and then at every interval.

    A failed cycle is logged and the next one repairs what it can: search is a
    derived read surface and must never take the application down with it.

    Args:
        container: Application's AsyncContainer for dependency injection.
        interval_seconds: Interval between cycles (default: 1 hour).
    """
    logger.info(
        "Starting contact search backfill loop", interval_seconds=interval_seconds
    )

    try:
        while True:
            try:
                await asyncio.wait_for(_run_cycle(container), CYCLE_TIMEOUT_SECONDS)
            except Exception as error:  # noqa: BLE001 - see the docstring
                logger.warning(
                    "Contact search backfill failed; retrying next cycle",
                    error=repr(error),
                )
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Contact search backfill loop cancelled")
        raise

"""
Summary refresh sweeper for buffered (debounced) AI summary generation.

Automated contact activity (edits, journal links, Google syncs) is recorded as
a rolling-debounce marker on the contact_summaries row instead of triggering a
Gemini call per event. This sweeper periodically claims contacts whose marker
has been quiet for the buffer window and publishes a ContactSummaryRefreshDue
event to the outbox, driving exactly one generation per burst of activity.

Runs as a background task alongside the outbox relay, following the same
lifecycle pattern (see run_outbox_relay_loop).
"""

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_summary_repository import (
    SqlContactSummaryRepository,
)
from app.core.contacts.models.events import ContactSummaryRefreshDue
from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

logger = structlog.get_logger()


class SummaryRefreshSweeper:
    """Dispatches buffered summary refreshes once their quiet period elapses.

    Claims contact_summaries rows whose refresh_requested_at marker is older
    than the buffer window (clearing the marker) and publishes a
    ContactSummaryRefreshDue event to the outbox on the same connection, so
    the claim and the dispatch commit atomically: a crash between the two
    rolls back the claim and the request is retried on the next sweep.
    """

    def __init__(
        self,
        buffer_seconds: int = 300,
        batch_size: int = 50,
    ) -> None:
        """Initialize the sweeper.

        Args:
            buffer_seconds: Quiet period a contact must observe before its
                buffered refresh is dispatched (rolling debounce window)
            batch_size: Maximum refreshes to dispatch per sweep
        """
        self._buffer_seconds = buffer_seconds
        self._batch_size = batch_size

    async def sweep_batch(self, connection: AsyncConnection) -> int:
        """Dispatch due buffered refreshes on the given connection.

        Disabled summaries are claimed too (their stale markers are cleared)
        but no generation is dispatched for them. A publish failure propagates
        so the caller's transaction rolls back the claimed markers.

        Args:
            connection: Async database connection

        Returns:
            Number of ContactSummaryRefreshDue events published
        """
        repository = SqlContactSummaryRepository(connection)
        publisher = OutboxEventPublisher(connection)

        cutoff = datetime.now(UTC) - timedelta(seconds=self._buffer_seconds)
        claimed = await repository.claim_due_refreshes(cutoff, self._batch_size)

        if not claimed:
            return 0

        dispatched = 0
        for contact_id, is_disabled in claimed:
            if is_disabled:
                logger.debug(
                    "Cleared stale refresh marker for disabled summary",
                    contact_id=contact_id,
                )
                continue
            await publisher.publish(ContactSummaryRefreshDue(contact_id=contact_id))
            dispatched += 1

        if dispatched > 0:
            logger.info(
                "Dispatched buffered summary refreshes",
                dispatched=dispatched,
                claimed=len(claimed),
                buffer_seconds=self._buffer_seconds,
            )

        return dispatched


async def run_summary_refresh_sweep_loop(
    buffer_seconds: int = 300,
    batch_size: int = 50,
    interval_seconds: float = 30.0,
) -> None:
    """Run the summary refresh sweeper in a periodic loop.

    Designed to be launched as an asyncio.Task from the application lifespan,
    following the same pattern as run_outbox_relay_loop. Each cycle owns its
    connection and transaction via engine.begin().

    Args:
        buffer_seconds: Rolling-debounce quiet period before dispatch
        batch_size: Maximum refreshes to dispatch per sweep
        interval_seconds: Seconds to wait between sweep cycles
    """
    sweeper = SummaryRefreshSweeper(
        buffer_seconds=buffer_seconds,
        batch_size=batch_size,
    )

    logger.info(
        "Starting summary refresh sweep loop",
        buffer_seconds=buffer_seconds,
        batch_size=batch_size,
        interval_seconds=interval_seconds,
    )

    while True:
        try:
            engine = get_async_database_engine()
            async with engine.begin() as conn:
                await sweeper.sweep_batch(conn)
        except asyncio.CancelledError:
            logger.info("Summary refresh sweep loop cancelled")
            raise
        except Exception:
            logger.error("Error in summary refresh sweep loop", exc_info=True)

        await asyncio.sleep(interval_seconds)

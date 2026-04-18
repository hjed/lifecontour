"""Background task for periodic attendance status transitions.

Runs in the main backend process as a lifespan task, similar to
the outbox processor. Transitions ATTENDING → ATTENDED for
journal-contact relationships on events that have passed.
"""

import asyncio
from datetime import UTC, datetime

import structlog
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.services.attendance_transition_service import (
    AttendanceTransitionService,
)

logger = structlog.get_logger()


async def run_attendance_transition_loop(
    container: AsyncContainer,
    interval_seconds: float = 3600,
) -> None:
    """Run the attendance transition job in a periodic loop.

    Creates a new database connection per cycle from the container's engine,
    runs the transition service, then sleeps for the configured interval.

    Args:
        container: Application's AsyncContainer for dependency injection.
        interval_seconds: Interval between processing cycles (default: 1 hour).
    """
    logger.info(
        "Starting attendance transition loop",
        interval_seconds=interval_seconds,
    )

    while True:
        try:
            engine = await container.get(AsyncEngine)
            async with engine.begin() as conn:
                repo = SqlJournalContactRelationshipRepository(conn)
                service = AttendanceTransitionService(repo)

                cutoff = datetime.now(UTC)
                await service.transition_past_event_attendees(cutoff)

            await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("Attendance transition loop cancelled")
            break

        except Exception as e:
            logger.error(
                "Unexpected error in attendance transition loop",
                error=str(e),
            )
            # Wait before retrying to avoid tight error loops
            await asyncio.sleep(interval_seconds)

"""
Background task loop for processing the attended transition.
"""

import asyncio

import structlog
from dishka import AsyncContainer

from app.core.journal.models.repositories import JournalContactRelationshipRepository
from app.core.journal.services.attended_transition_service import (
    transition_attending_to_attended,
)


async def run_attended_transition_loop(
    container: AsyncContainer, interval_seconds: int = 3600
) -> None:
    """
    Periodically checks for events that have ended and transitions ATTENDING participants to ATTENDED.
    Default interval is 3600 seconds (1 hour).
    """
    logger = structlog.get_logger()
    logger.info(
        f"Starting attended transition background loop (interval: {interval_seconds}s)"
    )

    while True:
        try:
            # We use Dishka here so that we only keep the DB connection open briefly
            async with container() as request_container:
                repo = await request_container.get(JournalContactRelationshipRepository)

                result = await transition_attending_to_attended(repo)

                if result.transitioned_count > 0:
                    logger.info(
                        "Transitioned relationships from ATTENDING to ATTENDED",
                        count=result.transitioned_count,
                        batches=result.batches_processed,
                    )
        except asyncio.CancelledError:
            # Re-raise to allow graceful shutdown
            raise
        except Exception as e:
            logger.error("Error in attended transition loop", exc_info=e)

        # Sleep until the next check
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break

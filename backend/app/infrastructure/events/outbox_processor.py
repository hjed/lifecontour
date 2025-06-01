"""
Background processor for outbox events.

Processes events from the outbox table and sends them to external systems
like MeiliSearch for search indexing.
"""

import asyncio
from typing import Any

import structlog

from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.outbox_repository import OutboxRepository
from app.infrastructure.search.search_indexer import SearchIndexer

logger = structlog.get_logger()


class OutboxProcessor:
    """Background processor for outbox events."""

    def __init__(self) -> None:
        """Initialize the outbox processor."""
        self.max_retries = 3
        self.batch_size = 50

    async def process_events(self) -> None:
        """
        Process unprocessed events from the outbox.

        This method is called periodically by the background task.
        """
        try:
            engine = get_async_database_engine()

            # Use a new connection for each processing cycle
            async with engine.begin() as conn:
                repository = OutboxRepository(conn)
                search_indexer = SearchIndexer(db_connection=conn)

                # Get unprocessed events
                events = await repository.get_unprocessed_events(limit=self.batch_size)

                if not events:
                    logger.debug("No unprocessed events found in outbox")
                    return

                logger.info("Processing outbox events", event_count=len(events))

                # Process each event
                for event in events:
                    try:
                        await self._process_single_event(
                            event, repository, search_indexer
                        )

                    except Exception as e:
                        logger.error(
                            "Failed to process outbox event",
                            event_id=event.event_id,
                            event_type=event.event_type,
                            retry_count=event.retry_count,
                            error=str(e),
                        )

                        # Increment retry count if under max retries
                        if event.retry_count < self.max_retries:
                            await repository.increment_retry_count(event.event_id)
                        else:
                            logger.error(
                                "Event exceeded max retries, giving up",
                                event_id=event.event_id,
                                event_type=event.event_type,
                                retry_count=event.retry_count,
                            )

                # Commit the transaction
                await conn.commit()

                logger.info(
                    "Finished processing outbox events", processed_count=len(events)
                )

        except Exception as e:
            logger.error("Failed to process outbox events", error=str(e))

    async def _process_single_event(
        self, event: Any, repository: OutboxRepository, search_indexer: SearchIndexer
    ) -> None:
        """
        Process a single outbox event.

        Args:
            event: Outbox event to process
            repository: Repository for updating event status
            search_indexer: Search indexer with database connection
        """
        try:
            # Process the event with the search indexer
            await search_indexer.process_event(event)

            # Mark as processed
            await repository.mark_as_processed(event.event_id)

            logger.debug(
                "Successfully processed outbox event",
                event_id=event.event_id,
                event_type=event.event_type,
            )

        except Exception as e:
            logger.error(
                "Failed to process single outbox event",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(e),
            )
            raise

    async def get_failed_events_summary(self) -> dict[str, Any]:
        """
        Get a summary of failed events for monitoring.

        Returns:
            Dictionary with failed events summary
        """
        try:
            engine = get_async_database_engine()

            async with engine.begin() as conn:
                repository = OutboxRepository(conn)
                failed_events = await repository.get_failed_events(self.max_retries)

                summary = {
                    "failed_event_count": len(failed_events),
                    "failed_events": [
                        {
                            "event_id": event.event_id,
                            "event_type": event.event_type,
                            "retry_count": event.retry_count,
                            "created_at": event.created_at.isoformat(),
                        }
                        for event in failed_events
                    ],
                }

                return summary

        except Exception as e:
            logger.error("Failed to get failed events summary", error=str(e))
            return {"failed_event_count": 0, "failed_events": []}


# Global processor instance
_processor_instance: OutboxProcessor | None = None


def get_outbox_processor() -> OutboxProcessor:
    """Get the global outbox processor instance."""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = OutboxProcessor()
    return _processor_instance


async def run_outbox_processor_loop(interval_seconds: float = 10) -> None:
    """
    Run the outbox processor in a loop.

    Args:
        interval_seconds: Interval between processing cycles (in seconds, can be fractional)
    """
    processor = get_outbox_processor()

    logger.info("Starting outbox processor loop", interval_seconds=interval_seconds)

    while True:
        try:
            await processor.process_events()
            await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("Outbox processor loop cancelled")
            break

        except Exception as e:
            logger.error("Unexpected error in outbox processor loop", error=str(e))
            # Wait a bit before retrying to avoid tight error loops
            await asyncio.sleep(interval_seconds)

"""
Background processor for outbox events.

Processes events from the outbox table and sends them to external systems
like MeiliSearch for search indexing and contact sync event processing.
"""

import asyncio
from typing import Any

import structlog
from dishka import AsyncContainer

from app.core.integrations.outbox_event_processor import (
    PermanentOutboxEventProcessingError,
)
from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.outbox_repository import OutboxRepository
from app.infrastructure.search.search_indexer import SearchIndexer

logger = structlog.get_logger()


class OutboxProcessor:
    """Background processor for outbox events."""

    def __init__(self, container: AsyncContainer) -> None:
        """Initialize the outbox processor."""
        self.max_retries = 3
        self.batch_size = 50
        self.container = container

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
                events = await repository.get_unprocessed_events(
                    limit=self.batch_size,
                    max_retry_count=self.max_retries,
                )

                if not events:
                    logger.debug("No unprocessed events found in outbox")
                    return

                logger.info("Processing outbox events", event_count=len(events))

                # Process each event in its own savepoint so one database error
                # does not abort retry persistence or later events in the batch.
                for event in events:
                    try:
                        async with conn.begin_nested():
                            await self._process_single_event(
                                event, repository, search_indexer
                            )

                    except PermanentOutboxEventProcessingError as e:
                        logger.error(
                            "Outbox event has permanent invalid payload",
                            event_id=event.event_id,
                            event_type=event.event_type,
                            retry_count=event.retry_count,
                            error=str(e),
                        )
                        await repository.mark_as_failed(
                            event.event_id, retry_count=self.max_retries
                        )

                    except Exception as e:
                        logger.error(
                            "Failed to process outbox event",
                            event_id=event.event_id,
                            event_type=event.event_type,
                            retry_count=event.retry_count,
                            error=str(e),
                        )

                        await repository.increment_retry_count(event.event_id)

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

        Routes events to appropriate processors:
        - contact.* events -> OutboxEventProcessor (contact sync)
        - Other events -> SearchIndexer (MeiliSearch indexing)

        Note on transaction scope:
        This method runs within a per-event nested transaction/savepoint inside the
        batch transaction. Successful event work and its processed marker are committed
        together, while failures roll back to the savepoint so retry state can still be
        persisted and later events can continue.

        Args:
            event: Outbox event to process
            repository: Repository for updating event status
            search_indexer: Search indexer with database connection
        """
        try:
            # Route contact sync events to OutboxEventProcessor
            if event.event_type.startswith("contact."):
                await self._process_contact_event(event, search_indexer.db_connection)
            else:
                # Process other events with the search indexer
                await search_indexer.process_event(event)

            # Additionally route journal events to integration workers
            if event.event_type in (
                "JournalCreated",
                "JournalUpdated",
                "JournalDeleted",
            ):
                await self._process_journal_event(event)

            # Mark as processed
            await repository.mark_as_processed(event.event_id)

            logger.debug(
                "Successfully processed outbox event",
                event_id=event.event_id,
                event_type=event.event_type,
            )

        except PermanentOutboxEventProcessingError:
            raise
        except Exception as e:
            logger.error(
                "Failed to process single outbox event",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(e),
            )
            raise

    async def _process_contact_event(self, event: Any, connection: Any) -> None:
        """
        Process contact sync events using OutboxEventProcessor.

        Args:
            event: Contact sync event (contact.created, contact.updated, etc.)
            connection: Database connection for transaction
        """
        # Import here to avoid circular dependencies
        from app.core.contacts.adapters.sql.contact_field_history_repository import (
            SqlContactFieldHistoryRepository,
        )
        from app.core.contacts.adapters.sql.contact_repository import (
            SqlContactRepository,
        )
        from app.core.contacts.adapters.sql.tag_repository import SqlTagRepository
        from app.core.contacts.services.address_validation_service import (
            AddressValidationService,
        )
        from app.core.contacts.services.contact_history_service import (
            ContactHistoryService,
        )
        from app.core.contacts.services.contact_service import ContactService
        from app.core.contacts.services.contact_validation_service import (
            ContactValidationService,
        )
        from app.core.contacts.services.tag_hierarchy_service import (
            TagHierarchyService,
        )
        from app.core.integrations.outbox_event_processor import OutboxEventProcessor
        from app.infrastructure.events.outbox_event_publisher import (
            OutboxEventPublisher,
        )

        # Create repositories
        contact_repository = SqlContactRepository(connection)
        tag_repository = SqlTagRepository(connection)
        history_repository = SqlContactFieldHistoryRepository(connection)
        event_publisher = OutboxEventPublisher(connection)

        # Create services
        address_validation_service = AddressValidationService()
        contact_validation_service = ContactValidationService(contact_repository)
        history_service = ContactHistoryService(history_repository)
        tag_hierarchy_service = TagHierarchyService(tag_repository)

        # Create contact service
        contact_service = ContactService(
            contact_repo=contact_repository,
            tag_repo=tag_repository,
            history_repo=history_repository,
            event_publisher=event_publisher,
            address_validation_service=address_validation_service,
            contact_validation_service=contact_validation_service,
            history_service=history_service,
            tag_hierarchy_service=tag_hierarchy_service,
        )

        # Create outbox event processor
        event_processor = OutboxEventProcessor(contact_service, connection)

        # Process the event
        result = await event_processor.process_event(event)

        logger.info(
            "Processed contact sync event",
            event_id=event.event_id,
            event_type=event.event_type,
            result=result,
        )

    async def _process_journal_event(self, event: Any) -> None:
        """
        Broadcast journal events to all integrations.

        Args:
            event: Journal sync event (JournalCreated, JournalUpdated, JournalDeleted)
        """
        from app.core.integrations.task_queue_service import TaskQueueService

        async with self.container() as request_container:
            task_queue = await request_container.get(TaskQueueService)
            await task_queue.broadcast_journal_event(event.event_type, event.event_data)
        logger.info(
            "Broadcasted journal sync event to workers",
            event_id=event.event_id,
            event_type=event.event_type,
        )

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


def get_outbox_processor(container: AsyncContainer) -> OutboxProcessor:
    """Get the global outbox processor instance."""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = OutboxProcessor(container)
    return _processor_instance


async def run_outbox_processor_loop(
    container: AsyncContainer, interval_seconds: float = 10
) -> None:
    """
    Run the outbox processor in a loop.

    Args:
        container: Application's AsyncContainer for dependency injection
        interval_seconds: Interval between processing cycles (in seconds, can be fractional)
    """
    processor = get_outbox_processor(container)

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

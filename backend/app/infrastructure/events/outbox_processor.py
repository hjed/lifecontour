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
from app.infrastructure.config import get_settings
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
            # Check if stream consumers handle search/summary processing
            settings = get_settings()
            stream_consumers_active = settings.use_stream_consumers

            # Route contact sync events to OutboxEventProcessor
            if event.event_type.startswith("contact."):
                if not stream_consumers_active:
                    await self._process_contact_event(
                        event, search_indexer.db_connection
                    )
            elif event.event_type.startswith(
                "journal_event."
            ) or event.event_type.startswith("journal_review."):
                if not stream_consumers_active:
                    await self._process_journal_sync_event(
                        event, search_indexer.db_connection
                    )
            elif event.event_type == "ContactSummaryRefreshRequested":
                if not stream_consumers_active:
                    await self._process_summary_generation_event(
                        event, search_indexer.db_connection
                    )
                    # After summary generation completes, forward the event to search indexer
                    # so the contact index is updated with the new summary text
                    await search_indexer.process_event(event)
            else:
                # Process other events with the search indexer
                if not stream_consumers_active:
                    await search_indexer.process_event(event)

            # Additionally route journal events to integration workers
            # and invalidate daily summary cache
            if event.event_type in (
                "JournalCreated",
                "JournalUpdated",
                "JournalDeleted",
            ):
                if not stream_consumers_active:
                    await self._process_journal_event(event)
                    await self._invalidate_daily_summary_for_journal_event(
                        event, search_indexer.db_connection
                    )

            # Route tag events to integration workers
            if event.event_type in (
                "TagUpdated",
                "TagDeleted",
            ):
                if not stream_consumers_active:
                    await self._process_tag_event(event)

            # Mark as processed
            await repository.mark_as_processed(event.event_id)

            logger.debug(
                "Successfully processed outbox event",
                event_id=event.event_id,
                event_type=event.event_type,
                stream_consumers_active=stream_consumers_active,
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

    async def _process_journal_sync_event(self, event: Any, connection: Any) -> None:
        """
        Process inbound journal sync events using JournalOutboxEventProcessor.

        Handles both journal_event.* (Phase 1: create/update journals) and
        journal_review.* (Phase 2: detect matches) events.

        Args:
            event: Journal sync or review event
            connection: Database connection for transaction
        """
        from app.core.integrations.journal_outbox_event_processor import (
            JournalOutboxEventProcessor,
        )
        from app.core.integrations.match_detection_event_processor import (
            MatchDetectionEventProcessor,
        )
        from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
            SqlJournalContactRelationshipRepository,
        )
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )
        from app.core.journal.adapters.sql.review_item_repository import (
            SqlReviewItemRepository,
        )
        from app.core.journal.services.journal_service import JournalService
        from app.core.journal.services.match_candidate_detector import (
            MatchCandidateDetector,
        )
        from app.core.journal.services.title_similarity_assessor import (
            GeminiTitleSimilarityAssessor,
        )
        from app.infrastructure.config import get_settings
        from app.infrastructure.events.outbox_event_publisher import (
            OutboxEventPublisher,
        )

        settings = get_settings()

        if event.event_type.startswith("journal_review."):
            # Create match detection dependencies (only if Gemini configured)
            review_item_repo = SqlReviewItemRepository(connection)
            match_detector = None
            if settings.gemini_api_key:
                similarity_assessor = GeminiTitleSimilarityAssessor(
                    api_key=settings.gemini_api_key,
                    model=settings.gemini_model,
                )
                match_detector = MatchCandidateDetector(
                    similarity_assessor=similarity_assessor,
                )

            processor = MatchDetectionEventProcessor(
                connection=connection,
                match_candidate_detector=match_detector,
                review_item_repository=review_item_repo,
            )
            result = await processor.process_event(event)
        else:
            # Phase 1: journal sync events
            journal_repo = SqlJournalRepository(connection)
            event_publisher = OutboxEventPublisher(connection)
            contact_relationship_repo = SqlJournalContactRelationshipRepository(
                connection
            )
            journal_service = JournalService(
                journal_repo=journal_repo,
                event_publisher=event_publisher,
                contact_relationship_repo=contact_relationship_repo,
            )

            # Need optional detector for gating Phase 2 emission
            match_detector = None
            if settings.gemini_api_key:
                similarity_assessor_fallback = GeminiTitleSimilarityAssessor(
                    api_key=settings.gemini_api_key,
                    model=settings.gemini_model,
                )
                match_detector = MatchCandidateDetector(
                    similarity_assessor=similarity_assessor_fallback,
                )

            outbox_processor = JournalOutboxEventProcessor(
                journal_service=journal_service,
                connection=connection,
                match_candidate_detector=match_detector,
            )
            result = await outbox_processor.process_event(event)

        logger.info(
            "Processed journal sync event",
            event_id=event.event_id,
            event_type=event.event_type,
            result=result,
        )

    async def _process_summary_generation_event(
        self, event: Any, connection: Any
    ) -> None:
        """
        Process a ContactSummaryRefreshRequested event to generate an AI summary.

        Constructs the full generation pipeline inline (following the same pattern
        as _process_contact_event and _process_journal_sync_event) and runs the
        summary generation for the specified contact.

        Args:
            event: ContactSummaryRefreshRequested event
            connection: Database connection for transaction
        """
        from app.core.contacts.adapters.sql.contact_field_history_repository import (
            SqlContactFieldHistoryRepository,
        )
        from app.core.contacts.adapters.sql.contact_repository import (
            SqlContactRepository,
        )
        from app.core.contacts.adapters.sql.contact_summary_repository import (
            SqlContactSummaryRepository,
        )
        from app.core.contacts.services.summary_generation_service import (
            LowActivityChecker,
            SummaryGenerator,
            SummaryInputAssembler,
        )
        from app.core.contacts.services.summary_prompt_builder import (
            SummaryPromptBuilder,
        )
        from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
            SqlJournalContactRelationshipRepository,
        )
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )
        from app.infrastructure.config import get_settings

        settings = get_settings()

        if not settings.gemini_api_key:
            logger.info(
                "Gemini API key not configured, skipping summary generation",
                event_id=event.event_id,
            )
            return

        contact_id_raw = event.event_data.get("contact_id")
        if not contact_id_raw:
            logger.error(
                "ContactSummaryRefreshRequested event missing contact_id",
                event_id=event.event_id,
            )
            return

        try:
            contact_id = int(contact_id_raw)
        except (TypeError, ValueError):
            logger.error(
                "ContactSummaryRefreshRequested event has invalid contact_id",
                event_id=event.event_id,
                contact_id_raw=contact_id_raw,
            )
            return

        if contact_id <= 0:
            logger.error(
                "ContactSummaryRefreshRequested event has non-positive contact_id",
                event_id=event.event_id,
                contact_id=contact_id,
            )
            return

        # Create repositories
        contact_repo = SqlContactRepository(connection)
        history_repo = SqlContactFieldHistoryRepository(connection)
        journal_rel_repo = SqlJournalContactRelationshipRepository(connection)
        journal_repo = SqlJournalRepository(connection)
        summary_repo = SqlContactSummaryRepository(connection)

        # Create services
        input_assembler = SummaryInputAssembler(
            contact_repo=contact_repo,
            history_repo=history_repo,
            journal_relationship_repo=journal_rel_repo,
            journal_repo=journal_repo,
            summary_repo=summary_repo,
        )
        activity_checker = LowActivityChecker()
        prompt_builder = SummaryPromptBuilder()

        generator = SummaryGenerator(
            input_assembler=input_assembler,
            activity_checker=activity_checker,
            prompt_builder=prompt_builder,
            summary_repo=summary_repo,
            gemini_api_key=settings.gemini_api_key,
            gemini_model=settings.gemini_summary_model,
        )

        result = await generator.generate(contact_id=contact_id)

        logger.info(
            "Processed summary generation event",
            event_id=event.event_id,
            contact_id=contact_id,
            result_status=result.status.value if result else "skipped",
        )

    async def _process_tag_event(self, event: Any) -> None:
        """
        Broadcast tag events to all integrations.

        Args:
            event: Tag domain event (TagUpdated, TagDeleted)
        """
        from app.core.integrations.task_queue_service import TaskQueueService

        async with self.container() as request_container:
            task_queue = await request_container.get(TaskQueueService)
            await task_queue.broadcast_tag_event(event.event_type, event.event_data)

        logger.info(
            "Broadcasted tag event to workers",
            event_id=event.event_id,
            event_type=event.event_type,
        )

    async def _invalidate_daily_summary_for_journal_event(
        self, event: Any, connection: Any
    ) -> None:
        """Invalidate daily summary cache when a journal is created/updated/deleted.

        Looks up the journal by ID from the database to get the user_id and
        event date, since domain events don't carry all fields needed.

        Args:
            event: Journal domain event (JournalCreated, JournalUpdated, JournalDeleted)
            connection: Database connection for transaction
        """
        from app.core.journal.adapters.sql.daily_summary_repository import (
            SqlJournalDailySummaryRepository,
        )
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        event_data = event.event_data or {}
        journal_id = event_data.get("journal_id")

        if not journal_id:
            logger.debug(
                "Cannot invalidate daily summary: missing journal_id",
                event_id=event.event_id,
                event_type=event.event_type,
            )
            return

        # Look up the journal to get user_id and event date
        journal_repo = SqlJournalRepository(connection)
        journal = await journal_repo.find_by_id(int(journal_id))

        if journal is None:
            # Journal may have been deleted — try user_id from event data
            # (JournalDeleted includes user_id)
            user_id = event_data.get("user_id")
            if not user_id:
                logger.debug(
                    "Cannot invalidate daily summary: journal not found and no user_id",
                    event_id=event.event_id,
                    journal_id=journal_id,
                )
                return
            # For deleted journals, we can't determine the date — skip invalidation
            # The next request will regenerate if needed
            logger.debug(
                "Journal deleted, cannot determine date for summary invalidation",
                event_id=event.event_id,
                journal_id=journal_id,
            )
            return

        # Extract date from the journal's event_date_range_start
        event_start = journal.event_date_range.start
        if event_start is None:
            logger.debug(
                "Cannot invalidate daily summary: journal has no event_date_range_start",
                event_id=event.event_id,
                journal_id=journal_id,
            )
            return

        summary_date = event_start.date()

        summary_repo = SqlJournalDailySummaryRepository(connection)
        await summary_repo.invalidate_for_date(journal.user_id, summary_date)

        logger.info(
            "Invalidated daily summary for journal event",
            event_id=event.event_id,
            event_type=event.event_type,
            user_id=journal.user_id,
            summary_date=summary_date.isoformat(),
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


async def run_outbox_processor_loop(
    container: AsyncContainer, interval_seconds: float = 10
) -> None:
    """
    Run the outbox processor in a loop.

    Args:
        container: Application's AsyncContainer for dependency injection
        interval_seconds: Interval between processing cycles (in seconds, can be fractional)
    """
    processor = await container.get(OutboxProcessor)

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

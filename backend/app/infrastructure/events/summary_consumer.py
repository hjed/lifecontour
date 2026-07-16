"""
Summary Generator consumer for Redis Streams.

Processes contact-summary refresh events from the pms:domain-events stream
as the 'summary-generator' consumer group. ContactSummaryRefreshRequested
(buffered intent, published per contact edit / journal link / sync) only
records a rolling-debounce marker; ContactSummaryRefreshDue (published by the
summary refresh sweeper after the quiet period, or directly by the manual
refresh endpoint) generates the AI summary and updates the search index.
"""

import structlog
from core_shared.stream_client import StreamClient, StreamEvent
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.config import get_settings
from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.dead_letter_consumer_mixin import DeadLetterConsumerMixin
from app.infrastructure.events.stream_consumer import StreamConsumer
from app.infrastructure.events.stream_event_adapter import stream_event_to_outbox_event
from app.infrastructure.search.search_indexer import SearchIndexer

logger = structlog.get_logger()


class SummaryConsumer(DeadLetterConsumerMixin, StreamConsumer):
    """Stream consumer for AI contact summary generation.

    Listens for ``ContactSummaryRefreshRequested`` and
    ``ContactSummaryRefreshDue`` events on the ``pms:domain-events`` stream
    using the ``summary-generator`` consumer group. Requested events are
    buffered (debounce marker write only); Due events generate the summary
    via the existing pipeline and update the search index afterward.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        container: AsyncContainer,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "summary-generator-1",
        batch_size: int = 5,
        block_ms: int = 5000,
    ) -> None:
        """Initialize the summary consumer.

        Args:
            stream_client: Redis Streams client
            container: Dishka DI container
            stream_name: Name of the domain events stream
            consumer_name: Individual consumer name within the group
            batch_size: Maximum events to read per XREADGROUP call
            block_ms: Milliseconds to block waiting for new events
        """
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="summary-generator",
            consumer_name=consumer_name,
            event_type_patterns=[
                "ContactSummaryRefreshRequested",
                "ContactSummaryRefreshDue",
            ],
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._container = container

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process a contact-summary refresh event.

        ``ContactSummaryRefreshRequested`` (buffered intent) only records the
        rolling-debounce marker — one cheap UPDATE per event, no Gemini call.
        Contact search reindexing for these events is handled independently by
        the SearchIndexerConsumer, so nothing else is needed here.

        ``ContactSummaryRefreshDue`` generates the AI summary for the contact,
        then updates the MeiliSearch index so the new summary text is
        searchable.

        Args:
            event: The stream event to process
        """
        if event.event_type == "ContactSummaryRefreshRequested":
            await self._mark_refresh_requested(event)
            return

        outbox_event = stream_event_to_outbox_event(event)

        engine = get_async_database_engine()

        # Set up MCP background context
        from app.mcp.shared.dependencies import mcp_background_container

        async with self._container() as request_container:
            # Set the container in contextvar for FastMCP tools
            mcp_background_container.set(request_container)

            async with engine.begin() as conn:
                # Attempt summary generation
                await self._generate_summary(outbox_event, conn)

                # Always update the search index (even if summary was skipped)
                # so the contact record reflects the latest state
                search_indexer = SearchIndexer(db_connection=conn)
                await search_indexer.process_event(outbox_event)

        logger.debug(
            "Summary consumer processed event",
            event_id=event.event_id,
            event_type=event.event_type,
        )

    async def _mark_refresh_requested(self, event: StreamEvent) -> None:
        """Record the rolling-debounce marker for a buffered refresh request.

        Every Requested event overwrites the marker timestamp, so generation
        only runs once the contact has been quiet for the buffer window (the
        summary refresh sweeper publishes ContactSummaryRefreshDue then).

        Args:
            event: The ContactSummaryRefreshRequested stream event
        """
        # Lazy import to avoid circular dependencies (see _generate_summary)
        from app.core.contacts.adapters.sql.contact_summary_repository import (
            SqlContactSummaryRepository,
        )

        contact_id = self._extract_contact_id(event)
        if contact_id is None:
            return

        engine = get_async_database_engine()
        async with engine.begin() as conn:
            await SqlContactSummaryRepository(conn).mark_refresh_requested(contact_id)

        logger.debug(
            "Buffered summary refresh request",
            event_id=event.event_id,
            contact_id=contact_id,
        )

    def _extract_contact_id(self, event: object) -> int | None:
        """Validate and return the contact_id from a refresh event, or None."""
        event_data = event.event_data  # type: ignore[attr-defined]
        contact_id_raw = event_data.get("contact_id")
        if not contact_id_raw:
            logger.error(
                "Summary refresh event missing contact_id",
                event_id=event.event_id,  # type: ignore[attr-defined]
            )
            return None

        try:
            contact_id = int(contact_id_raw)
        except TypeError, ValueError:
            logger.error(
                "Summary refresh event has invalid contact_id",
                event_id=event.event_id,  # type: ignore[attr-defined]
                contact_id_raw=contact_id_raw,
            )
            return None

        if contact_id <= 0:
            logger.error(
                "Summary refresh event has non-positive contact_id",
                event_id=event.event_id,  # type: ignore[attr-defined]
                contact_id=contact_id,
            )
            return None

        return contact_id

    async def _generate_summary(
        self, event: object, connection: AsyncConnection
    ) -> None:
        """Generate an AI summary for the contact.

        Replicates the logic from OutboxProcessor._process_summary_generation_event.

        Args:
            event: The outbox event with contact_id in event_data
            connection: Database connection
        """
        # Lazy imports to avoid circular dependencies
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
        from app.core.settings.adapters.sql.user_settings_repository import (
            SqlUserSettingsRepository,
        )

        settings = get_settings()

        if not settings.gemini_api_key:
            logger.info(
                "Gemini API key not configured, skipping summary generation",
                event_id=event.event_id,  # type: ignore[attr-defined]
            )
            return

        contact_id = self._extract_contact_id(event)
        if contact_id is None:
            return

        # Create repositories
        contact_repo = SqlContactRepository(connection)
        history_repo = SqlContactFieldHistoryRepository(connection)
        journal_rel_repo = SqlJournalContactRelationshipRepository(connection)
        journal_repo = SqlJournalRepository(connection)
        summary_repo = SqlContactSummaryRepository(connection)

        # Publish ContactSummaryUpdated to the outbox on the same connection so the
        # event commits atomically with the summary row; the history projection
        # consumer records summary history from it (ITER12-003 Phase 2).
        from app.infrastructure.events.outbox_event_publisher import (
            OutboxEventPublisher,
        )

        event_publisher = OutboxEventPublisher(connection)

        input_assembler = SummaryInputAssembler(
            contact_repo=contact_repo,
            history_repo=history_repo,
            journal_relationship_repo=journal_rel_repo,
            journal_repo=journal_repo,
            summary_repo=summary_repo,
        )
        activity_checker = LowActivityChecker()
        prompt_builder = SummaryPromptBuilder()

        # Resolve the user's timezone so generated summaries render dates/times
        # in local time. This is a background worker with no request user, so we
        # use the single-user fallback.
        user_settings_repo = SqlUserSettingsRepository(connection)
        timezone = await user_settings_repo.get_default_timezone()

        generator = SummaryGenerator(
            input_assembler=input_assembler,
            activity_checker=activity_checker,
            prompt_builder=prompt_builder,
            summary_repo=summary_repo,
            gemini_api_key=settings.gemini_api_key,
            gemini_model=settings.gemini_summary_model,
            event_publisher=event_publisher,
            connection=connection,
            timezone=timezone,
        )

        result = await generator.generate(contact_id=contact_id)

        logger.info(
            "Processed summary generation event (stream consumer)",
            event_id=event.event_id,  # type: ignore[attr-defined]
            contact_id=contact_id,
            result_status=result.status.value if result else "skipped",
        )

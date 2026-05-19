"""
Summary Generator consumer for Redis Streams.

Processes ContactSummaryRefreshRequested events from the pms:domain-events
stream, generates AI contact summaries, and updates the search index.
Runs as the 'summary-generator' consumer group.
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

    Listens for ``ContactSummaryRefreshRequested`` events on the
    ``pms:domain-events`` stream using the ``summary-generator``
    consumer group. Generates summaries via the existing pipeline
    and updates the search index afterward.
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
            event_type_patterns=["ContactSummaryRefreshRequested"],
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._container = container

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process a ContactSummaryRefreshRequested event.

        Generates an AI summary for the contact, then updates the
        MeiliSearch index so the new summary text is searchable.

        Args:
            event: The stream event to process
        """
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

        settings = get_settings()

        if not settings.gemini_api_key:
            logger.info(
                "Gemini API key not configured, skipping summary generation",
                event_id=event.event_id,  # type: ignore[attr-defined]
            )
            return

        event_data = event.event_data  # type: ignore[attr-defined]
        contact_id_raw = event_data.get("contact_id")
        if not contact_id_raw:
            logger.error(
                "ContactSummaryRefreshRequested event missing contact_id",
                event_id=event.event_id,  # type: ignore[attr-defined]
            )
            return

        try:
            contact_id = int(contact_id_raw)
        except (TypeError, ValueError):
            logger.error(
                "ContactSummaryRefreshRequested event has invalid contact_id",
                event_id=event.event_id,  # type: ignore[attr-defined]
                contact_id_raw=contact_id_raw,
            )
            return

        if contact_id <= 0:
            logger.error(
                "ContactSummaryRefreshRequested event has non-positive contact_id",
                event_id=event.event_id,  # type: ignore[attr-defined]
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
        from app.core.contacts.services.contact_history_service import (
            ContactHistoryService,
        )

        history_service = ContactHistoryService(history_repo)

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
            history_service=history_service,
        )

        result = await generator.generate(contact_id=contact_id)

        logger.info(
            "Processed summary generation event (stream consumer)",
            event_id=event.event_id,  # type: ignore[attr-defined]
            contact_id=contact_id,
            result_status=result.status.value if result else "skipped",
        )

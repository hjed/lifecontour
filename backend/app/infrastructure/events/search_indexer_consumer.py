"""
Search Indexer consumer for Redis Streams.

Processes domain events from the pms:domain-events stream and updates
MeiliSearch indices via the existing SearchIndexer. Runs as the
'search-indexer' consumer group.
"""

import structlog
from core_shared.stream_client import StreamClient, StreamEvent
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.dead_letter_consumer_mixin import DeadLetterConsumerMixin
from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.events.stream_consumer import StreamConsumer
from app.infrastructure.events.stream_event_adapter import stream_event_to_outbox_event
from app.infrastructure.search.search_indexer import SearchIndexer

logger = structlog.get_logger()

# All event types the SearchIndexer handles.
# These are contact-scoped events, contact-tag events,
# contact important date events, and journal events.
_SEARCH_EVENT_TYPES: list[str] = [
    # Contact events
    "ContactCreated",
    "ContactUpdated",
    "ContactDeleted",
    "ContactSummaryRefreshRequested",
    # Contact relationship events
    "ContactRelationshipCreated",
    "ContactRelationshipUpdated",
    "ContactRelationshipDeleted",
    # Contact-tag assignment/removal events
    "TagAssigned",
    "TagRemoved",
    # Contact-scoped important date events
    "ImportantDateAdded",
    "ImportantDateDeleted",
    # Journal events
    "JournalCreated",
    "JournalUpdated",
    "JournalDeleted",
]

# Journal event types that also trigger daily summary invalidation
_JOURNAL_INVALIDATION_EVENTS = frozenset(
    {"JournalCreated", "JournalUpdated", "JournalDeleted"}
)


class SearchIndexerConsumer(DeadLetterConsumerMixin, StreamConsumer):
    """Stream consumer for MeiliSearch indexing.

    Listens to contact, journal, and tag-related domain events on the
    ``pms:domain-events`` stream using the ``search-indexer`` consumer
    group. Delegates to the existing :class:`SearchIndexer` for actual
    MeiliSearch operations.

    For journal events, also runs daily summary cache invalidation
    (same behaviour as the legacy OutboxProcessor).
    """

    def __init__(
        self,
        stream_client: StreamClient,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "search-indexer-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Initialize the search indexer consumer.

        Args:
            stream_client: Redis Streams client
            stream_name: Name of the domain events stream
            consumer_name: Individual consumer name within the group
            batch_size: Maximum events to read per XREADGROUP call
            block_ms: Milliseconds to block waiting for new events
        """
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="search-indexer",
            consumer_name=consumer_name,
            event_type_patterns=_SEARCH_EVENT_TYPES,
            batch_size=batch_size,
            block_ms=block_ms,
        )

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process a search-relevant event.

        Converts the stream event to an OutboxEvent and delegates to
        SearchIndexer. For journal CRUD events, also invalidates the
        daily summary cache.

        Args:
            event: The stream event to process
        """
        outbox_event = stream_event_to_outbox_event(event)

        engine = get_async_database_engine()
        async with engine.begin() as conn:
            search_indexer = SearchIndexer(db_connection=conn)
            await search_indexer.process_event(outbox_event)

            # Journal events also trigger daily summary cache invalidation
            if event.event_type in _JOURNAL_INVALIDATION_EVENTS:
                await self._invalidate_daily_summary(outbox_event, conn)

        logger.debug(
            "Search indexer consumer processed event",
            event_id=event.event_id,
            event_type=event.event_type,
        )

    async def _invalidate_daily_summary(
        self, event: OutboxEvent, connection: AsyncConnection
    ) -> None:
        """Invalidate daily summary cache for journal events.

        Replicates the logic from OutboxProcessor._invalidate_daily_summary_for_journal_event.

        Args:
            event: The outbox event (JournalCreated/Updated/Deleted)
            connection: Database connection
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

        journal_repo = SqlJournalRepository(connection)
        journal = await journal_repo.find_by_id(int(journal_id))

        if journal is None:
            # Journal may have been deleted — try user_id from event data
            user_id = event_data.get("user_id")
            if not user_id:
                logger.debug(
                    "Cannot invalidate daily summary: journal not found and no user_id",
                    event_id=event.event_id,
                    journal_id=journal_id,
                )
                return
            logger.debug(
                "Journal deleted, cannot determine date for summary invalidation",
                event_id=event.event_id,
                journal_id=journal_id,
            )
            return

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
            "Invalidated daily summary for journal event (stream consumer)",
            event_id=event.event_id,
            event_type=event.event_type,
            user_id=journal.user_id,
            summary_date=summary_date.isoformat(),
        )

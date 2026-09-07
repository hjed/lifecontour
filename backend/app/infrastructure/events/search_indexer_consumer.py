"""
Search Indexer consumer for Redis Streams.

Processes domain events from the pms:domain-events stream and updates
MeiliSearch indices via the existing SearchIndexer. Runs as the
'search-indexer' consumer group.

**Indexing, and nothing else.** Daily summary invalidation used to run here for
journal events, having landed in the same handler by history rather than by
design. ITER18-005 Phase 7 moved it to ``SummaryInvalidationConsumer``, which
owns summary freshness for every input the summary has — journals, tasks and
contact dates. It could not have stayed: this consumer permanently ignores task
events, and a task change makes a summary stale.
"""

import structlog
from core_shared.stream_client import StreamClient, StreamEvent

from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.dead_letter_consumer_mixin import DeadLetterConsumerMixin
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
    "ContactMerged",
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
    # Journal-tag events. The journal document carries `tag_ids`, so a tag change
    # makes it stale. `JournalTagRenamed` is deliberately excluded — the document
    # indexes tag ids and never tag names, so a rename changes nothing in it.
    "JournalTagAssigned",
    "JournalTagRemoved",
    "JournalTagDeleted",
    "JournalTagMerged",
]


class SearchIndexerConsumer(DeadLetterConsumerMixin, StreamConsumer):
    """Stream consumer for MeiliSearch indexing.

    Listens to contact, journal, and tag-related domain events on the
    ``pms:domain-events`` stream using the ``search-indexer`` consumer
    group. Delegates to the existing :class:`SearchIndexer` for actual
    MeiliSearch operations.

    Daily summary invalidation is **not** here any more; see the module
    docstring and ``SummaryInvalidationConsumer``.
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
        SearchIndexer.

        Args:
            event: The stream event to process
        """
        outbox_event = stream_event_to_outbox_event(event)

        engine = get_async_database_engine()
        async with engine.begin() as conn:
            search_indexer = SearchIndexer(db_connection=conn)
            await search_indexer.process_event(outbox_event)

        logger.debug(
            "Search indexer consumer processed event",
            event_id=event.event_id,
            event_type=event.event_type,
        )

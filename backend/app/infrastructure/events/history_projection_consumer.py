"""History projection consumer for Redis Streams.

Projects journal domain events from the ``pms:domain-events`` stream into
``field_history`` rows via :class:`HistoryService`. Runs as the
``history-projection`` consumer group.

This is the event-driven replacement for a synchronous dual-write: a journal
mutation publishes a single event, and this consumer derives the history rows
from it. Writes are idempotent (``record_change`` uses ``ON CONFLICT DO
NOTHING`` on ``(event_id, entity_type, entity_id, field_name)``), so stream
redelivery never produces duplicate entries.
"""

import structlog
from core_shared.stream_client import StreamClient, StreamEvent

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.services.history_service import HistoryService
from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.dead_letter_consumer_mixin import DeadLetterConsumerMixin
from app.infrastructure.events.stream_consumer import StreamConsumer
from app.infrastructure.events.stream_event_adapter import stream_event_to_outbox_event

logger = structlog.get_logger()

# Journal-domain event types this consumer projects into history.
_JOURNAL_HISTORY_EVENT_TYPES: list[str] = [
    "JournalCreated",
    "JournalUpdated",
    "JournalDeleted",
    "JournalTypeAdded",
    "JournalTypeRemoved",
    "RouteCreated",
    "RouteUpdated",
    "RouteDeleted",
    "GearItemUpdated",
]

# Contact-domain event types the projection knows how to map (HistoryService has a
# handler for each). ITER12-003 Phase 1 deliberately keeps these OUT of the live
# subscription below: the synchronous dual-write is still the sole writer of
# contact history this phase, so subscribing here would double-write. Phase 2 adds
# these to ``event_type_patterns`` and removes the dual-write atomically. The list
# lives here so Phase 2 (and the inertness-invariant test) can reference it.
_CONTACT_HISTORY_EVENT_TYPES: list[str] = [
    "ContactCreated",
    "ContactUpdated",
    "ContactDeleted",
    "ContactMethodAdded",
    "ContactMethodDeleted",
    "ContactAddressAdded",
    "ContactAddressDeleted",
    "ContactNoteAdded",
    "ImportantDateAdded",
    "ImportantDateDeleted",
    "TagAssigned",
    "TagRemoved",
    "ContactRelationshipCreated",
    "ContactRelationshipUpdated",
    "ContactRelationshipDeleted",
    "ContactSummaryUpdated",
]


class HistoryProjectionConsumer(DeadLetterConsumerMixin, StreamConsumer):
    """Stream consumer that projects journal events into field history.

    Listens to journal/route/gear domain events on the ``pms:domain-events``
    stream using the ``history-projection`` consumer group and delegates the
    event-to-rows mapping to :class:`HistoryService`.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "history-projection-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Initialize the history projection consumer.

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
            group_name="history-projection",
            consumer_name=consumer_name,
            event_type_patterns=_JOURNAL_HISTORY_EVENT_TYPES,
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._history_service = HistoryService()

    async def _handle_event(self, event: StreamEvent) -> None:
        """Project a journal event into history rows and write them idempotently.

        Args:
            event: The stream event to project
        """
        outbox_event = stream_event_to_outbox_event(event)
        entries = self._history_service.project_event(outbox_event)
        if not entries:
            return

        engine = get_async_database_engine()
        async with engine.begin() as conn:
            repo = SqlFieldHistoryRepository(conn)
            for entry in entries:
                await repo.record_change(entry)

        logger.debug(
            "History projection consumer processed event",
            event_id=event.event_id,
            event_type=event.event_type,
            rows=len(entries),
        )

"""
Google Outbound consumer for Redis Streams.

Processes journal and tag domain events from the pms:domain-events stream
and broadcasts them to the Google integration worker via ARQ.
Runs as the 'google-worker' consumer group.

Replicates the outbound broadcast logic from OutboxProcessor._process_journal_event
and OutboxProcessor._process_tag_event, maintaining exact behavioral parity.
"""

import structlog
from core_shared.stream_client import StreamClient, StreamEvent
from dishka import AsyncContainer

from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.events.stream_consumer import StreamConsumer

logger = structlog.get_logger()

# Journal event types that trigger outbound broadcast to Google worker.
_JOURNAL_EVENT_TYPES = frozenset({"JournalCreated", "JournalUpdated", "JournalDeleted"})

# Tag event types that trigger outbound broadcast to Google worker.
_TAG_EVENT_TYPES = frozenset({"TagUpdated", "TagDeleted"})

# Combined event type list for pattern matching (exact match).
_OUTBOUND_EVENT_TYPES: list[str] = sorted(_JOURNAL_EVENT_TYPES | _TAG_EVENT_TYPES)


class GoogleOutboundConsumer(StreamConsumer):
    """Stream consumer for outbound Google integration broadcast.

    Listens to journal and tag domain events on the ``pms:domain-events``
    stream using the ``google-worker`` consumer group. Broadcasts events
    to the Google integration worker via ARQ using ``TaskQueueService``.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        container: AsyncContainer,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "google-worker-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Initialize the Google outbound consumer.

        Args:
            stream_client: Redis Streams client
            container: Dishka AsyncContainer for dependency injection
            stream_name: Name of the domain events stream
            consumer_name: Individual consumer name within the group
            batch_size: Maximum events to read per XREADGROUP call
            block_ms: Milliseconds to block waiting for new events
        """
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="google-worker",
            consumer_name=consumer_name,
            event_type_patterns=_OUTBOUND_EVENT_TYPES,
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._container = container

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process an outbound event by broadcasting to Google worker.

        Routes events to the appropriate TaskQueueService broadcast method:
        - ``JournalCreated/Updated/Deleted`` → ``broadcast_journal_event``
        - ``TagUpdated/Deleted`` → ``broadcast_tag_event``

        Args:
            event: The stream event to process
        """
        async with self._container() as request_container:
            task_queue = await request_container.get(TaskQueueService)

            if event.event_type in _JOURNAL_EVENT_TYPES:
                await task_queue.broadcast_journal_event(
                    event.event_type, event.event_data
                )
            elif event.event_type in _TAG_EVENT_TYPES:
                await task_queue.broadcast_tag_event(event.event_type, event.event_data)

        logger.info(
            "Google outbound consumer broadcasted event",
            event_id=event.event_id,
            event_type=event.event_type,
        )

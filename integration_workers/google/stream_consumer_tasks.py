"""
Google Worker Stream Consumer for Redis Streams.

Reads journal, tag, and contact domain events directly from the
pms:domain-events stream using the 'google-worker' consumer group.
Routes events to the existing process_journal_event, process_tag_event,
and process_contact_event worker functions, bypassing ARQ for event
fan-out.

This replaces the backend's GoogleOutboundConsumer which previously
enqueued ARQ jobs. The worker now consumes events directly from the
Redis Stream, as specified: "ARQ remains for long-running tasks
(sync jobs, webhook processing) but is no longer used for event fan-out."
"""

import asyncio
from typing import Any

import structlog
from core_shared.stream_client import StreamClient, StreamEvent, create_stream_redis
from core_shared.stream_consumer import EventRoute, StreamConsumer

from worker import process_contact_event, process_journal_event, process_tag_event

logger = structlog.get_logger()

# Journal event types that trigger outbound processing.
_JOURNAL_EVENT_TYPES = ("JournalCreated", "JournalUpdated", "JournalDeleted")

# Tag event types that trigger outbound processing.
_TAG_EVENT_TYPES = ("TagUpdated", "TagDeleted")

# Contact event types that trigger outbound push to Google.
# ``ContactMerged`` (ITER13-005 Phase 2) reconciles a same-service merge by
# deleting the source contact's orphaned remote Google record.
_CONTACT_EVENT_TYPES = (
    "ContactCreated",
    "ContactUpdated",
    "ContactDeleted",
    "ContactMerged",
)


class GoogleWorkerStreamConsumer(StreamConsumer):
    """Stream consumer for Google integration event processing.

    Listens to journal, tag, and contact domain events on the
    ``pms:domain-events`` stream using the ``google-worker`` consumer
    group. The declarative route table (see :meth:`_build_routes`) maps each
    consumed event type to ``process_journal_event``, ``process_tag_event``, or
    ``process_contact_event`` worker functions; the shared
    :class:`~core_shared.stream_consumer.StreamConsumer` runs the read/ack/retry
    loop and dispatches matched events. The route table is the single source of
    truth for the consumed-event set.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        session_factory: Any,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "google-worker-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Initialize the Google worker stream consumer.

        Args:
            stream_client: Redis Streams client
            session_factory: Async session factory for database operations
            stream_name: Name of the domain events stream
            consumer_name: Individual consumer name within the group
            batch_size: Maximum events to read per XREADGROUP call
            block_ms: Milliseconds to block waiting for new events
        """
        self._session_factory = session_factory
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="google-worker",
            consumer_name=consumer_name,
            batch_size=batch_size,
            block_ms=block_ms,
            routes=self._build_routes(),
        )

    def _build_routes(self) -> list[EventRoute]:
        """Declare the event-type → handler routes for this worker."""
        return [
            *(EventRoute(t, self._handle_journal) for t in _JOURNAL_EVENT_TYPES),
            *(EventRoute(t, self._handle_tag) for t in _TAG_EVENT_TYPES),
            *(EventRoute(t, self._handle_contact) for t in _CONTACT_EVENT_TYPES),
        ]

    def _build_ctx(self, event: StreamEvent) -> dict[str, Any]:
        """Build the minimal ARQ-compatible context dict for a worker function."""
        return {"session_factory": self._session_factory, "job_id": event.event_id}

    async def _handle_journal(self, event: StreamEvent) -> None:
        """Route a journal event to ``process_journal_event``."""
        await process_journal_event(
            ctx=self._build_ctx(event),
            event_type=event.event_type,
            event_data=event.event_data,
        )
        self._log_processed(event)

    async def _handle_tag(self, event: StreamEvent) -> None:
        """Route a tag event to ``process_tag_event``."""
        await process_tag_event(
            ctx=self._build_ctx(event),
            event_type=event.event_type,
            event_data=event.event_data,
        )
        self._log_processed(event)

    async def _handle_contact(self, event: StreamEvent) -> None:
        """Route a contact event to ``process_contact_event``."""
        await process_contact_event(
            ctx=self._build_ctx(event),
            event_type=event.event_type,
            event_data=event.event_data,
        )
        self._log_processed(event)

    def _log_processed(self, event: StreamEvent) -> None:
        logger.info(
            "Google worker processed event from stream",
            event_id=event.event_id,
            event_type=event.event_type,
        )


async def run_google_stream_consumer(
    session_factory: Any,
    redis_url: str,
    stream_name: str = "pms:domain-events",
) -> None:
    """Run the Google worker stream consumer loop.

    Creates a StreamClient and GoogleWorkerStreamConsumer, then starts
    the consumer loop. Designed to be launched as an asyncio.Task from
    the ARQ worker startup.

    Args:
        session_factory: Async session factory for database operations
        redis_url: Redis connection URL
        stream_name: Name of the domain events stream
    """
    redis_client = create_stream_redis(redis_url)
    stream_client = StreamClient(redis_client)

    consumer = GoogleWorkerStreamConsumer(
        stream_client=stream_client,
        session_factory=session_factory,
        stream_name=stream_name,
    )

    logger.info(
        "Starting Google worker stream consumer",
        stream=stream_name,
        group="google-worker",
    )

    try:
        await consumer.start()
    except asyncio.CancelledError:
        logger.info("Google worker stream consumer cancelled")
        raise
    finally:
        await redis_client.aclose()

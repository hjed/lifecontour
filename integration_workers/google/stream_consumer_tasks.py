"""
Google Worker Stream Consumer for Redis Streams.

Reads journal and tag domain events directly from the pms:domain-events
stream using the 'google-worker' consumer group. Routes events to the
existing process_journal_event and process_tag_event worker functions,
bypassing ARQ for event fan-out.

This replaces the backend's GoogleOutboundConsumer which previously
enqueued ARQ jobs. The worker now consumes events directly from the
Redis Stream, as specified: "ARQ remains for long-running tasks
(sync jobs, webhook processing) but is no longer used for event fan-out."
"""

import asyncio
from typing import Any

import structlog
from core_shared.stream_client import StreamClient, StreamEvent
from core_shared.stream_consumer import StreamConsumer

from worker import process_journal_event, process_tag_event

logger = structlog.get_logger()

# Journal event types that trigger outbound processing.
_JOURNAL_EVENT_TYPES = frozenset({"JournalCreated", "JournalUpdated", "JournalDeleted"})

# Tag event types that trigger outbound processing.
_TAG_EVENT_TYPES = frozenset({"TagUpdated", "TagDeleted"})

# Combined event type list for pattern matching (exact match).
_OUTBOUND_EVENT_TYPES: list[str] = sorted(_JOURNAL_EVENT_TYPES | _TAG_EVENT_TYPES)


class GoogleWorkerStreamConsumer(StreamConsumer):
    """Stream consumer for Google integration event processing.

    Listens to journal and tag domain events on the ``pms:domain-events``
    stream using the ``google-worker`` consumer group. Routes events
    directly to ``process_journal_event`` and ``process_tag_event``
    worker functions without ARQ enqueue.
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
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="google-worker",
            consumer_name=consumer_name,
            event_type_patterns=_OUTBOUND_EVENT_TYPES,
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._session_factory = session_factory

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process an event by routing to the appropriate worker function.

        Builds a minimal ARQ-compatible context dict and calls the
        worker function directly. The context includes the session_factory
        and uses the event_id as the job_id for logging consistency.

        Args:
            event: The stream event to process

        Raises:
            Exception: Any exception from the worker function propagates
                for the base class retry mechanism.
        """
        ctx = {
            "session_factory": self._session_factory,
            "job_id": event.event_id,
        }

        if event.event_type in _JOURNAL_EVENT_TYPES:
            await process_journal_event(
                ctx=ctx,
                event_type=event.event_type,
                event_data=event.event_data,
            )
        elif event.event_type in _TAG_EVENT_TYPES:
            await process_tag_event(
                ctx=ctx,
                event_type=event.event_type,
                event_data=event.event_data,
            )

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
    from redis.asyncio import Redis

    redis_client = Redis.from_url(redis_url)
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
        await redis_client.close()

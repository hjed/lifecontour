"""
Immich Worker Stream Consumer for Redis Streams.

Reads domain events from the pms:domain-events stream using the
'immich-worker' consumer group. Routes events to appropriate handler
functions for contact/album synchronisation.

In Phase 2 this is a placeholder that logs events. Actual sync
processing will be implemented in Phase 3 (ITER11-001-P3).
"""

import asyncio
from typing import Any

import structlog
from core_shared.stream_client import StreamClient, StreamEvent, create_stream_redis
from core_shared.stream_consumer import StreamConsumer

logger = structlog.get_logger(__name__)

# Event types this consumer is interested in.
# Phase 2: subscribe but only log. Phase 3+ will add real handlers.
_IMMICH_EVENT_TYPES: list[str] = [
    "ContactCreated",
    "ContactUpdated",
    "ContactBirthdayChanged",
]


class ImmichWorkerStreamConsumer(StreamConsumer):
    """Stream consumer for Immich integration event processing.

    Listens to contact and journal domain events on the
    ``pms:domain-events`` stream using the ``immich-worker`` consumer
    group. Routes events to appropriate handler functions.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        session_factory: Any,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "immich-worker-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Initialize the Immich worker stream consumer.

        Args:
            stream_client: Redis Streams client.
            session_factory: Async session factory for database operations.
            stream_name: Name of the domain events stream.
            consumer_name: Individual consumer name within the group.
            batch_size: Maximum events to read per XREADGROUP call.
            block_ms: Milliseconds to block waiting for new events.
        """
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="immich-worker",
            consumer_name=consumer_name,
            event_type_patterns=_IMMICH_EVENT_TYPES,
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._session_factory = session_factory

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process an event from the stream.

        Phase 2: Logs the event for observability.
        Phase 3+: Will route to sync handlers.
        """
        logger.info(
            "Immich worker received event from stream",
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
        )

        ctx = {
            "session_factory": self._session_factory,
            "job_id": event.event_id,
        }

        if event.event_type in (
            "ContactCreated",
            "ContactUpdated",
            "ContactBirthdayChanged",
        ):
            from worker import process_contact_event

            # Create a shallow copy to avoid mutating the original event data
            event_data = dict(event.event_data) if event.event_data else {}
            event_data["contact_id"] = event.aggregate_id
            await process_contact_event(ctx, event.event_type, event_data)


async def run_immich_stream_consumer(
    session_factory: Any,
    redis_url: str,
    stream_name: str = "pms:domain-events",
) -> None:
    """Run the Immich worker stream consumer loop.

    Args:
        session_factory: Async session factory for database operations.
        redis_url: Redis connection URL.
        stream_name: Name of the domain events stream.
    """
    redis_client = create_stream_redis(redis_url)
    stream_client = StreamClient(redis_client)

    consumer = ImmichWorkerStreamConsumer(
        stream_client=stream_client,
        session_factory=session_factory,
        stream_name=stream_name,
    )

    logger.info(
        "Starting Immich worker stream consumer",
        stream=stream_name,
        group="immich-worker",
    )

    try:
        await consumer.start()
    except asyncio.CancelledError:
        logger.info("Immich worker stream consumer cancelled")
        raise
    finally:
        await redis_client.aclose()

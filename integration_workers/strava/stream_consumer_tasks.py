"""
Strava Worker Stream Consumer for Redis Streams.

Reads domain events from the pms:domain-events stream using the
'strava-worker' consumer group. Routes events to appropriate handler
functions.

In Phase 3 this is a placeholder that logs events. Actual activity
processing will be implemented in ITER5-004.
"""

import asyncio
from typing import Any

import structlog
from core_shared.stream_client import StreamClient, StreamEvent
from core_shared.stream_consumer import StreamConsumer

logger = structlog.get_logger(__name__)

# Event type patterns this consumer is interested in
# Currently subscribed to strava-specific events (future use)
_STRAVA_EVENT_PATTERNS: list[str] = [
    "strava.",  # Prefix match for all strava domain events
]


class StravaWorkerStreamConsumer(StreamConsumer):
    """Stream consumer for Strava integration event processing.

    Listens to domain events on the ``pms:domain-events`` stream using
    the ``strava-worker`` consumer group. Routes events to appropriate
    handler functions.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        session_factory: Any,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "strava-worker-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Initialize the Strava worker stream consumer.

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
            group_name="strava-worker",
            consumer_name=consumer_name,
            event_type_patterns=_STRAVA_EVENT_PATTERNS,
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._session_factory = session_factory

    async def _handle_event(self, event: StreamEvent) -> None:
        """Handle a matched domain event.

        Args:
            event: The stream event to process.
        """
        logger.info(
            "Strava stream consumer received event (placeholder)",
            event_id=event.event_id,
            event_type=event.event_type,
        )
        # Actual event processing will be implemented in ITER5-004


async def run_strava_stream_consumer(
    session_factory: Any,
    redis_url: str,
    stream_name: str = "pms:domain-events",
) -> None:
    """Run the Strava worker stream consumer loop.

    Creates a StreamClient and StravaWorkerStreamConsumer, then starts
    the consumer loop. Designed to be launched as an asyncio.Task from
    the ARQ worker startup.

    Args:
        session_factory: Async session factory for database operations.
        redis_url: Redis connection URL.
        stream_name: Name of the domain events stream.
    """
    from redis.asyncio import Redis

    redis_client = Redis.from_url(redis_url)
    stream_client = StreamClient(redis_client)

    consumer = StravaWorkerStreamConsumer(
        stream_client=stream_client,
        session_factory=session_factory,
        stream_name=stream_name,
    )

    logger.info(
        "Starting Strava worker stream consumer",
        stream=stream_name,
        group="strava-worker",
    )

    try:
        await consumer.start()
    except asyncio.CancelledError:
        logger.info("Strava worker stream consumer cancelled")
        raise
    finally:
        await redis_client.aclose()

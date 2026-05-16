"""
Snipe-IT Worker Stream Consumer for Redis Streams.

Reads events from the pms:domain-events stream using the 'snipeit-worker' consumer group.
Currently listens for snipeit.webhook_received events, which will be processed in
subsequent phases.
"""

import asyncio
from typing import Any

import structlog
from core_shared.stream_client import StreamClient, StreamEvent
from core_shared.stream_consumer import StreamConsumer

logger = structlog.get_logger()

_SNIPEIT_EVENT_TYPES = frozenset({"snipeit.webhook_received"})


class SnipeItWorkerStreamConsumer(StreamConsumer):
    """Stream consumer for Snipe-IT integration event processing.

    Listens to Snipe-IT webhook events on the ``pms:domain-events`` stream
    using the ``snipeit-worker`` consumer group.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        session_factory: Any,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "snipeit-worker-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="snipeit-worker",
            consumer_name=consumer_name,
            event_type_patterns=list(_SNIPEIT_EVENT_TYPES),
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._session_factory = session_factory

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process an event from the stream.

        In this phase, we simply log that the event was received.
        Subsequent phases will implement the actual processing.
        """
        logger.info(
            "Snipe-IT worker processed event from stream",
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
        )


async def run_snipeit_stream_consumer(
    session_factory: Any,
    redis_url: str,
    stream_name: str = "pms:domain-events",
) -> None:
    """Run the Snipe-IT worker stream consumer loop."""
    from redis.asyncio import Redis  # type: ignore[import-untyped]

    redis_client = Redis.from_url(redis_url)
    stream_client = StreamClient(redis_client)

    consumer = SnipeItWorkerStreamConsumer(
        stream_client=stream_client,
        session_factory=session_factory,
        stream_name=stream_name,
    )

    logger.info(
        "Starting Snipe-IT worker stream consumer",
        stream=stream_name,
        group="snipeit-worker",
    )

    try:
        await consumer.start()
    except asyncio.CancelledError:
        logger.info("Snipe-IT worker stream consumer cancelled")
        raise
    finally:
        await redis_client.close()

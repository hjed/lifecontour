"""
Outbox Relay for publishing domain events to Redis Streams.

Reads unrelayed events from the outbox_events table and publishes
them to the Redis Stream, then marks them as relayed. Runs as a
background task alongside the legacy OutboxProcessor during
the migration phase.
"""

import asyncio

import structlog
from core_shared.stream_client import StreamClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.outbox_repository import OutboxEvent, OutboxRepository

logger = structlog.get_logger()


class OutboxRelay:
    """Relay process that publishes outbox events to a Redis Stream.

    This relay is the bridge between the transactional outbox (Postgres)
    and the Redis Streams event bus. It reads events that have not yet
    been relayed, publishes them to the stream, and marks them as relayed.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        stream_name: str,
        batch_size: int = 50,
    ) -> None:
        """Initialize the OutboxRelay.

        Args:
            stream_client: Redis Streams client for publishing events
            stream_name: Name of the target Redis Stream
            batch_size: Maximum number of events to relay per batch
        """
        self._stream_client = stream_client
        self._stream_name = stream_name
        self._batch_size = batch_size

    async def relay_batch(
        self,
        connection: AsyncConnection,
    ) -> int:
        """Relay a batch of unrelayed events to the Redis Stream.

        Reads events from the outbox where relayed_at IS NULL, publishes
        each to the stream, and marks them as relayed. Continues processing
        remaining events even if individual publishes fail.

        Args:
            connection: Async database connection

        Returns:
            Number of successfully relayed events
        """
        repository = OutboxRepository(connection)
        events = await repository.get_unrelayed_events(limit=self._batch_size)

        if not events:
            return 0

        relayed_count = 0
        for event in events:
            # Defensive idempotency check — skip if already relayed
            if event.relayed_at is not None:
                logger.debug(
                    "Skipping already-relayed event",
                    event_id=event.event_id,
                )
                continue

            try:
                await self._publish_event(event)
                await repository.mark_as_relayed(event.event_id)
                relayed_count += 1
            except Exception:
                logger.error(
                    "Failed to relay event to stream",
                    event_id=event.event_id,
                    event_type=event.event_type,
                    exc_info=True,
                )
                # Continue with next event — don't let one failure block the batch

        if relayed_count > 0:
            logger.info(
                "Relayed events to stream",
                relayed_count=relayed_count,
                total_events=len(events),
                stream=self._stream_name,
            )

        return relayed_count

    async def _publish_event(self, event: OutboxEvent) -> str:
        """Publish a single outbox event to the Redis Stream.

        Args:
            event: The outbox event to publish

        Returns:
            The stream message ID assigned by Redis
        """
        return await self._stream_client.publish(
            stream_name=self._stream_name,
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
            event_data=event.event_data,
            occurred_at=event.occurred_at.isoformat(),
        )


async def run_outbox_relay_loop(
    stream_client: StreamClient,
    stream_name: str = "pms:domain-events",
    batch_size: int = 50,
    interval_seconds: float = 5.0,
) -> None:
    """Run the outbox relay in a periodic loop.

    This function is designed to be launched as an asyncio.Task from
    the application lifespan. It follows the same pattern as
    run_outbox_processor_loop.

    Args:
        stream_client: Redis Streams client for publishing events
        stream_name: Name of the target Redis Stream
        batch_size: Maximum number of events to relay per batch
        interval_seconds: Seconds to wait between relay cycles
    """
    relay = OutboxRelay(
        stream_client=stream_client,
        stream_name=stream_name,
        batch_size=batch_size,
    )

    logger.info(
        "Starting outbox relay loop",
        stream=stream_name,
        batch_size=batch_size,
        interval_seconds=interval_seconds,
    )

    while True:
        try:
            engine = get_async_database_engine()
            async with engine.begin() as conn:
                await relay.relay_batch(conn)
        except asyncio.CancelledError:
            logger.info("Outbox relay loop cancelled")
            raise
        except Exception:
            logger.error("Error in outbox relay loop", exc_info=True)

        await asyncio.sleep(interval_seconds)

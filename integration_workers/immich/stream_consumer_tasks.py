"""
Immich Worker Stream Consumer for Redis Streams.

Reads domain events from the pms:domain-events stream using the
'immich-worker' consumer group. A declarative route table maps each consumed
contact event type to a handler; the shared ``StreamConsumer`` runs the
read/ack/retry loop and dispatches matched events to ``process_contact_event``.
"""

import asyncio
from typing import Any

import structlog
from core_shared.stream_client import StreamClient, StreamEvent, create_stream_redis
from core_shared.stream_consumer import EventRoute, StreamConsumer

logger = structlog.get_logger(__name__)

# Contact lifecycle events that carry a single contact via ``aggregate_id``; the
# consumer injects it as ``contact_id`` before dispatching to the handler.
_CONTACT_LIFECYCLE_EVENT_TYPES = (
    "ContactCreated",
    "ContactUpdated",
    "ContactBirthdayChanged",
)

# ``ContactMerged`` reconciles a same-service merge collision: because Immich
# exposes no person-delete, the worker unlinks the source's orphaned local
# reference rather than deleting a remote record. It carries no single
# ``contact_id`` (it reconciles a survivor/source pair via
# ``external_collisions``), so its payload is forwarded unchanged.
_CONTACT_MERGED_EVENT_TYPE = "ContactMerged"


class ImmichWorkerStreamConsumer(StreamConsumer):
    """Stream consumer for Immich integration event processing.

    Listens to contact domain events on the ``pms:domain-events`` stream using
    the ``immich-worker`` consumer group. The declarative route table (see
    :meth:`_build_routes`) maps each consumed event type to a handler; the shared
    :class:`~core_shared.stream_consumer.StreamConsumer` runs the read/ack/retry
    loop and dispatches matched events. The route table is the single source of
    truth for the consumed-event set.
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
        self._session_factory = session_factory
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="immich-worker",
            consumer_name=consumer_name,
            batch_size=batch_size,
            block_ms=block_ms,
            routes=self._build_routes(),
        )

    def _build_routes(self) -> list[EventRoute]:
        """Declare the event-type → handler routes for this worker."""
        return [
            *(
                EventRoute(t, self._handle_contact_lifecycle)
                for t in _CONTACT_LIFECYCLE_EVENT_TYPES
            ),
            EventRoute(_CONTACT_MERGED_EVENT_TYPE, self._handle_contact_merged),
        ]

    def _build_ctx(self, event: StreamEvent) -> dict[str, Any]:
        """Build the minimal ARQ-compatible context dict for the worker function."""
        return {"session_factory": self._session_factory, "job_id": event.event_id}

    async def _handle_contact_lifecycle(self, event: StreamEvent) -> None:
        """Dispatch a contact lifecycle event, injecting ``contact_id``."""
        self._log_received(event)
        from worker import process_contact_event

        # Shallow copy to avoid mutating the original event data.
        event_data = dict(event.event_data) if event.event_data else {}
        event_data["contact_id"] = event.aggregate_id
        await process_contact_event(
            self._build_ctx(event), event.event_type, event_data
        )

    async def _handle_contact_merged(self, event: StreamEvent) -> None:
        """Dispatch ``ContactMerged`` with its raw payload (no ``contact_id``)."""
        self._log_received(event)
        from worker import process_contact_event

        event_data = dict(event.event_data) if event.event_data else {}
        await process_contact_event(
            self._build_ctx(event), event.event_type, event_data
        )

    def _log_received(self, event: StreamEvent) -> None:
        logger.info(
            "Immich worker received event from stream",
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
        )


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

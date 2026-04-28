"""
Redis Streams client for the domain event bus.

Provides a thin wrapper around redis.asyncio for Stream operations
used by the OutboxRelay and StreamConsumer base class.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

import structlog
from redis.asyncio import Redis
from redis.exceptions import ResponseError

logger = structlog.get_logger()


@dataclass
class StreamEvent:
    """A domain event read from a Redis Stream.

    Attributes:
        message_id: Redis Stream message ID (e.g. "1234567890-0")
        event_id: Application-level unique event identifier
        event_type: Type of the domain event (e.g. "ContactCreated")
        aggregate_id: ID of the entity that produced the event
        event_data: Deserialized JSON payload of the event
        occurred_at: ISO 8601 timestamp string of when the event occurred
    """

    message_id: str
    event_id: str
    event_type: str
    aggregate_id: int
    event_data: dict[str, Any]
    occurred_at: str


@dataclass
class PendingEntry:
    """A pending entry from XPENDING.

    Attributes:
        message_id: Redis Stream message ID
        consumer: Name of the consumer that read the message
        idle_time_ms: Milliseconds since the message was last delivered
        delivery_count: Number of times the message has been delivered
    """

    message_id: str
    consumer: str
    idle_time_ms: int
    delivery_count: int


class StreamClient:
    """Thin wrapper around redis.asyncio.Redis for Stream operations.

    This client is designed to be shared across the backend and
    integration workers via the core_shared package.
    """

    def __init__(self, redis: Redis) -> None:
        """Initialize with an async Redis connection.

        Args:
            redis: An async Redis client instance
        """
        self._redis = redis

    async def publish(
        self,
        stream_name: str,
        event_id: str,
        event_type: str,
        aggregate_id: int,
        event_data: dict[str, Any],
        occurred_at: str,
    ) -> str:
        """Publish an event to a Redis Stream via XADD.

        Args:
            stream_name: Name of the Redis Stream
            event_id: Application-level unique event identifier
            event_type: Type of the domain event
            aggregate_id: ID of the entity that produced the event
            event_data: Event payload (will be JSON-serialized)
            occurred_at: ISO 8601 timestamp string

        Returns:
            The stream message ID assigned by Redis
        """
        fields = {
            "event_id": event_id,
            "event_type": event_type,
            "aggregate_id": str(aggregate_id),
            "event_data": json.dumps(event_data),
            "occurred_at": occurred_at,
        }

        message_id_raw = await self._redis.xadd(
            stream_name,
            cast(Any, fields),
        )

        if isinstance(message_id_raw, bytes):
            message_id = message_id_raw.decode()
        else:
            message_id = str(message_id_raw)

        logger.debug(
            "Published event to stream",
            stream=stream_name,
            event_id=event_id,
            event_type=event_type,
            message_id=message_id,
        )

        return message_id

    async def ensure_consumer_group(
        self,
        stream_name: str,
        group_name: str,
    ) -> None:
        """Create a consumer group, ignoring if it already exists.

        Uses XGROUP CREATE with mkstream=True so the stream is created
        if it doesn't exist yet.

        Args:
            stream_name: Name of the Redis Stream
            group_name: Name of the consumer group
        """
        try:
            await self._redis.xgroup_create(
                stream_name,
                group_name,
                id="0",
                mkstream=True,
            )
            logger.info(
                "Created consumer group",
                stream=stream_name,
                group=group_name,
            )
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(
                    "Consumer group already exists",
                    stream=stream_name,
                    group=group_name,
                )
            else:
                raise

    async def read_events(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[StreamEvent]:
        """Read new events from a stream using XREADGROUP.

        Args:
            stream_name: Name of the Redis Stream
            group_name: Consumer group name
            consumer_name: Individual consumer name within the group
            count: Maximum number of events to read
            block_ms: Milliseconds to block waiting for new events

        Returns:
            List of StreamEvent objects
        """
        result = await self._redis.xreadgroup(
            groupname=group_name,
            consumername=consumer_name,
            streams={stream_name: ">"},
            count=count,
            block=block_ms,
        )

        if result is None:
            return []

        return self._parse_stream_response(result)

    async def acknowledge(
        self,
        stream_name: str,
        group_name: str,
        message_id: str,
    ) -> None:
        """Acknowledge a message using XACK.

        Args:
            stream_name: Name of the Redis Stream
            group_name: Consumer group name
            message_id: Stream message ID to acknowledge
        """
        await self._redis.xack(stream_name, group_name, message_id)

    async def get_pending_entries(
        self,
        stream_name: str,
        group_name: str,
        min_idle_time_ms: int,
        count: int = 10,
    ) -> list[PendingEntry]:
        """Get pending entries that have exceeded the idle time threshold.

        Uses XPENDING with the IDLE filter to find messages that were
        delivered but not acknowledged.

        Args:
            stream_name: Name of the Redis Stream
            group_name: Consumer group name
            min_idle_time_ms: Minimum idle time in milliseconds
            count: Maximum number of entries to return

        Returns:
            List of PendingEntry objects
        """
        result = await self._redis.xpending_range(
            stream_name,
            group_name,
            min="-",
            max="+",
            count=count,
            idle=min_idle_time_ms,
        )

        entries = []
        for entry in result:
            msg_id = entry.get("message_id", b"")
            if isinstance(msg_id, bytes):
                msg_id = msg_id.decode()
            consumer = entry.get("consumer", b"")
            if isinstance(consumer, bytes):
                consumer = consumer.decode()

            entries.append(
                PendingEntry(
                    message_id=msg_id,
                    consumer=consumer,
                    idle_time_ms=entry.get("time_since_delivered", 0),
                    delivery_count=entry.get("times_delivered", 0),
                )
            )

        return entries

    async def claim_pending(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        min_idle_time_ms: int,
        message_ids: Sequence[str],
    ) -> list[StreamEvent]:
        """Claim pending messages using XCLAIM.

        Transfers ownership of pending messages to this consumer
        for retry processing.

        Args:
            stream_name: Name of the Redis Stream
            group_name: Consumer group name
            consumer_name: Consumer to claim messages for
            min_idle_time_ms: Minimum idle time for the claim
            message_ids: Sequence of message IDs to claim

        Returns:
            List of claimed StreamEvent objects
        """
        result = await self._redis.xclaim(
            stream_name,
            group_name,
            consumer_name,
            min_idle_time=min_idle_time_ms,
            message_ids=list(message_ids),
        )

        events = []
        for msg_id, fields in result:
            events.append(self._parse_message(msg_id, fields))

        return events

    def _parse_stream_response(self, response: list[Any]) -> list[StreamEvent]:
        """Parse the raw XREADGROUP response into StreamEvent objects."""
        events = []
        for _stream_name, messages in response:
            for msg_id, fields in messages:
                events.append(self._parse_message(msg_id, fields))
        return events

    def _parse_message(
        self, msg_id: bytes | str, fields: dict[Any, Any]
    ) -> StreamEvent:
        """Parse a single stream message into a StreamEvent."""

        def _decode(value: bytes | str) -> str:
            return value.decode() if isinstance(value, bytes) else str(value)

        def _get_field(field_name: str) -> str:
            """Get a field value, trying both bytes and str keys."""
            value = fields.get(field_name.encode(), fields.get(field_name, ""))
            return _decode(value)

        decoded_msg_id = _decode(msg_id)

        event_data_raw = _get_field("event_data") or "{}"
        aggregate_id_raw = _get_field("aggregate_id") or "0"

        return StreamEvent(
            message_id=decoded_msg_id,
            event_id=_get_field("event_id"),
            event_type=_get_field("event_type"),
            aggregate_id=int(aggregate_id_raw),
            event_data=json.loads(event_data_raw),
            occurred_at=_get_field("occurred_at"),
        )

"""
Base StreamConsumer class for Redis Streams consumer groups.

Provides abstract consumer with XREADGROUP, event filtering by type pattern,
XACK acknowledgement, and retry logic via XPENDING + XCLAIM.
"""

import asyncio
from abc import ABC, abstractmethod

import structlog

from core_shared.stream_client import PendingEntry, StreamClient, StreamEvent

logger = structlog.get_logger()


class StreamConsumer(ABC):
    """Abstract base class for Redis Streams consumer groups.

    Subclasses implement ``_handle_event`` for actual event processing.
    The base class manages consumer group creation, event filtering by
    type patterns, acknowledgement, and retry of stale pending entries.

    Event type matching supports two modes:
    - **Prefix match**: patterns ending with ``.`` (e.g. ``"contact."``)
      match any event type starting with that prefix.
    - **Exact match**: patterns without a trailing ``.`` match exactly.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        event_type_patterns: list[str],
        batch_size: int = 10,
        block_ms: int = 5000,
        retry_min_idle_ms: int = 60000,
        retry_batch_size: int = 10,
        max_delivery_count: int = 5,
    ) -> None:
        """Initialize the consumer.

        Args:
            stream_client: Redis Streams client
            stream_name: Name of the Redis Stream to consume from
            group_name: Consumer group name (e.g. "search-indexer")
            consumer_name: Individual consumer name within the group
            event_type_patterns: List of event type patterns to process
            batch_size: Maximum events to read per XREADGROUP call
            block_ms: Milliseconds to block waiting for new events
            retry_min_idle_ms: Minimum idle time (ms) before retrying pending entries
            retry_batch_size: Maximum pending entries to claim per retry cycle
            max_delivery_count: Maximum times an event can be delivered before dead-lettering
        """
        self._stream_client = stream_client
        self._stream_name = stream_name
        self._group_name = group_name
        self._consumer_name = consumer_name
        self._event_type_patterns = event_type_patterns
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._retry_min_idle_ms = retry_min_idle_ms
        self._retry_batch_size = retry_batch_size
        self._max_delivery_count = max_delivery_count
        self._running = True

    async def start(self) -> None:
        """Create consumer group and begin the read loop.

        The loop alternates between reading new events and retrying
        stale pending entries until ``stop()`` is called or the task
        is cancelled.
        """
        await self._stream_client.ensure_consumer_group(
            self._stream_name, self._group_name
        )

        logger.info(
            "Stream consumer started",
            group=self._group_name,
            consumer=self._consumer_name,
            patterns=self._event_type_patterns,
        )

        while self._running:
            try:
                await self._process_batch()
                await self._retry_pending()
            except asyncio.CancelledError:
                logger.info(
                    "Stream consumer cancelled",
                    group=self._group_name,
                    consumer=self._consumer_name,
                )
                raise
            except Exception:
                logger.error(
                    "Error in stream consumer loop",
                    group=self._group_name,
                    consumer=self._consumer_name,
                    exc_info=True,
                )
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal the consumer to stop reading."""
        self._running = False

    @abstractmethod
    async def _handle_event(self, event: StreamEvent) -> None:
        """Process a single matched event.

        Subclasses implement this method. If the method raises an exception,
        the event will **not** be acknowledged and will remain in the
        pending entries list for retry.

        Args:
            event: The stream event to process
        """

    async def _handle_dead_letter(
        self, event: StreamEvent, pending_entry: PendingEntry
    ) -> None:
        """Handle a dead-letter event that has exceeded max retries.

        Default implementation ACKs the message and logs an error.
        Subclasses can override to persist to a DLQ database.
        """
        logger.error(
            "Event exceeded max delivery count, dead-lettering",
            event_id=event.event_id,
            event_type=event.event_type,
            message_id=event.message_id,
            group=self._group_name,
            delivery_count=pending_entry.delivery_count,
        )
        await self._stream_client.acknowledge(
            self._stream_name, self._group_name, event.message_id
        )

    async def _process_batch(self) -> int:
        """Read a batch of events, filter by type patterns, process or ack-skip.

        Returns:
            Number of events processed (including skipped non-matching events)
        """
        events = await self._stream_client.read_events(
            stream_name=self._stream_name,
            group_name=self._group_name,
            consumer_name=self._consumer_name,
            count=self._batch_size,
            block_ms=self._block_ms,
        )

        if not events:
            return 0

        processed = 0
        for event in events:
            if self._matches_event_type(event.event_type):
                try:
                    await self._handle_event(event)
                    await self._stream_client.acknowledge(
                        self._stream_name, self._group_name, event.message_id
                    )
                except Exception:
                    logger.error(
                        "Failed to handle event, leaving pending for retry",
                        event_id=event.event_id,
                        event_type=event.event_type,
                        message_id=event.message_id,
                        group=self._group_name,
                        exc_info=True,
                    )
            else:
                # Non-matching event — acknowledge immediately (skip)
                await self._stream_client.acknowledge(
                    self._stream_name, self._group_name, event.message_id
                )
            processed += 1

        return processed

    async def _retry_pending(self) -> int:
        """Claim and retry stale pending entries.

        Uses XPENDING to find entries that have exceeded the idle time
        threshold, claims them with XCLAIM, and reprocesses.

        Returns:
            Number of events retried
        """
        pending = await self._stream_client.get_pending_entries(
            stream_name=self._stream_name,
            group_name=self._group_name,
            min_idle_time_ms=self._retry_min_idle_ms,
            count=self._retry_batch_size,
        )

        if not pending:
            return 0

        pending_by_id = {entry.message_id: entry for entry in pending}
        message_ids = list(pending_by_id.keys())

        claimed_events = await self._stream_client.claim_pending(
            stream_name=self._stream_name,
            group_name=self._group_name,
            consumer_name=self._consumer_name,
            min_idle_time_ms=self._retry_min_idle_ms,
            message_ids=message_ids,
        )

        retried = 0
        for event in claimed_events:
            pending_entry = pending_by_id.get(event.message_id)

            if (
                pending_entry
                and pending_entry.delivery_count >= self._max_delivery_count
            ):
                await self._handle_dead_letter(event, pending_entry)
                continue

            if self._matches_event_type(event.event_type):
                try:
                    await self._handle_event(event)
                    await self._stream_client.acknowledge(
                        self._stream_name, self._group_name, event.message_id
                    )
                    retried += 1
                except Exception:
                    logger.error(
                        "Failed to retry event, leaving pending",
                        event_id=event.event_id,
                        event_type=event.event_type,
                        message_id=event.message_id,
                        group=self._group_name,
                        exc_info=True,
                    )
            else:
                await self._stream_client.acknowledge(
                    self._stream_name, self._group_name, event.message_id
                )
                retried += 1

        if retried > 0:
            logger.info(
                "Retried pending events",
                retried_count=retried,
                group=self._group_name,
                consumer=self._consumer_name,
            )

        return retried

    def _matches_event_type(self, event_type: str) -> bool:
        """Check if event_type matches any of the consumer's patterns.

        Supports two modes:
        - Prefix match: patterns ending with "." match any event_type
          that starts with the pattern (e.g. "contact." matches
          "contact.created").
        - Exact match: patterns without trailing "." must match exactly.

        Args:
            event_type: The event type string to check

        Returns:
            True if the event type matches any pattern
        """
        for pattern in self._event_type_patterns:
            if pattern.endswith("."):
                if event_type.startswith(pattern):
                    return True
            else:
                if event_type == pattern:
                    return True
        return False

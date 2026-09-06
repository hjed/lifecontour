"""
Base StreamConsumer class for Redis Streams consumer groups.

Provides a consumer with XREADGROUP, event filtering by type pattern,
XACK acknowledgement, and retry logic via XPENDING + XCLAIM.

A consumer declares either a **route table** (``routes``) — a list of
:class:`EventRoute` mapping an event-type pattern to a handler coroutine, with
the shared infrastructure running the loop/ack/retry and dispatching matched
events — or overrides ``_handle_event`` directly (the legacy path, retained for
backward compatibility until workers migrate to routes).
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import structlog

from core_shared.stream_client import PendingEntry, StreamClient, StreamEvent

logger = structlog.get_logger()

# A route handler receives a single matched event. Raising leaves the event
# unacknowledged so the base class retries it via the pending-entries path.
EventHandler = Callable[[StreamEvent], Awaitable[None]]


def event_type_matches(pattern: str, event_type: str) -> bool:
    """Return whether ``event_type`` matches a single pattern.

    Supports two modes:
    - **Prefix match**: patterns ending with ``"."`` (e.g. ``"contact."``)
      match any ``event_type`` starting with the pattern.
    - **Exact match**: patterns without a trailing ``"."`` must match exactly.
    """
    if pattern.endswith("."):
        return event_type.startswith(pattern)
    return event_type == pattern


@dataclass(frozen=True)
class EventRoute:
    """A declarative route: an event-type pattern mapped to a handler.

    Attributes:
        pattern: Event-type pattern using the prefix/exact semantics of
            :func:`event_type_matches` (e.g. ``"strava."`` or ``"ContactCreated"``).
        handler: Coroutine invoked with the matched :class:`StreamEvent`.
    """

    pattern: str
    handler: EventHandler


class StreamConsumer:
    """Base class for Redis Streams consumer groups.

    The base class manages consumer group creation, event filtering by type
    patterns, acknowledgement, and retry of stale pending entries.

    Workers declare a **route table** via ``routes`` (an :class:`EventRoute`
    list); the shared :meth:`_handle_event` dispatches each matched event to the
    first route whose pattern matches. Alternatively, subclasses may override
    :meth:`_handle_event` directly (the legacy path) and pass
    ``event_type_patterns`` instead.

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
        event_type_patterns: list[str] | None = None,
        batch_size: int = 10,
        block_ms: int = 5000,
        retry_min_idle_ms: int = 60000,
        retry_batch_size: int = 10,
        max_delivery_count: int = 5,
        *,
        routes: Sequence[EventRoute] | None = None,
        group_start_id: str = "0",
    ) -> None:
        """Initialize the consumer.

        Provide either ``routes`` (declarative dispatch via :meth:`_handle_event`)
        or ``event_type_patterns`` (with a ``_handle_event`` override). When
        ``routes`` are given and ``event_type_patterns`` is omitted, the consumed
        patterns are derived from the route table, so the route table is the
        single source of truth for the consumed-event set.

        ``routes`` is keyword-only and appended after the original parameters, so
        the positional argument order is unchanged from before route support was
        added (existing positional and keyword callers are unaffected).

        Args:
            stream_client: Redis Streams client
            stream_name: Name of the Redis Stream to consume from
            group_name: Consumer group name (e.g. "search-indexer")
            consumer_name: Individual consumer name within the group
            event_type_patterns: List of event type patterns to process. Optional
                when ``routes`` are supplied (derived from the route patterns).
            batch_size: Maximum events to read per XREADGROUP call
            block_ms: Milliseconds to block waiting for new events
            retry_min_idle_ms: Minimum idle time (ms) before retrying pending entries
            retry_batch_size: Maximum pending entries to claim per retry cycle
            max_delivery_count: Maximum times an event can be delivered before dead-lettering
            routes: Declarative route table mapping patterns to handlers (keyword-only).
            group_start_id: Where the consumer group begins reading **when it is
                first created** (keyword-only). ``"0"`` replays everything the
                stream still holds, which is what a projection wants; ``"$"``
                starts at the next event published, which is what a group added
                to a running system wants when replaying an untrimmed stream
                would do more harm than missing a deploy window's events. It has
                no effect once the group exists.

        Raises:
            ValueError: If neither ``routes`` nor ``event_type_patterns`` is given;
                if both are given (the combination is ambiguous — the filter set and
                the dispatch set could diverge and silently drop events); or if
                ``event_type_patterns`` is given without ``routes`` and ``_handle_event``
                is not overridden (a misconfiguration that would otherwise only surface
                when the first event is processed).
        """
        if routes is not None and event_type_patterns is not None:
            raise ValueError(
                "StreamConsumer accepts 'routes' or 'event_type_patterns', not both; "
                "with 'routes' the consumed patterns are derived from the route table"
            )

        self._routes: list[EventRoute] = list(routes) if routes is not None else []
        if event_type_patterns is None:
            if not self._routes:
                raise ValueError(
                    "StreamConsumer requires either 'routes' or 'event_type_patterns'"
                )
            event_type_patterns = [route.pattern for route in self._routes]
        elif (
            not self._routes
            and type(self)._handle_event is StreamConsumer._handle_event
        ):
            # event_type_patterns supplied, but no routes and no _handle_event
            # override — fail fast rather than acking-then-raising at the first
            # event (which would leave messages pending until dead-lettering).
            raise ValueError(
                "StreamConsumer requires 'routes' or a '_handle_event' override; "
                "'event_type_patterns' alone has no handler to dispatch to"
            )

        self._stream_client = stream_client
        self._stream_name = stream_name
        self._group_name = group_name
        self._group_start_id = group_start_id
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
            self._stream_name, self._group_name, start_id=self._group_start_id
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

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process a single matched event.

        The default implementation dispatches to the first :class:`EventRoute`
        whose pattern matches ``event.event_type``. Subclasses may override this
        method instead of declaring ``routes`` (the legacy path). If the handler
        (or override) raises, the event is **not** acknowledged and remains in the
        pending entries list for retry.

        Args:
            event: The stream event to process

        Raises:
            NotImplementedError: If the consumer declares no routes and this
                method is not overridden.
        """
        if not self._routes:
            raise NotImplementedError(
                "StreamConsumer must declare 'routes' or override '_handle_event'"
            )
        route = self._match_route(event.event_type)
        if route is None:
            # Event passed the pattern filter but matches no specific route.
            # With routes-derived patterns this is unreachable; log and skip so
            # the caller acknowledges it rather than leaving it pending.
            logger.debug(
                "No route matched event, skipping",
                event_type=event.event_type,
                event_id=event.event_id,
                group=self._group_name,
            )
            return
        await route.handler(event)

    def _match_route(self, event_type: str) -> EventRoute | None:
        """Return the first route whose pattern matches ``event_type``."""
        for route in self._routes:
            if event_type_matches(route.pattern, event_type):
                return route
        return None

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
                    from opentelemetry import trace
                    from opentelemetry.propagate import extract

                    tracer = trace.get_tracer(__name__)
                    ctx = extract(event.trace_context) if event.trace_context else None
                    with tracer.start_as_current_span(
                        f"process_stream_event {event.event_type}",
                        context=ctx,
                        attributes={
                            "messaging.message_id": event.message_id,
                            "messaging.system": "redis_streams",
                            "messaging.destination.name": self._stream_name,
                            "messaging.operation": "process",
                        },
                    ):
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
                    from opentelemetry import trace
                    from opentelemetry.propagate import extract

                    tracer = trace.get_tracer(__name__)
                    ctx = extract(event.trace_context) if event.trace_context else None
                    with tracer.start_as_current_span(
                        f"retry_stream_event {event.event_type}",
                        context=ctx,
                        attributes={
                            "messaging.message_id": event.message_id,
                            "messaging.system": "redis_streams",
                            "messaging.destination.name": self._stream_name,
                            "messaging.operation": "process",
                        },
                    ):
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
        return any(
            event_type_matches(pattern, event_type)
            for pattern in self._event_type_patterns
        )

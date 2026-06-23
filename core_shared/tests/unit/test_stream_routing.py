"""Unit tests for the declarative route-registration convention on StreamConsumer.

ITER14-004 Phase 1 adds a declarative route table (event-type pattern -> handler)
to ``core_shared``'s :class:`StreamConsumer`. The shared infrastructure runs the
``XREADGROUP``/ack/retry loop and dispatches matched events to the registered
handler; unmatched events are acked immediately. The existing ``_handle_event``
subclass-override path remains supported (backward compatible) until workers migrate.

These cover the worker-agnostic mechanism in isolation with a mocked stream client.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core_shared.stream_client import PendingEntry, StreamClient, StreamEvent
from core_shared.stream_consumer import (
    EventRoute,
    StreamConsumer,
    event_type_matches,
)

STREAM_NAME = "pms:domain-events"
GROUP_NAME = "test-group"
CONSUMER_NAME = "test-consumer-1"


def _make_stream_client() -> MagicMock:
    """A mocked StreamClient with all async methods stubbed and idle by default."""
    client = MagicMock(spec=StreamClient)
    client.ensure_consumer_group = AsyncMock()
    client.read_events = AsyncMock(return_value=[])
    client.acknowledge = AsyncMock()
    client.get_pending_entries = AsyncMock(return_value=[])
    client.claim_pending = AsyncMock(return_value=[])
    return client


def _make_event(
    *,
    event_type: str,
    message_id: str = "1-0",
    event_id: str = "evt-1",
    aggregate_id: int = 42,
) -> StreamEvent:
    return StreamEvent(
        message_id=message_id,
        event_id=event_id,
        event_type=event_type,
        aggregate_id=aggregate_id,
        event_data={"contact_id": aggregate_id},
        occurred_at="2024-01-01T12:00:00Z",
    )


def _routed_consumer(
    stream_client: MagicMock,
    routes: list[EventRoute],
    retry_min_idle_ms: int = 60000,
) -> StreamConsumer:
    return StreamConsumer(
        stream_client=stream_client,
        stream_name=STREAM_NAME,
        group_name=GROUP_NAME,
        consumer_name=CONSUMER_NAME,
        routes=routes,
        retry_min_idle_ms=retry_min_idle_ms,
    )


class TestEventTypeMatches:
    """The shared prefix/exact matcher used by both pattern filtering and routing."""

    @pytest.mark.parametrize(
        ("pattern", "event_type", "expected"),
        [
            ("ContactCreated", "ContactCreated", True),
            ("ContactCreated", "ContactCreatedExtra", False),
            ("ContactCreated", "Contact", False),
            ("contact.", "contact.created", True),
            ("contact.", "contact.", True),
            ("contact.", "contactcreated", False),
            ("strava.", "strava.activity.created", True),
            ("strava.", "snipeit.webhook_received", False),
        ],
    )
    def test_prefix_and_exact_matching(
        self, pattern: str, event_type: str, expected: bool
    ) -> None:
        assert event_type_matches(pattern, event_type) is expected


class TestRouteDispatch:
    """A configured route dispatches matched events to the right handler."""

    @pytest.mark.asyncio
    async def test_exact_pattern_routes_to_handler(self) -> None:
        """An exact pattern dispatches the matching event to its handler."""
        client = _make_stream_client()
        handler = AsyncMock()
        consumer = _routed_consumer(client, [EventRoute("ContactCreated", handler)])

        event = _make_event(event_type="ContactCreated")
        await consumer._handle_event(event)

        handler.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_prefix_pattern_routes_to_handler(self) -> None:
        """A prefix pattern dispatches any event under that prefix to its handler."""
        client = _make_stream_client()
        handler = AsyncMock()
        consumer = _routed_consumer(client, [EventRoute("strava.", handler)])

        event = _make_event(event_type="strava.activity.created")
        await consumer._handle_event(event)

        handler.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_first_matching_route_wins(self) -> None:
        """When multiple routes match, the first declared route handles the event."""
        client = _make_stream_client()
        first = AsyncMock()
        second = AsyncMock()
        consumer = _routed_consumer(
            client,
            [
                EventRoute("strava.", first),
                EventRoute("strava.activity.created", second),
            ],
        )

        event = _make_event(event_type="strava.activity.created")
        await consumer._handle_event(event)

        first.assert_awaited_once_with(event)
        second.assert_not_awaited()

    def test_routes_derive_event_type_patterns(self) -> None:
        """The consumed-event set is the route table's patterns when not given."""
        client = _make_stream_client()
        consumer = _routed_consumer(
            client,
            [
                EventRoute("ContactCreated", AsyncMock()),
                EventRoute("strava.", AsyncMock()),
            ],
        )
        assert consumer._event_type_patterns == ["ContactCreated", "strava."]


class TestProcessBatchDispatch:
    """End-to-end dispatch + ack through the shared read loop (mocked client)."""

    @pytest.mark.asyncio
    async def test_matched_event_dispatched_and_acked(self) -> None:
        """A matched event invokes its handler once and is then acknowledged."""
        client = _make_stream_client()
        handler = AsyncMock()
        consumer = _routed_consumer(client, [EventRoute("ContactCreated", handler)])

        event = _make_event(event_type="ContactCreated", message_id="55-0")
        client.read_events.return_value = [event]

        processed = await consumer._process_batch()

        assert processed == 1
        handler.assert_awaited_once_with(event)
        client.acknowledge.assert_awaited_once_with(STREAM_NAME, GROUP_NAME, "55-0")

    @pytest.mark.asyncio
    async def test_unmatched_event_acked_immediately(self) -> None:
        """An event matching no route is not dispatched and is acked immediately."""
        client = _make_stream_client()
        handler = AsyncMock()
        consumer = _routed_consumer(client, [EventRoute("ContactCreated", handler)])

        event = _make_event(event_type="JournalCreated", message_id="77-0")
        client.read_events.return_value = [event]

        processed = await consumer._process_batch()

        assert processed == 1
        handler.assert_not_awaited()
        client.acknowledge.assert_awaited_once_with(STREAM_NAME, GROUP_NAME, "77-0")

    @pytest.mark.asyncio
    async def test_failing_handler_leaves_event_pending(self) -> None:
        """A handler that raises leaves the event unacked for later retry."""
        client = _make_stream_client()
        handler = AsyncMock(side_effect=RuntimeError("boom"))
        consumer = _routed_consumer(client, [EventRoute("ContactCreated", handler)])

        event = _make_event(event_type="ContactCreated", message_id="88-0")
        client.read_events.return_value = [event]

        processed = await consumer._process_batch()

        assert processed == 1
        handler.assert_awaited_once_with(event)
        client.acknowledge.assert_not_awaited()


class TestRetryDispatch:
    """Retry-on-failure via pending entries is preserved for routed consumers."""

    @pytest.mark.asyncio
    async def test_retry_pending_redispatches_and_acks(self) -> None:
        """A reclaimed pending entry is re-dispatched to its handler and acked."""
        client = _make_stream_client()
        handler = AsyncMock()
        consumer = _routed_consumer(
            client,
            [EventRoute("ContactCreated", handler)],
            retry_min_idle_ms=0,
        )

        event = _make_event(event_type="ContactCreated", message_id="99-0")
        client.get_pending_entries.return_value = [
            PendingEntry(
                message_id="99-0",
                consumer=CONSUMER_NAME,
                idle_time_ms=120000,
                delivery_count=1,
            )
        ]
        client.claim_pending.return_value = [event]

        retried = await consumer._retry_pending()

        assert retried == 1
        handler.assert_awaited_once_with(event)
        client.acknowledge.assert_awaited_once_with(STREAM_NAME, GROUP_NAME, "99-0")


class _LegacyConsumer(StreamConsumer):
    """A subclass using the legacy ``_handle_event`` override path (no routes)."""

    def __init__(self, stream_client: MagicMock) -> None:
        super().__init__(
            stream_client=stream_client,
            stream_name=STREAM_NAME,
            group_name=GROUP_NAME,
            consumer_name=CONSUMER_NAME,
            event_type_patterns=["ContactCreated"],
        )
        self.handled: list[StreamEvent] = []

    async def _handle_event(self, event: StreamEvent) -> None:
        self.handled.append(event)


class TestBackwardCompatibility:
    """The pre-existing override path keeps working unchanged."""

    @pytest.mark.asyncio
    async def test_subclass_override_still_dispatches(self) -> None:
        """A subclass overriding _handle_event processes and acks matched events."""
        client = _make_stream_client()
        consumer = _LegacyConsumer(client)

        event = _make_event(event_type="ContactCreated", message_id="11-0")
        client.read_events.return_value = [event]

        await consumer._process_batch()

        assert [e.message_id for e in consumer.handled] == ["11-0"]
        client.acknowledge.assert_awaited_once_with(STREAM_NAME, GROUP_NAME, "11-0")

    def test_legacy_patterns_only_construction(self) -> None:
        """Passing only event_type_patterns preserves the existing matcher behaviour."""
        client = _make_stream_client()
        consumer = _LegacyConsumer(client)
        assert consumer._matches_event_type("ContactCreated") is True
        assert consumer._matches_event_type("JournalCreated") is False

    @pytest.mark.asyncio
    async def test_base_without_routes_or_override_raises(self) -> None:
        """A base consumer with neither routes nor override raises on dispatch."""
        client = _make_stream_client()
        consumer = StreamConsumer(
            stream_client=client,
            stream_name=STREAM_NAME,
            group_name=GROUP_NAME,
            consumer_name=CONSUMER_NAME,
            event_type_patterns=["ContactCreated"],
        )
        with pytest.raises(NotImplementedError):
            await consumer._handle_event(_make_event(event_type="ContactCreated"))

    def test_construction_requires_routes_or_patterns(self) -> None:
        """Constructing with neither routes nor patterns is a configuration error."""
        client = _make_stream_client()
        with pytest.raises(ValueError):
            StreamConsumer(
                stream_client=client,
                stream_name=STREAM_NAME,
                group_name=GROUP_NAME,
                consumer_name=CONSUMER_NAME,
            )


class TestExports:
    """The route-registration surface is exported from the package root."""

    def test_public_exports(self) -> None:
        import core_shared

        assert core_shared.EventRoute is EventRoute
        assert core_shared.StreamConsumer is StreamConsumer
        assert core_shared.StreamEvent is StreamEvent
        for name in ("EventRoute", "StreamConsumer", "StreamEvent"):
            assert name in core_shared.__all__

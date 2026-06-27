"""Unit tests for the StravaWorkerStreamConsumer declarative route table.

ITER14-004 Phase 3: the consumer declares an ``EventRoute`` table instead of
overriding ``_handle_event``. These tests assert the route table preserves the
``strava.`` prefix match, dispatches a matched event to its handler, and acks
unmatched events without dispatch.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.stream_client import StreamClient, StreamEvent

from stream_consumer_tasks import StravaWorkerStreamConsumer


def _make_stream_event(event_type: str) -> StreamEvent:
    """Create a minimal StreamEvent for the given type."""
    return StreamEvent(
        message_id="1-0",
        event_id="evt-1",
        event_type=event_type,
        aggregate_id=1,
        event_data={"object_id": 1},
        occurred_at="2024-06-15T10:30:00+00:00",
    )


@pytest.fixture
def consumer() -> StravaWorkerStreamConsumer:
    """Create a StravaWorkerStreamConsumer with mock dependencies."""
    return StravaWorkerStreamConsumer(
        stream_client=MagicMock(spec=StreamClient),
        session_factory=MagicMock(),
        stream_name="pms:domain-events",
    )


class TestStravaWorkerRouteTable:
    """The consumer declares its consumed events via a route table."""

    def test_route_table_covers_exact_consumed_event_set(
        self, consumer: StravaWorkerStreamConsumer
    ) -> None:
        """Route patterns equal the documented consumed-event set (regression).

        Guards the spec requirement that the migrated consumer's consumed-event
        set is unchanged: the single ``strava.`` prefix route.
        """
        patterns = {route.pattern for route in consumer._routes}
        assert patterns == {"strava."}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event_type",
        ["strava.activity.created", "strava.activity.updated", "strava.deauthorized"],
    )
    async def test_strava_prefix_event_dispatched_to_handler(
        self, consumer: StravaWorkerStreamConsumer, event_type: str
    ) -> None:
        """Any ``strava.``-prefixed event dispatches to the strava handler."""
        consumer._handle_strava_event = AsyncMock()  # type: ignore[method-assign]
        consumer._routes = consumer._build_routes()

        await consumer._handle_event(_make_stream_event(event_type))

        consumer._handle_strava_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unmatched_event_acked_without_dispatch(
        self, consumer: StravaWorkerStreamConsumer
    ) -> None:
        """A non-``strava.`` event is acknowledged and no handler is invoked."""
        mock_client: Any = consumer._stream_client
        mock_client.read_events = AsyncMock(
            return_value=[_make_stream_event("ContactCreated")]
        )
        mock_client.acknowledge = AsyncMock()
        consumer._handle_strava_event = AsyncMock()  # type: ignore[method-assign]

        processed = await consumer._process_batch()

        assert processed == 1
        mock_client.acknowledge.assert_awaited_once()
        consumer._handle_strava_event.assert_not_awaited()

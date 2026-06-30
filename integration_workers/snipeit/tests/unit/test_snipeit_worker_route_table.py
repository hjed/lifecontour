"""Unit tests for the SnipeItWorkerStreamConsumer declarative route table.

ITER14-004 Phase 3: the consumer declares an ``EventRoute`` table instead of
overriding ``_handle_event``. These tests assert the route table maps the
expected event types to the right handlers, the consumed-event set is unchanged,
and unmatched events are acknowledged without dispatch.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.stream_client import StreamEvent

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/test"
    )
if "ENCRYPTION_KEY" not in os.environ:
    os.environ["ENCRYPTION_KEY"] = "testkey"

from stream_consumer_tasks import SnipeItWorkerStreamConsumer


def _make_stream_event(event_type: str) -> StreamEvent:
    """Create a minimal StreamEvent for the given type."""
    return StreamEvent(
        message_id="1-0",
        event_id="evt-1",
        event_type=event_type,
        aggregate_id=1,
        event_data={"item": {"id": 1}},
        occurred_at="2024-06-15T10:30:00+00:00",
    )


@pytest.fixture
def consumer() -> SnipeItWorkerStreamConsumer:
    """Return a configured SnipeItWorkerStreamConsumer with mock dependencies."""
    return SnipeItWorkerStreamConsumer(
        stream_client=MagicMock(),
        session_factory=MagicMock(),
    )


class TestSnipeItWorkerRouteTable:
    """The consumer declares its consumed events via a route table."""

    def test_route_table_covers_exact_consumed_event_set(
        self, consumer: SnipeItWorkerStreamConsumer
    ) -> None:
        """Route patterns equal the documented consumed-event set (regression)."""
        patterns = {route.pattern for route in consumer._routes}
        assert patterns == {
            "snipeit.webhook_received",
            "GearItemUpdated",
            "JournalCreated",
            "JournalUpdated",
            "JournalDeleted",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("event_type", "expected_handler"),
        [
            ("GearItemUpdated", "_handle_gear_item_updated"),
            ("JournalCreated", "_handle_journal_maintenance_event"),
            ("JournalUpdated", "_handle_journal_maintenance_event"),
            ("JournalDeleted", "_handle_journal_deleted"),
            ("snipeit.webhook_received", "_handle_webhook_received"),
        ],
    )
    async def test_route_table_maps_event_type_to_correct_handler(
        self,
        consumer: SnipeItWorkerStreamConsumer,
        event_type: str,
        expected_handler: str,
    ) -> None:
        """Each event type dispatches to its expected handler method only."""
        handler_names = [
            "_handle_gear_item_updated",
            "_handle_journal_maintenance_event",
            "_handle_journal_deleted",
            "_handle_webhook_received",
        ]
        mocks = {name: AsyncMock() for name in handler_names}
        for name, mock in mocks.items():
            setattr(consumer, name, mock)
        # Rebuild routes so they bind to the patched handlers.
        consumer._routes = consumer._build_routes()

        await consumer._handle_event(_make_stream_event(event_type))

        mocks[expected_handler].assert_awaited_once()
        for name, mock in mocks.items():
            if name != expected_handler:
                mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unmatched_event_acked_without_dispatch(
        self, consumer: SnipeItWorkerStreamConsumer
    ) -> None:
        """An unmatched event is acknowledged and no handler is invoked."""
        mock_client: Any = consumer._stream_client
        mock_client.read_events = AsyncMock(
            return_value=[_make_stream_event("ContactCreated")]
        )
        mock_client.acknowledge = AsyncMock()
        gear = AsyncMock()
        journal = AsyncMock()
        webhook = AsyncMock()
        consumer._handle_gear_item_updated = gear  # type: ignore[method-assign]
        consumer._handle_journal_maintenance_event = journal  # type: ignore[method-assign]
        consumer._handle_webhook_received = webhook  # type: ignore[method-assign]
        consumer._routes = consumer._build_routes()

        processed = await consumer._process_batch()

        assert processed == 1
        mock_client.acknowledge.assert_awaited_once()
        gear.assert_not_awaited()
        journal.assert_not_awaited()
        webhook.assert_not_awaited()

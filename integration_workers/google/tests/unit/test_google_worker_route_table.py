"""Unit tests for the GoogleWorkerStreamConsumer declarative route table.

ITER14-004 Phase 2: the consumer declares an ``EventRoute`` table instead of
overriding ``_handle_event``. These tests assert the route table maps the
expected event types to the right handlers, the consumed-event set is unchanged,
and unmatched events are acknowledged without dispatch.

LOCAL-177: the contact half of that table is now derived from the shared
``CONTACT_PUSH_EVENT_TYPES`` registry rather than hand-maintained, so a contact
event added backend-side cannot silently miss outbound Google sync.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.models.contacts.event_types import CONTACT_PUSH_EVENT_TYPES
from core_shared.stream_client import StreamClient, StreamEvent


def _make_stream_event(event_type: str) -> StreamEvent:
    """Create a minimal StreamEvent for the given type."""
    return StreamEvent(
        message_id="1-0",
        event_id="evt-1",
        event_type=event_type,
        aggregate_id=1,
        event_data={"id": 1},
        occurred_at="2024-06-15T10:30:00+00:00",
    )


@pytest.fixture
def consumer() -> Any:
    """Create a GoogleWorkerStreamConsumer with mock dependencies."""
    from stream_consumer_tasks import GoogleWorkerStreamConsumer

    return GoogleWorkerStreamConsumer(
        stream_client=MagicMock(spec=StreamClient),
        session_factory=MagicMock(),
        stream_name="pms:domain-events",
    )


class TestGoogleWorkerRouteTable:
    """The consumer declares its consumed events via a route table."""

    def test_route_table_covers_exact_consumed_event_set(self, consumer: Any) -> None:
        """Route patterns equal the documented consumed-event set (regression).

        Guards the spec requirement that the migrated consumer's consumed-event
        set is unchanged: the 3 journal + 2 tag events, plus every contact event
        the shared registry marks as pushed to integrations.
        """
        patterns = {route.pattern for route in consumer._routes}
        assert patterns == {
            "JournalCreated",
            "JournalUpdated",
            "JournalDeleted",
            "TagUpdated",
            "TagDeleted",
        } | set(CONTACT_PUSH_EVENT_TYPES)

    def test_contact_routes_are_driven_by_the_shared_registry(
        self, consumer: Any
    ) -> None:
        """LOCAL-177: the contact route set is the registry, not a hand list.

        Ten contact events (``TagAssigned``, ``ContactMethodAdded``,
        ``ImportantDate*`` …) were dropped because this table was maintained by
        hand. Deriving it from ``CONTACT_PUSH_EVENT_TYPES`` means a newly added
        contact event is routed as soon as it is classified.
        """
        contact_patterns = {
            route.pattern
            for route in consumer._routes
            if route.handler == consumer._handle_contact
        }
        assert contact_patterns == set(CONTACT_PUSH_EVENT_TYPES)
        # The events this ticket was raised for, spelled out so a regression
        # names the symptom rather than a set difference.
        assert {
            "TagAssigned",
            "TagRemoved",
            "ContactMethodAdded",
            "ContactMethodDeleted",
            "ImportantDateAdded",
            "ImportantDateUpdated",
            "ImportantDateDeleted",
        } <= contact_patterns

    @pytest.mark.parametrize(
        ("event_type", "expected_handler"),
        [
            ("JournalCreated", "process_journal_event"),
            ("JournalUpdated", "process_journal_event"),
            ("JournalDeleted", "process_journal_event"),
            ("TagUpdated", "process_tag_event"),
            ("TagDeleted", "process_tag_event"),
            *(
                (event_type, "process_contact_event")
                for event_type in CONTACT_PUSH_EVENT_TYPES
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_route_table_maps_event_type_to_correct_handler(
        self, consumer: Any, event_type: str, expected_handler: str
    ) -> None:
        """Each event type dispatches to its expected process_* function only."""
        with (
            patch(
                "stream_consumer_tasks.process_journal_event", new_callable=AsyncMock
            ) as journal,
            patch(
                "stream_consumer_tasks.process_tag_event", new_callable=AsyncMock
            ) as tag,
            patch(
                "stream_consumer_tasks.process_contact_event", new_callable=AsyncMock
            ) as contact,
        ):
            handlers = {
                "process_journal_event": journal,
                "process_tag_event": tag,
                "process_contact_event": contact,
            }
            await consumer._handle_event(_make_stream_event(event_type))

            handlers[expected_handler].assert_called_once()
            for name, mock in handlers.items():
                if name != expected_handler:
                    mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_unmatched_event_acked_without_dispatch(self, consumer: Any) -> None:
        """An unmatched event is acknowledged and no handler is invoked."""
        mock_client = consumer._stream_client
        mock_client.read_events = AsyncMock(
            return_value=[_make_stream_event("SomethingElse")]
        )
        mock_client.acknowledge = AsyncMock()

        with (
            patch(
                "stream_consumer_tasks.process_journal_event", new_callable=AsyncMock
            ) as journal,
            patch(
                "stream_consumer_tasks.process_tag_event", new_callable=AsyncMock
            ) as tag,
            patch(
                "stream_consumer_tasks.process_contact_event", new_callable=AsyncMock
            ) as contact,
        ):
            processed = await consumer._process_batch()

        assert processed == 1
        mock_client.acknowledge.assert_awaited_once()
        journal.assert_not_called()
        tag.assert_not_called()
        contact.assert_not_called()

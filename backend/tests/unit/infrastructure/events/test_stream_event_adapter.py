"""
Unit tests for StreamEventAdapter.

Tests the conversion from StreamEvent (Redis Streams) to OutboxEvent
(used by SearchIndexer and other processors).
"""

from datetime import datetime

from core_shared.stream_client import StreamEvent

from app.infrastructure.events.stream_event_adapter import stream_event_to_outbox_event


class TestStreamEventAdapter:
    """Test cases for stream_event_to_outbox_event conversion."""

    def test_converts_stream_event_to_outbox_event(self) -> None:
        """Test basic field mapping from StreamEvent to OutboxEvent."""
        stream_event = StreamEvent(
            message_id="1234567890-0",
            event_id="evt-abc-123",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42, "first_name": "John"},
            occurred_at="2024-06-15T10:30:00+00:00",
        )

        outbox_event = stream_event_to_outbox_event(stream_event)

        assert outbox_event.event_id == "evt-abc-123"
        assert outbox_event.event_type == "ContactCreated"
        assert outbox_event.aggregate_id == 42
        assert outbox_event.event_data == {"contact_id": 42, "first_name": "John"}
        assert outbox_event.processed_at is None
        assert outbox_event.retry_count == 0
        assert outbox_event.id == 0

    def test_parses_occurred_at_iso_string(self) -> None:
        """Test that occurred_at ISO 8601 string is parsed to datetime."""
        stream_event = StreamEvent(
            message_id="1234567890-0",
            event_id="evt-time-1",
            event_type="JournalUpdated",
            aggregate_id=99,
            event_data={"journal_id": 99},
            occurred_at="2024-06-15T10:30:00+00:00",
        )

        outbox_event = stream_event_to_outbox_event(stream_event)

        assert isinstance(outbox_event.occurred_at, datetime)
        assert outbox_event.occurred_at.year == 2024
        assert outbox_event.occurred_at.month == 6
        assert outbox_event.occurred_at.day == 15
        assert outbox_event.occurred_at.hour == 10
        assert outbox_event.occurred_at.minute == 30
        assert outbox_event.occurred_at.tzinfo is not None

    def test_parses_occurred_at_without_timezone(self) -> None:
        """Test that occurred_at without timezone info is handled."""
        stream_event = StreamEvent(
            message_id="1234567890-0",
            event_id="evt-naive-1",
            event_type="ContactUpdated",
            aggregate_id=10,
            event_data={"contact_id": 10},
            occurred_at="2024-03-20T14:00:00",
        )

        outbox_event = stream_event_to_outbox_event(stream_event)

        assert isinstance(outbox_event.occurred_at, datetime)
        assert outbox_event.occurred_at.year == 2024
        assert outbox_event.occurred_at.month == 3

    def test_created_at_matches_occurred_at(self) -> None:
        """Test that created_at is set to the same value as occurred_at."""
        stream_event = StreamEvent(
            message_id="1234567890-0",
            event_id="evt-created-1",
            event_type="TagAssigned",
            aggregate_id=5,
            event_data={"contact_id": 5, "tag_id": 10},
            occurred_at="2024-06-15T10:30:00+00:00",
        )

        outbox_event = stream_event_to_outbox_event(stream_event)

        assert outbox_event.created_at == outbox_event.occurred_at

    def test_preserves_complex_event_data(self) -> None:
        """Test that nested event_data dicts are preserved."""
        complex_data = {
            "contact_id": 42,
            "changed_fields": {"name": ("old", "new")},
            "tags": ["friend", "colleague"],
            "nested": {"key": "value"},
        }
        stream_event = StreamEvent(
            message_id="1234567890-0",
            event_id="evt-complex-1",
            event_type="ContactUpdated",
            aggregate_id=42,
            event_data=complex_data,
            occurred_at="2024-06-15T10:30:00+00:00",
        )

        outbox_event = stream_event_to_outbox_event(stream_event)

        assert outbox_event.event_data == complex_data

    def test_empty_event_data(self) -> None:
        """Test conversion with empty event_data dict."""
        stream_event = StreamEvent(
            message_id="1234567890-0",
            event_id="evt-empty-1",
            event_type="ContactDeleted",
            aggregate_id=7,
            event_data={},
            occurred_at="2024-06-15T10:30:00+00:00",
        )

        outbox_event = stream_event_to_outbox_event(stream_event)

        assert outbox_event.event_data == {}

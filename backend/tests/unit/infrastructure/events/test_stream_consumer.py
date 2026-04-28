"""
Unit tests for StreamConsumer base class.

Tests the abstract consumer with consumer group creation, event filtering,
acknowledgement, and retry logic.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.stream_client import StreamClient, StreamEvent

from app.infrastructure.events.stream_consumer import StreamConsumer


class ConcreteConsumer(StreamConsumer):
    """Concrete implementation of StreamConsumer for testing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handled_events: list[StreamEvent] = []

    async def _handle_event(self, event: StreamEvent) -> None:
        """Record handled events for test assertions."""
        self.handled_events.append(event)


class FailingConsumer(StreamConsumer):
    """Consumer that always fails during event handling."""

    async def _handle_event(self, event: StreamEvent) -> None:
        """Always raise an exception."""
        raise ValueError("Processing failed")


class TestStreamConsumer:
    """Test cases for StreamConsumer base class."""

    @pytest.fixture
    def mock_stream_client(self) -> MagicMock:
        """Create a mock StreamClient."""
        client = MagicMock(spec=StreamClient)
        client.ensure_consumer_group = AsyncMock()
        client.read_events = AsyncMock(return_value=[])
        client.acknowledge = AsyncMock()
        client.get_pending_entries = AsyncMock(return_value=[])
        client.claim_pending = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def consumer(self, mock_stream_client: MagicMock) -> ConcreteConsumer:
        """Create a ConcreteConsumer for testing."""
        return ConcreteConsumer(
            stream_client=mock_stream_client,
            stream_name="pms:domain-events",
            group_name="test-group",
            consumer_name="test-consumer-1",
            event_type_patterns=["contact.", "ContactCreated"],
        )

    @pytest.fixture
    def failing_consumer(self, mock_stream_client: MagicMock) -> FailingConsumer:
        """Create a FailingConsumer for testing error handling."""
        return FailingConsumer(
            stream_client=mock_stream_client,
            stream_name="pms:domain-events",
            group_name="test-group",
            consumer_name="test-consumer-1",
            event_type_patterns=["contact."],
        )

    @pytest.fixture
    def contact_created_event(self) -> StreamEvent:
        """Create a sample contact.created event."""
        return StreamEvent(
            message_id="1234567890-0",
            event_id="evt-1",
            event_type="contact.created",
            aggregate_id=42,
            event_data={"contact_id": 42, "name": "John"},
            occurred_at="2024-01-01T12:00:00Z",
        )

    @pytest.fixture
    def journal_created_event(self) -> StreamEvent:
        """Create a sample JournalCreated event (non-matching)."""
        return StreamEvent(
            message_id="1234567890-1",
            event_id="evt-2",
            event_type="JournalCreated",
            aggregate_id=100,
            event_data={"journal_id": 100},
            occurred_at="2024-01-01T12:05:00Z",
        )

    @pytest.mark.asyncio
    async def test_consumer_creates_group_on_start(
        self, consumer: ConcreteConsumer, mock_stream_client: MagicMock
    ) -> None:
        """Test ensure_consumer_group is called when consumer starts."""
        # Start and immediately stop
        consumer.stop()
        await consumer.start()

        mock_stream_client.ensure_consumer_group.assert_called_once_with(
            "pms:domain-events", "test-group"
        )

    @pytest.mark.asyncio
    async def test_consumer_reads_and_processes_matching_events(
        self,
        consumer: ConcreteConsumer,
        mock_stream_client: MagicMock,
        contact_created_event: StreamEvent,
    ) -> None:
        """Test events matching event_type_patterns are passed to _handle_event and acknowledged."""
        # Return events on first call, then empty on subsequent calls
        mock_stream_client.read_events.side_effect = [
            [contact_created_event],
            [],
        ]

        # Run one batch
        count = await consumer._process_batch()

        assert count == 1
        assert len(consumer.handled_events) == 1
        assert consumer.handled_events[0].event_id == "evt-1"

        # Event should be acknowledged
        mock_stream_client.acknowledge.assert_called_once_with(
            "pms:domain-events", "test-group", "1234567890-0"
        )

    @pytest.mark.asyncio
    async def test_consumer_acks_non_matching_events_immediately(
        self,
        consumer: ConcreteConsumer,
        mock_stream_client: MagicMock,
        journal_created_event: StreamEvent,
    ) -> None:
        """Test events not matching patterns are acknowledged without calling _handle_event."""
        mock_stream_client.read_events.return_value = [journal_created_event]

        count = await consumer._process_batch()

        # Should not have handled the event
        assert len(consumer.handled_events) == 0
        # But should have acknowledged it (skip-ack)
        mock_stream_client.acknowledge.assert_called_once_with(
            "pms:domain-events", "test-group", "1234567890-1"
        )
        # Count of processed (including skipped) events
        assert count == 1

    @pytest.mark.asyncio
    async def test_consumer_prefix_matching(self, consumer: ConcreteConsumer) -> None:
        """Test pattern 'contact.' matches 'contact.created', 'contact.updated' but not 'ContactCreated'."""
        assert consumer._matches_event_type("contact.created") is True
        assert consumer._matches_event_type("contact.updated") is True
        assert consumer._matches_event_type("contact.deleted") is True
        # "ContactCreated" matches because it's also in the patterns list as exact match
        assert consumer._matches_event_type("ContactCreated") is True

    @pytest.mark.asyncio
    async def test_consumer_exact_matching(self, mock_stream_client: MagicMock) -> None:
        """Test exact pattern 'ContactSummaryRefreshRequested' matches exactly."""
        consumer = ConcreteConsumer(
            stream_client=mock_stream_client,
            stream_name="pms:domain-events",
            group_name="test-group",
            consumer_name="test-consumer-1",
            event_type_patterns=["ContactSummaryRefreshRequested"],
        )

        assert consumer._matches_event_type("ContactSummaryRefreshRequested") is True
        assert consumer._matches_event_type("ContactCreated") is False
        assert consumer._matches_event_type("contact.created") is False

    @pytest.mark.asyncio
    async def test_consumer_no_match(self, consumer: ConcreteConsumer) -> None:
        """Test events that don't match any pattern."""
        assert consumer._matches_event_type("JournalCreated") is False
        assert consumer._matches_event_type("sync.completed") is False

    @pytest.mark.asyncio
    async def test_consumer_retries_pending_entries(
        self,
        consumer: ConcreteConsumer,
        mock_stream_client: MagicMock,
        contact_created_event: StreamEvent,
    ) -> None:
        """Test _retry_pending claims stale pending entries and reprocesses them."""
        from core_shared.stream_client import PendingEntry

        mock_stream_client.get_pending_entries.return_value = [
            PendingEntry(
                message_id="1234567890-0",
                consumer="test-consumer-1",
                idle_time_ms=120000,
                delivery_count=2,
            )
        ]
        mock_stream_client.claim_pending.return_value = [contact_created_event]

        count = await consumer._retry_pending()

        assert count == 1
        assert len(consumer.handled_events) == 1
        mock_stream_client.acknowledge.assert_called_once_with(
            "pms:domain-events", "test-group", "1234567890-0"
        )

    @pytest.mark.asyncio
    async def test_consumer_handles_processing_error(
        self,
        failing_consumer: FailingConsumer,
        mock_stream_client: MagicMock,
        contact_created_event: StreamEvent,
    ) -> None:
        """Test if _handle_event raises, event is NOT acknowledged (remains pending for retry)."""
        mock_stream_client.read_events.return_value = [contact_created_event]

        count = await failing_consumer._process_batch()

        # Event should NOT be acknowledged since handler failed
        mock_stream_client.acknowledge.assert_not_called()
        # Count includes attempted events (even if failed)
        assert count == 1

    @pytest.mark.asyncio
    async def test_consumer_stop(
        self,
        consumer: ConcreteConsumer,
        mock_stream_client: MagicMock,
    ) -> None:
        """Test stop() sets running flag to False, loop exits."""
        consumer.stop()
        # start() should return quickly since _running is False
        await consumer.start()

        # ensure_consumer_group should still be called
        mock_stream_client.ensure_consumer_group.assert_called_once()

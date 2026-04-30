"""
Unit tests for the DeadLetterConsumerMixin.
"""

from unittest.mock import AsyncMock, patch

import pytest
from core_shared.stream_client import PendingEntry, StreamEvent

from app.infrastructure.events.dead_letter_consumer_mixin import DeadLetterConsumerMixin
from app.infrastructure.events.dead_letter_repository import DeadLetterEvent


class MockConsumer(DeadLetterConsumerMixin):
    def __init__(self):
        self._group_name = "test-group"
        self._stream_name = "test-stream"
        self._stream_client = AsyncMock()


@pytest.fixture
def consumer():
    return MockConsumer()


@pytest.fixture
def stream_event():
    return StreamEvent(
        message_id="1234-0",
        event_id="evt-123",
        event_type="test.event",
        aggregate_id=42,
        event_data={"foo": "bar"},
        occurred_at="2024-01-01T12:00:00Z",
    )


@pytest.fixture
def pending_entry():
    return PendingEntry(
        message_id="1234-0",
        consumer="test-consumer",
        idle_time_ms=10000,
        delivery_count=5,
    )


@pytest.mark.asyncio
async def test_handle_dead_letter_saves_and_acks(consumer, stream_event, pending_entry):
    """Test that the mixin saves the dead letter to the repository and acks it."""
    # Mock the database engine and connection
    mock_conn = AsyncMock()
    from unittest.mock import MagicMock

    mock_engine = MagicMock()

    class MockContextManager:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_engine.begin.return_value = MockContextManager()

    with (
        patch(
            "app.infrastructure.events.dead_letter_consumer_mixin.get_async_database_engine",
            return_value=mock_engine,
        ),
        patch(
            "app.infrastructure.events.dead_letter_consumer_mixin.DeadLetterRepository"
        ) as mock_repo_class,
    ):
        mock_repo = AsyncMock()
        mock_repo_class.return_value = mock_repo

        # We need to patch the super()._handle_dead_letter call because our MockConsumer
        # doesn't actually inherit from StreamConsumer in this unit test structure.
        # But wait, Python's super() inside DeadLetterConsumerMixin will fail if the MRO
        # doesn't include something with _handle_dead_letter.

        # Let's fix our MockConsumer to inherit from a dummy base that has _handle_dead_letter
        class BaseWithHandler:
            async def _handle_dead_letter(self, event, pending_entry):
                self.base_called = True

        class RealMockConsumer(DeadLetterConsumerMixin, BaseWithHandler):
            def __init__(self):
                self._group_name = "test-group"
                self._stream_name = "test-stream"
                self._stream_client = AsyncMock()
                self.base_called = False

        real_consumer = RealMockConsumer()

        await real_consumer._handle_dead_letter(stream_event, pending_entry)

        # Verify repository was created with connection
        mock_repo_class.assert_called_once_with(mock_conn)

        # Verify save was called with right event
        mock_repo.save.assert_called_once()
        saved_event = mock_repo.save.call_args[0][0]
        assert isinstance(saved_event, DeadLetterEvent)
        assert saved_event.event_id == "evt-123"
        assert saved_event.consumer_group == "test-group"
        assert saved_event.delivery_count == 5

        # Verify super class was called
        assert real_consumer.base_called is True


@pytest.mark.asyncio
async def test_handle_dead_letter_exception_logging(stream_event, pending_entry):
    """Test that exceptions during saving just log and don't raise/ack."""

    class BaseWithHandler:
        async def _handle_dead_letter(self, event, pending_entry):
            self.base_called = True

    class RealMockConsumer(DeadLetterConsumerMixin, BaseWithHandler):
        def __init__(self):
            self._group_name = "test-group"
            self._stream_name = "test-stream"
            self._stream_client = AsyncMock()
            self.base_called = False

    real_consumer = RealMockConsumer()

    from unittest.mock import MagicMock

    mock_engine = MagicMock()
    mock_engine.begin.side_effect = Exception("Database error")

    with (
        patch(
            "app.infrastructure.events.dead_letter_consumer_mixin.get_async_database_engine",
            return_value=mock_engine,
        ),
        patch(
            "app.infrastructure.events.dead_letter_consumer_mixin.logger.error"
        ) as mock_logger,
    ):
        await real_consumer._handle_dead_letter(stream_event, pending_entry)

        # Should log the error
        mock_logger.assert_called_once()
        assert "Failed to save dead letter event" in mock_logger.call_args[0][0]

        # Should NOT call super() which would ACK the message
        assert real_consumer.base_called is False

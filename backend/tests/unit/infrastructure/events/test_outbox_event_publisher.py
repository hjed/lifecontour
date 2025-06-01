"""
Unit tests for OutboxEventPublisher.

Tests the outbox event publisher implementation to ensure it correctly
stores domain events in the outbox_events table.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.core.contacts.models.events import DomainEvent
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


class TestOutboxEventPublisher:
    """Test cases for OutboxEventPublisher."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock async database connection."""
        connection = AsyncMock()
        return connection

    @pytest.fixture
    def publisher(self, mock_connection):
        """Create an OutboxEventPublisher instance with mock connection."""
        return OutboxEventPublisher(mock_connection)

    @pytest.fixture
    def sample_event(self):
        """Create a sample domain event for testing."""
        return DomainEvent(
            event_id="test-event-123",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42, "first_name": "John", "last_name": "Doe"},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
        )

    @pytest.mark.asyncio
    async def test_publish_single_event(self, publisher, mock_connection, sample_event):
        """Test publishing a single domain event."""
        # Act
        await publisher.publish(sample_event)

        # Assert
        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args

        # Check the SQL query
        query = call_args[0][0]
        assert "INSERT INTO outbox_events" in str(query)

        # Check the parameters
        params = call_args[0][1]
        assert params["event_id"] == "test-event-123"
        assert params["event_type"] == "ContactCreated"
        assert params["aggregate_id"] == 42
        assert params["occurred_at"] == datetime(2024, 1, 1, 12, 0, 0)
        assert params["retry_count"] == 0

        # Check event data is JSON serialized
        event_data = json.loads(params["event_data"])
        assert event_data["contact_id"] == 42
        assert event_data["first_name"] == "John"
        assert event_data["last_name"] == "Doe"

    @pytest.mark.asyncio
    async def test_publish_batch_events(self, publisher, mock_connection):
        """Test publishing multiple events in a batch."""
        # Arrange
        events = [
            DomainEvent(
                event_id=f"test-event-{i}",
                event_type="ContactCreated",
                aggregate_id=i,
                event_data={"contact_id": i, "name": f"Contact {i}"},
                occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            )
            for i in range(3)
        ]

        # Act
        await publisher.publish_batch(events)

        # Assert
        assert mock_connection.execute.call_count == 3

        # Verify each event was published
        for i, call in enumerate(mock_connection.execute.call_args_list):
            params = call[0][1]
            assert params["event_id"] == f"test-event-{i}"
            assert params["aggregate_id"] == i

    @pytest.mark.asyncio
    async def test_publish_empty_batch(self, publisher, mock_connection):
        """Test publishing an empty batch of events."""
        # Act
        await publisher.publish_batch([])

        # Assert
        mock_connection.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_handles_database_error(
        self, publisher, mock_connection, sample_event
    ):
        """Test that database errors are properly raised."""
        # Arrange
        mock_connection.execute.side_effect = Exception("Database connection failed")

        # Act & Assert
        with pytest.raises(Exception, match="Database connection failed"):
            await publisher.publish(sample_event)

    @pytest.mark.asyncio
    async def test_publish_batch_handles_partial_failure(
        self, publisher, mock_connection
    ):
        """Test that batch publishing handles partial failures correctly."""
        # Arrange
        events = [
            DomainEvent(
                event_id="test-event-1",
                event_type="ContactCreated",
                aggregate_id=1,
                event_data={"contact_id": 1},
                occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            ),
            DomainEvent(
                event_id="test-event-2",
                event_type="ContactCreated",
                aggregate_id=2,
                event_data={"contact_id": 2},
                occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            ),
        ]

        # Make the second call fail
        mock_connection.execute.side_effect = [None, Exception("Database error")]

        # Act & Assert
        with pytest.raises(Exception, match="Database error"):
            await publisher.publish_batch(events)

        # First event should have been processed
        assert mock_connection.execute.call_count == 2

    def test_publisher_initialization(self, mock_connection):
        """Test that the publisher initializes correctly."""
        # Act
        publisher = OutboxEventPublisher(mock_connection)

        # Assert
        assert publisher.conn is mock_connection

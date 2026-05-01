"""
Unit tests for OutboxRepository.

Tests the outbox repository for retrieving and managing outbox events.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.events.outbox_repository import OutboxEvent, OutboxRepository


class TestOutboxRepository:
    """Test cases for OutboxRepository."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock async database connection."""
        connection = AsyncMock()
        return connection

    @pytest.fixture
    def repository(self, mock_connection):
        """Create an OutboxRepository instance with mock connection."""
        return OutboxRepository(mock_connection)

    @pytest.fixture
    def sample_outbox_events_data(self):
        """Create sample outbox event data for testing."""
        return [
            {
                "id": 1,
                "event_id": "event-1",
                "event_type": "ContactCreated",
                "aggregate_id": 42,
                "event_data": '{"contact_id": 42, "name": "John"}',
                "occurred_at": datetime(2024, 1, 1, 12, 0, 0),
                "retry_count": 0,
                "created_at": datetime(2024, 1, 1, 12, 0, 0),
                "relayed_at": None,
            },
            {
                "id": 2,
                "event_id": "event-2",
                "event_type": "ContactUpdated",
                "aggregate_id": 43,
                "event_data": '{"contact_id": 43, "name": "Jane"}',
                "occurred_at": datetime(2024, 1, 1, 12, 5, 0),
                "retry_count": 1,
                "created_at": datetime(2024, 1, 1, 12, 5, 0),
                "relayed_at": None,
            },
        ]

    @pytest.mark.asyncio
    async def test_get_unrelayed_events(
        self, repository, mock_connection, sample_outbox_events_data
    ):
        """Test retrieving unrelayed events from the outbox."""
        # Arrange
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(**event_data) for event_data in sample_outbox_events_data
        ]
        mock_connection.execute.return_value = mock_result

        # Act
        events = await repository.get_unrelayed_events(limit=10, max_retry_count=3)

        # Assert
        assert len(events) == 2

        # Check first event
        assert events[0].id == 1
        assert events[0].event_id == "event-1"
        assert events[0].event_type == "ContactCreated"
        assert events[0].aggregate_id == 42
        assert events[0].event_data == {"contact_id": 42, "name": "John"}
        assert getattr(events[0], "relayed_at", None) is None
        assert events[0].retry_count == 0

        # Check second event
        assert events[1].id == 2
        assert events[1].event_id == "event-2"
        assert events[1].retry_count == 1

        # Verify SQL query
        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args
        query = str(call_args[0][0])
        assert "SELECT" in query
        assert "FROM outbox_events" in query
        assert "WHERE relayed_at IS NULL" in query
        assert "retry_count <" in query
        assert "LIMIT" in query
        params = call_args[0][1]
        assert params["max_retry_count"] == 3

    @pytest.mark.asyncio
    async def test_get_unrelayed_events_empty_result(self, repository, mock_connection):
        """Test retrieving unrelayed events when none exist."""
        # Arrange
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_connection.execute.return_value = mock_result

        # Act
        events = await repository.get_unrelayed_events()

        # Assert
        assert events == []

    @pytest.mark.asyncio
    async def test_get_unrelayed_events_without_retry_filter(
        self, repository, mock_connection, sample_outbox_events_data
    ):
        """Test retrieving unrelayed events without excluding failed events."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(**event_data) for event_data in sample_outbox_events_data
        ]
        mock_connection.execute.return_value = mock_result

        await repository.get_unrelayed_events(limit=10)

        call_args = mock_connection.execute.call_args
        query = str(call_args[0][0])
        assert "retry_count <" not in query

    @pytest.mark.asyncio
    async def test_mark_as_relayed(self, repository, mock_connection):
        """Test marking an event as relayed."""
        # Act
        await repository.mark_as_relayed("event-123")

        # Assert
        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args

        # Check SQL query
        query = str(call_args[0][0])
        assert "UPDATE outbox_events" in query
        assert "SET relayed_at" in query
        assert "WHERE event_id" in query

        # Check parameters
        params = call_args[0][1]
        assert params["event_id"] == "event-123"
        assert "relayed_at" in params

    @pytest.mark.asyncio
    async def test_repository_handles_database_errors(
        self, repository, mock_connection
    ):
        """Test that repository methods handle database errors properly."""
        # Arrange
        mock_connection.execute.side_effect = Exception("Database error")

        # Act & Assert
        with pytest.raises(Exception, match="Database error"):
            await repository.get_unrelayed_events()

        with pytest.raises(Exception, match="Database error"):
            await repository.mark_as_relayed("event-123")

    def test_outbox_event_dataclass(self):
        """Test the OutboxEvent dataclass."""
        # Arrange
        event_data = {"contact_id": 42, "name": "Test"}

        # Act
        event = OutboxEvent(
            id=1,
            event_id="test-event",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data=event_data,
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            retry_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            relayed_at=None,
        )

        # Assert
        assert event.id == 1
        assert event.event_id == "test-event"
        assert event.event_type == "ContactCreated"
        assert event.aggregate_id == 42
        assert event.event_data == event_data
        assert event.occurred_at == datetime(2024, 1, 1, 12, 0, 0)
        assert getattr(event, "relayed_at", None) is None
        assert event.retry_count == 0

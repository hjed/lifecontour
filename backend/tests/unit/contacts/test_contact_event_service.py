"""Tests for ContactEventService."""

from unittest.mock import AsyncMock

import pytest

from app.core.contacts.models.events import ContactCreated
from app.core.contacts.models.repositories import ContactEditEvent
from app.core.contacts.services.contact_event_service import ContactEventService


class TestContactEventService:
    """Test ContactEventService."""

    @pytest.fixture
    def mock_event_repo(self):
        """Create mock event repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_transaction(self):
        """Create mock transaction."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_event_repo):
        """Create ContactEventService instance."""
        return ContactEventService(mock_event_repo)

    @pytest.mark.asyncio
    async def test_record_domain_event(
        self, service, mock_event_repo, mock_transaction
    ):
        """Test recording a domain event."""
        # Arrange
        domain_event = ContactCreated(contact_id=1, first_name="John", last_name="Doe")

        # Act
        await service.record_domain_event(domain_event, mock_transaction)

        # Assert
        mock_event_repo.store_event.assert_called_once()
        stored_event = mock_event_repo.store_event.call_args[0][0]

        assert isinstance(stored_event, ContactEditEvent)
        assert stored_event.event_type == "ContactCreated"
        assert stored_event.aggregate_id == 1
        assert stored_event.occurred_at == domain_event.occurred_at.isoformat()
        assert "contact_id" in stored_event.event_data
        assert stored_event.event_data["contact_id"] == 1
        assert "first_name" in stored_event.event_data
        assert stored_event.event_data["first_name"] == "John"
        assert "last_name" in stored_event.event_data
        assert stored_event.event_data["last_name"] == "Doe"

    @pytest.mark.asyncio
    async def test_get_contact_events(self, service, mock_event_repo, mock_transaction):
        """Test getting events for a contact."""
        # Arrange
        expected_events = [
            ContactEditEvent(
                event_id="event-1",
                event_type="ContactCreated",
                aggregate_id=1,
                event_data={"first_name": "John"},
                occurred_at="2024-01-01T00:00:00Z",
            ),
            ContactEditEvent(
                event_id="event-2",
                event_type="ContactUpdated",
                aggregate_id=1,
                event_data={"first_name": "Jane"},
                occurred_at="2024-01-02T00:00:00Z",
            ),
        ]
        mock_event_repo.get_events_for_contact.return_value = expected_events

        # Act
        result = await service.get_contact_events(
            1, limit=50, _transaction=mock_transaction
        )

        # Assert
        assert result == expected_events
        mock_event_repo.get_events_for_contact.assert_called_once_with(1, 50)

    @pytest.mark.asyncio
    async def test_get_contact_events_with_custom_limit(
        self, service, mock_event_repo, mock_transaction
    ):
        """Test getting events for a contact with custom limit."""
        # Arrange
        expected_events: list[ContactEditEvent] = []
        mock_event_repo.get_events_for_contact.return_value = expected_events

        # Act
        result = await service.get_contact_events(
            1, limit=10, _transaction=mock_transaction
        )

        # Assert
        assert result == expected_events
        mock_event_repo.get_events_for_contact.assert_called_once_with(1, 10)

    @pytest.mark.asyncio
    async def test_get_events_by_type(self, service, mock_event_repo, mock_transaction):
        """Test getting events by type."""
        # Arrange
        expected_events = [
            ContactEditEvent(
                event_id="event-1",
                event_type="ContactCreated",
                aggregate_id=1,
                event_data={"first_name": "John"},
                occurred_at="2024-01-01T00:00:00Z",
            ),
            ContactEditEvent(
                event_id="event-2",
                event_type="ContactCreated",
                aggregate_id=2,
                event_data={"first_name": "Jane"},
                occurred_at="2024-01-02T00:00:00Z",
            ),
        ]
        mock_event_repo.get_events_by_type.return_value = expected_events

        # Act
        result = await service.get_events_by_type(
            "ContactCreated", limit=50, _transaction=mock_transaction
        )

        # Assert
        assert result == expected_events
        mock_event_repo.get_events_by_type.assert_called_once_with("ContactCreated", 50)

    @pytest.mark.asyncio
    async def test_get_events_by_type_with_custom_limit(
        self, service, mock_event_repo, mock_transaction
    ):
        """Test getting events by type with custom limit."""
        # Arrange
        expected_events: list[ContactEditEvent] = []
        mock_event_repo.get_events_by_type.return_value = expected_events

        # Act
        result = await service.get_events_by_type(
            "ContactUpdated", limit=25, _transaction=mock_transaction
        )

        # Assert
        assert result == expected_events
        mock_event_repo.get_events_by_type.assert_called_once_with("ContactUpdated", 25)

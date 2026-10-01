"""Integration tests for ContactEditEventRepository with real database."""

import pytest
from core_shared.models.contacts.entities import Contact
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactEditEventRepository
from app.core.contacts.models.repositories import ContactEditEvent
from tests.integration.contact_seeding import seed_contact


@pytest.mark.integration
class TestContactEditEventRepositoryIntegration:
    """Integration tests for ContactEditEventRepository with real database."""

    @pytest.fixture
    def event_repo(self, clean_database: AsyncConnection):
        """Create ContactEditEventRepository instance with real database connection."""
        return SqlContactEditEventRepository(clean_database)

    @pytest.mark.asyncio
    async def test_store_event(self, event_repo, clean_database: AsyncConnection):
        """Test storing a domain event."""
        # Arrange
        contact = Contact(id=1, first_name="John", last_name="Doe")
        await seed_contact(
            clean_database,
            contact_id=contact.id,
            first_name=contact.first_name,
            last_name=contact.last_name,
        )

        event = ContactEditEvent(
            event_id="contact_created_1_2024-01-01T00:00:00",
            event_type="ContactCreated",
            aggregate_id=1,
            event_data={
                "contact_id": 1,
                "first_name": "John",
                "last_name": "Doe",
                "occurred_at": "2024-01-01T00:00:00Z",
            },
            occurred_at="2024-01-01T00:00:00Z",
            correlation_id="correlation-123",
        )

        # Act
        saved_event = await event_repo.store_event(event)

        # Assert
        assert saved_event.id is not None
        assert saved_event.event_id == "contact_created_1_2024-01-01T00:00:00"
        assert saved_event.event_type == "ContactCreated"
        assert saved_event.aggregate_id == 1
        assert saved_event.event_data["contact_id"] == 1
        assert saved_event.event_data["first_name"] == "John"
        assert saved_event.event_data["last_name"] == "Doe"
        assert saved_event.occurred_at == "2024-01-01T00:00:00Z"
        assert saved_event.correlation_id == "correlation-123"

    @pytest.mark.asyncio
    async def test_store_event_without_correlation_id(
        self, event_repo, clean_database: AsyncConnection
    ):
        """Test storing event without correlation ID."""
        # Arrange
        await seed_contact(
            clean_database, contact_id=2, first_name="Jane", last_name="Doe"
        )

        event = ContactEditEvent(
            event_id="contact_updated_2_2024-01-02T00:00:00",
            event_type="ContactUpdated",
            aggregate_id=2,
            event_data={
                "contact_id": 2,
                "changed_fields": {"first_name": ["John", "Jane"]},
                "occurred_at": "2024-01-02T00:00:00Z",
            },
            occurred_at="2024-01-02T00:00:00Z",
        )

        # Act
        saved_event = await event_repo.store_event(event)

        # Assert
        assert saved_event.id is not None
        assert saved_event.correlation_id is None
        assert saved_event.event_data["changed_fields"]["first_name"] == [
            "John",
            "Jane",
        ]

    @pytest.mark.asyncio
    async def test_store_event_complex_data(
        self, event_repo, clean_database: AsyncConnection
    ):
        """Test storing event with complex JSON data."""
        # Arrange
        await seed_contact(
            clean_database, contact_id=1, first_name="John", last_name="Doe"
        )

        complex_data = {
            "contact_id": 1,
            "method_details": {
                "type": "email",
                "value": "john@example.com",
                "is_primary": True,
                "metadata": {"verified": False, "source": "manual_entry"},
            },
            "tags": ["work", "client", "important"],
            "numbers": [1, 2, 3.14, -5],
            "occurred_at": "2024-01-01T00:00:00Z",
        }

        event = ContactEditEvent(
            event_id="contact_method_added_1_2024-01-01T00:00:00",
            event_type="ContactMethodAdded",
            aggregate_id=1,
            event_data=complex_data,
            occurred_at="2024-01-01T00:00:00Z",
        )

        # Act
        saved_event = await event_repo.store_event(event)

        # Assert
        assert saved_event.event_data["method_details"]["type"] == "email"
        assert saved_event.event_data["method_details"]["metadata"]["verified"] is False
        assert saved_event.event_data["tags"] == ["work", "client", "important"]
        assert saved_event.event_data["numbers"] == [1, 2, 3.14, -5]

    @pytest.mark.asyncio
    async def test_get_events_for_contact(
        self, event_repo, clean_database: AsyncConnection
    ):
        """Test getting events for a specific contact."""
        # Arrange - Create contacts for events
        for contact_id, first_name, last_name in [
            (1, "John", "Doe"),
            (2, "Jane", "Smith"),
        ]:
            await seed_contact(
                clean_database,
                contact_id=contact_id,
                first_name=first_name,
                last_name=last_name,
            )

        events = [
            ContactEditEvent(
                event_id="contact_created_1_2024-01-01T00:00:00",
                event_type="ContactCreated",
                aggregate_id=1,
                event_data={"contact_id": 1, "first_name": "John"},
                occurred_at="2024-01-01T00:00:00Z",
            ),
            ContactEditEvent(
                event_id="contact_updated_1_2024-01-02T00:00:00",
                event_type="ContactUpdated",
                aggregate_id=1,
                event_data={
                    "contact_id": 1,
                    "changed_fields": {"last_name": ["Doe", "Smith"]},
                },
                occurred_at="2024-01-02T00:00:00Z",
            ),
            ContactEditEvent(
                event_id="contact_created_2_2024-01-03T00:00:00",
                event_type="ContactCreated",
                aggregate_id=2,
                event_data={"contact_id": 2, "first_name": "Jane"},
                occurred_at="2024-01-03T00:00:00Z",
            ),
        ]

        for event in events:
            await event_repo.store_event(event)

        # Act
        contact1_events = await event_repo.get_events_for_contact(1)

        # Assert
        assert len(contact1_events) == 2
        for event in contact1_events:
            assert event.aggregate_id == 1

        event_types = [event.event_type for event in contact1_events]
        assert "ContactCreated" in event_types
        assert "ContactUpdated" in event_types

    @pytest.mark.asyncio
    async def test_get_events_for_contact_with_limit(
        self, event_repo, clean_database: AsyncConnection
    ):
        """Test getting events for contact with limit."""
        # Arrange - Create multiple events for same contact
        await seed_contact(
            clean_database, contact_id=1, first_name="John", last_name="Doe"
        )

        for i in range(10):
            day = f"{i + 1:02d}" if i < 9 else "10"
            event = ContactEditEvent(
                event_id=f"event_{i}_2024-01-{day}T00:00:00",
                event_type="ContactUpdated",
                aggregate_id=1,
                event_data={"contact_id": 1, "field": f"value_{i}"},
                occurred_at=f"2024-01-{day}T00:00:00Z",
            )
            await event_repo.store_event(event)

        # Act
        limited_events = await event_repo.get_events_for_contact(1, limit=5)

        # Assert
        assert len(limited_events) == 5
        # Should be ordered by occurred_at DESC (most recent first)
        for i in range(len(limited_events) - 1):
            assert limited_events[i].occurred_at >= limited_events[i + 1].occurred_at

    @pytest.mark.asyncio
    async def test_get_events_by_type(
        self, event_repo, clean_database: AsyncConnection
    ):
        """Test getting events by type."""
        # Arrange - Create events of different types
        for contact_id, first_name, last_name in [
            (1, "John", "Doe"),
            (2, "Jane", "Smith"),
        ]:
            await seed_contact(
                clean_database,
                contact_id=contact_id,
                first_name=first_name,
                last_name=last_name,
            )

        events = [
            ContactEditEvent(
                event_id="contact_created_1_2024-01-01T00:00:00",
                event_type="ContactCreated",
                aggregate_id=1,
                event_data={"contact_id": 1},
                occurred_at="2024-01-01T00:00:00Z",
            ),
            ContactEditEvent(
                event_id="contact_created_2_2024-01-02T00:00:00",
                event_type="ContactCreated",
                aggregate_id=2,
                event_data={"contact_id": 2},
                occurred_at="2024-01-02T00:00:00Z",
            ),
            ContactEditEvent(
                event_id="contact_updated_1_2024-01-03T00:00:00",
                event_type="ContactUpdated",
                aggregate_id=1,
                event_data={"contact_id": 1},
                occurred_at="2024-01-03T00:00:00Z",
            ),
            ContactEditEvent(
                event_id="tag_assigned_1_2024-01-04T00:00:00",
                event_type="TagAssigned",
                aggregate_id=1,
                event_data={"contact_id": 1, "tag_id": 5},
                occurred_at="2024-01-04T00:00:00Z",
            ),
        ]

        for event in events:
            await event_repo.store_event(event)

        # Act
        created_events = await event_repo.get_events_by_type("ContactCreated")

        # Assert
        assert len(created_events) == 2
        for event in created_events:
            assert event.event_type == "ContactCreated"

        aggregate_ids = [event.aggregate_id for event in created_events]
        assert 1 in aggregate_ids
        assert 2 in aggregate_ids

    @pytest.mark.asyncio
    async def test_get_events_by_type_with_limit(
        self, event_repo, clean_database: AsyncConnection
    ):
        """Test getting events by type with limit."""
        # Arrange - Create multiple events of same type
        for contact_id, first_name, last_name in [
            (1, "John", "Doe"),
            (2, "Jane", "Smith"),
            (3, "Bob", "Johnson"),
            (4, "Alice", "Williams"),
            (5, "Charlie", "Brown"),
            (6, "David", "Davis"),
            (7, "Eve", "Evans"),
            (8, "Frank", "Franklin"),
        ]:
            await seed_contact(
                clean_database,
                contact_id=contact_id,
                first_name=first_name,
                last_name=last_name,
            )

        for i in range(8):
            day = f"{i + 1:02d}"
            event = ContactEditEvent(
                event_id=f"contact_updated_{i}_2024-01-{day}T00:00:00",
                event_type="ContactUpdated",
                aggregate_id=i + 1,
                event_data={"contact_id": i + 1},
                occurred_at=f"2024-01-{day}T00:00:00Z",
            )
            await event_repo.store_event(event)

        # Act
        limited_events = await event_repo.get_events_by_type("ContactUpdated", limit=3)

        # Assert
        assert len(limited_events) == 3
        for event in limited_events:
            assert event.event_type == "ContactUpdated"

    @pytest.mark.asyncio
    async def test_get_events_by_correlation_id(
        self, event_repo, clean_database: AsyncConnection
    ):
        """Test getting events by correlation ID."""
        # Arrange - Create events with same correlation ID
        for contact_id, first_name, last_name in [
            (1, "John", "Doe"),
            (2, "Jane", "Smith"),
            (3, "Bob", "Johnson"),
        ]:
            await seed_contact(
                clean_database,
                contact_id=contact_id,
                first_name=first_name,
                last_name=last_name,
            )

        correlation_id = "batch-operation-123"
        events = [
            ContactEditEvent(
                event_id="contact_created_1_2024-01-01T00:00:00",
                event_type="ContactCreated",
                aggregate_id=1,
                event_data={"contact_id": 1},
                occurred_at="2024-01-01T00:00:00Z",
                correlation_id=correlation_id,
            ),
            ContactEditEvent(
                event_id="contact_created_2_2024-01-02T00:00:00",
                event_type="ContactCreated",
                aggregate_id=2,
                event_data={"contact_id": 2},
                occurred_at="2024-01-02T00:00:00Z",
                correlation_id=correlation_id,
            ),
            ContactEditEvent(
                event_id="contact_created_3_2024-01-03T00:00:00",
                event_type="ContactCreated",
                aggregate_id=3,
                event_data={"contact_id": 3},
                occurred_at="2024-01-03T00:00:00Z",
                correlation_id="different-correlation",
            ),
        ]

        for event in events:
            await event_repo.store_event(event)

        # Act
        correlated_events = await event_repo.get_events_by_correlation_id(
            correlation_id
        )

        # Assert
        assert len(correlated_events) == 2
        for event in correlated_events:
            assert event.correlation_id == correlation_id

        aggregate_ids = [event.aggregate_id for event in correlated_events]
        assert 1 in aggregate_ids
        assert 2 in aggregate_ids
        assert 3 not in aggregate_ids

    @pytest.mark.asyncio
    async def test_event_ordering(self, event_repo, clean_database: AsyncConnection):
        """Test that events are returned in correct order (most recent first)."""
        # Arrange - Create events with different timestamps
        await seed_contact(
            clean_database, contact_id=1, first_name="John", last_name="Doe"
        )

        events = [
            ContactEditEvent(
                event_id="event_1",
                event_type="ContactCreated",
                aggregate_id=1,
                event_data={"contact_id": 1},
                occurred_at="2024-01-01T00:00:00Z",
            ),
            ContactEditEvent(
                event_id="event_2",
                event_type="ContactUpdated",
                aggregate_id=1,
                event_data={"contact_id": 1},
                occurred_at="2024-01-03T00:00:00Z",
            ),
            ContactEditEvent(
                event_id="event_3",
                event_type="ContactUpdated",
                aggregate_id=1,
                event_data={"contact_id": 1},
                occurred_at="2024-01-02T00:00:00Z",
            ),
        ]

        for event in events:
            await event_repo.store_event(event)

        # Act
        contact_events = await event_repo.get_events_for_contact(1)

        # Assert
        assert len(contact_events) == 3
        # Should be ordered by occurred_at DESC
        assert contact_events[0].event_id == "event_2"  # 2024-01-03
        assert contact_events[1].event_id == "event_3"  # 2024-01-02
        assert contact_events[2].event_id == "event_1"  # 2024-01-01

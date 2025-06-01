"""Unit tests for contacts domain events."""

from datetime import datetime

from app.core.contacts.models.events import (
    ContactAddressAdded,
    ContactCreated,
    ContactDeleted,
    ContactMethodAdded,
    ContactNoteAdded,
    ContactUpdated,
    TagAssigned,
    TagRemoved,
)


class TestContactCreated:
    """Test ContactCreated event."""

    def test_create_event_with_last_name(self):
        """Test creating ContactCreated event with last name."""
        event = ContactCreated(contact_id=1, first_name="John", last_name="Doe")

        assert event.aggregate_id == 1
        assert event.event_type == "ContactCreated"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["first_name"] == "John"
        assert event.event_data["last_name"] == "Doe"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_created_1_")

    def test_create_event_without_last_name(self):
        """Test creating ContactCreated event without last name."""
        event = ContactCreated(contact_id=2, first_name="Jane")

        assert event.aggregate_id == 2
        assert event.event_type == "ContactCreated"
        assert event.event_data["contact_id"] == 2
        assert event.event_data["first_name"] == "Jane"
        assert event.event_data["last_name"] is None
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_created_2_")


class TestContactUpdated:
    """Test ContactUpdated event."""

    def test_create_event(self):
        """Test creating ContactUpdated event."""
        changed_fields = {
            "first_name": ("John", "Jonathan"),
            "email": ("old@example.com", "new@example.com"),
        }

        event = ContactUpdated(contact_id=1, changed_fields=changed_fields)

        assert event.aggregate_id == 1
        assert event.event_type == "ContactUpdated"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["changed_fields"] == changed_fields
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_updated_1_")


class TestContactDeleted:
    """Test ContactDeleted event."""

    def test_create_event(self):
        """Test creating ContactDeleted event."""
        event = ContactDeleted(contact_id=1)

        assert event.aggregate_id == 1
        assert event.event_type == "ContactDeleted"
        assert event.event_data["contact_id"] == 1
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_deleted_1_")


class TestTagAssigned:
    """Test TagAssigned event."""

    def test_create_event(self):
        """Test creating TagAssigned event."""
        event = TagAssigned(contact_id=1, tag_id=2, tag_name="work")

        assert event.aggregate_id == 1
        assert event.event_type == "TagAssigned"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["tag_id"] == 2
        assert event.event_data["tag_name"] == "work"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("tag_assigned_1_2_")


class TestTagRemoved:
    """Test TagRemoved event."""

    def test_create_event(self):
        """Test creating TagRemoved event."""
        event = TagRemoved(contact_id=1, tag_id=2, tag_name="work")

        assert event.aggregate_id == 1
        assert event.event_type == "TagRemoved"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["tag_id"] == 2
        assert event.event_data["tag_name"] == "work"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("tag_removed_1_2_")


class TestContactMethodAdded:
    """Test ContactMethodAdded event."""

    def test_create_event(self):
        """Test creating ContactMethodAdded event."""
        event = ContactMethodAdded(
            contact_id=1, method_id=2, method_type="email", value="test@example.com"
        )

        assert event.aggregate_id == 1
        assert event.event_type == "ContactMethodAdded"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["method_id"] == 2
        assert event.event_data["method_type"] == "email"
        assert event.event_data["value"] == "test@example.com"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_method_added_1_2_")


class TestContactAddressAdded:
    """Test ContactAddressAdded event."""

    def test_create_event(self):
        """Test creating ContactAddressAdded event."""
        event = ContactAddressAdded(
            contact_id=1, address_id=2, street_line_1="123 Main St", country_code="AU"
        )

        assert event.aggregate_id == 1
        assert event.event_type == "ContactAddressAdded"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["address_id"] == 2
        assert event.event_data["street_line_1"] == "123 Main St"
        assert event.event_data["country_code"] == "AU"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_address_added_1_2_")


class TestContactNoteAdded:
    """Test ContactNoteAdded event."""

    def test_create_event_short_content(self):
        """Test creating ContactNoteAdded event with short content."""
        event = ContactNoteAdded(contact_id=1, note_id=2, content="Short note")

        assert event.aggregate_id == 1
        assert event.event_type == "ContactNoteAdded"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["note_id"] == 2
        assert event.event_data["content"] == "Short note"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_note_added_1_2_")

    def test_create_event_long_content_truncated(self):
        """Test creating ContactNoteAdded event with long content gets truncated."""
        long_content = "x" * 150  # 150 characters
        event = ContactNoteAdded(contact_id=1, note_id=2, content=long_content)

        assert event.aggregate_id == 1
        assert event.event_type == "ContactNoteAdded"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["note_id"] == 2
        # Content should be truncated to 100 chars + "..."
        expected_content = "x" * 100 + "..."
        assert event.event_data["content"] == expected_content
        assert len(event.event_data["content"]) == 103
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_note_added_1_2_")

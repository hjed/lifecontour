"""Unit tests for contact history converters."""

from datetime import UTC, datetime

import pytest
from core_shared.models.contacts.value_objects import Provenance

from app.api.contacts.converters import ContactHistoryConverter
from app.core.contacts.models.repositories import ContactFieldHistoryEntry


class TestContactHistoryConverter:
    """Tests for ContactHistoryConverter."""

    def test_to_resource_basic(self):
        """Test basic conversion of history entry to resource."""
        entry = ContactFieldHistoryEntry(
            entity_type="contact",
            entity_id=123,
            field_name="first_name",
            old_value="John",
            new_value="Jane",
            changed_by="user@example.com",
            source=Provenance.GOOGLE_CONTACTS,
            id=1,
            created_at="2024-01-15T10:30:00+00:00",
        )

        resource = ContactHistoryConverter.to_resource(entry)

        assert resource.type == "contact_history"
        assert resource.id == "1"
        assert resource.attributes.entity_type == "contact"
        assert resource.attributes.entity_id == 123
        assert resource.attributes.field_name == "first_name"
        assert resource.attributes.old_value == "John"
        assert resource.attributes.new_value == "Jane"
        assert resource.attributes.changed_by == "user@example.com"
        assert resource.attributes.source == "google_contacts"
        assert resource.attributes.created_at is not None

    def test_to_resource_with_none_values(self):
        """Test conversion with None old_value (e.g., new field)."""
        entry = ContactFieldHistoryEntry(
            entity_type="contact",
            entity_id=456,
            field_name="nick_name",
            old_value=None,
            new_value="JD",
            changed_by="system",
            id=2,
            created_at="2024-01-15T11:00:00+00:00",
        )

        resource = ContactHistoryConverter.to_resource(entry)

        assert resource.id == "2"
        assert resource.attributes.old_value is None
        assert resource.attributes.new_value == "JD"

    def test_to_resource_without_id_raises_error(self):
        """Test that conversion fails without an ID."""
        entry = ContactFieldHistoryEntry(
            entity_type="contact",
            entity_id=123,
            field_name="first_name",
            old_value="John",
            new_value="Jane",
            changed_by="user@example.com",
            id=None,  # No ID
            created_at="2024-01-15T10:30:00+00:00",
        )

        with pytest.raises(ValueError, match="without ID"):
            ContactHistoryConverter.to_resource(entry)

    def test_to_resource_different_entity_types(self):
        """Test conversion for different entity types."""
        entity_types = [
            "contact",
            "contact_method",
            "contact_address",
            "contact_note",
            "contact_tag",
        ]

        for idx, entity_type in enumerate(entity_types):
            entry = ContactFieldHistoryEntry(
                entity_type=entity_type,
                entity_id=100 + idx,
                field_name="value",
                old_value="old",
                new_value="new",
                changed_by="system",
                id=idx + 1,
                created_at="2024-01-15T10:30:00+00:00",
            )

            resource = ContactHistoryConverter.to_resource(entry)
            assert resource.attributes.entity_type == entity_type

    def test_to_resource_with_datetime_object(self):
        """Test conversion when created_at is already a datetime object."""
        # This tests the case where created_at might already be parsed
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        entry = ContactFieldHistoryEntry(
            entity_type="contact",
            entity_id=123,
            field_name="first_name",
            old_value="John",
            new_value="Jane",
            changed_by="user@example.com",
            id=1,
            created_at=dt.isoformat(),
        )

        resource = ContactHistoryConverter.to_resource(entry)
        assert resource.attributes.created_at is not None

    def test_to_resource_with_none_created_at(self):
        """Test conversion when created_at is None."""
        entry = ContactFieldHistoryEntry(
            entity_type="contact",
            entity_id=123,
            field_name="first_name",
            old_value="John",
            new_value="Jane",
            changed_by="user@example.com",
            id=1,
            created_at=None,
        )

        resource = ContactHistoryConverter.to_resource(entry)
        assert resource.attributes.created_at is None

"""
Integration tests for Google Contacts worker outbox event creation.

Tests that verify the worker correctly creates outbox events
when syncing contacts from Google API.

These tests verify the full pipeline: GooglePerson → Contact → serialized dict
→ OutboxEvent, without requiring a full database setup.
"""

import sys
from datetime import datetime
from typing import Any

import pytest

sys.path.insert(0, "/core_shared")

from core_shared.models.contacts.serialization import serialize_contact
from core_shared.models.outbox import OutboxEvent

from api_models import (
    GoogleEmailAddress,
    GoogleFieldMetadata,
    GoogleName,
    GooglePerson,
    GooglePhoneNumber,
)
from transformer import GoogleContactTransformer


@pytest.fixture
def sample_google_person() -> GooglePerson:
    """Sample Google Person model as returned by the Google People API."""
    return GooglePerson(
        resourceName="people/c123456789",
        etag="etag123",
        names=[
            GoogleName(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                displayName="John Doe",
                givenName="John",
                familyName="Doe",
            )
        ],
        emailAddresses=[
            GoogleEmailAddress(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                value="john.doe@example.com",
                type="work",
                formattedType="Work",
            )
        ],
        phoneNumbers=[
            GooglePhoneNumber(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                value="+1-555-123-4567",
                canonicalForm="+15551234567",
                type="mobile",
                formattedType="Mobile",
            )
        ],
    )


@pytest.fixture
def serialized_contact(sample_google_person: GooglePerson) -> dict[str, Any]:
    """Contact data serialized to dict format (as stored in outbox events)."""
    transformer = GoogleContactTransformer()
    contact = transformer.transform_person(sample_google_person)
    return serialize_contact(contact)


class TestWorkerOutboxEventCreation:
    """Test cases for worker outbox event creation."""

    def test_create_contact_sync_event_for_created_contact(
        self,
        serialized_contact: dict[str, Any],
    ) -> None:
        """Test that OutboxEvent.create_contact_sync_event creates correct event for new contact."""
        outbox_event = OutboxEvent.create_contact_sync_event(
            contact_data=serialized_contact,
            integration_source="google",
            external_id="people/c123456789",
            sync_type="created",
        )

        assert outbox_event.event_type == "contact.created"
        assert outbox_event.event_data["integration_source"] == "google"
        assert outbox_event.event_data["external_id"] == "people/c123456789"
        assert outbox_event.event_data["sync_type"] == "created"
        assert outbox_event.event_data["contact_data"] == serialized_contact
        assert "sync_timestamp" in outbox_event.event_data

        # Verify sync_timestamp is a valid ISO format datetime
        sync_timestamp = str(outbox_event.event_data["sync_timestamp"])
        datetime.fromisoformat(sync_timestamp)  # Should not raise

    def test_create_contact_sync_event_for_updated_contact(
        self,
        serialized_contact: dict[str, Any],
    ) -> None:
        """Test that OutboxEvent.create_contact_sync_event creates correct event for updated contact."""
        outbox_event = OutboxEvent.create_contact_sync_event(
            contact_data=serialized_contact,
            integration_source="google",
            external_id="people/c123456789",
            sync_type="updated",
        )

        assert outbox_event.event_type == "contact.updated"
        assert outbox_event.event_data["integration_source"] == "google"
        assert outbox_event.event_data["external_id"] == "people/c123456789"
        assert outbox_event.event_data["sync_type"] == "updated"
        assert outbox_event.event_data["contact_data"] == serialized_contact

    def test_create_contact_sync_event_preserves_all_contact_data(
        self,
        serialized_contact: dict[str, Any],
    ) -> None:
        """Test that all Contact dict fields are preserved in the outbox event."""
        outbox_event = OutboxEvent.create_contact_sync_event(
            contact_data=serialized_contact,
            integration_source="google",
            external_id="people/c123456789",
            sync_type="created",
        )

        contact_data = outbox_event.event_data["contact_data"]

        # Verify transformed Contact format fields (not Google API format)
        assert contact_data["first_name"] == "John"
        assert contact_data["last_name"] == "Doe"
        assert contact_data["middle_name"] is None
        assert contact_data["nick_name"] is None
        assert contact_data["is_favourite"] is False

        # Verify email method was transformed correctly
        email_methods = [
            m for m in contact_data["methods"] if m["method_type"] == "email"
        ]
        assert len(email_methods) == 1
        assert email_methods[0]["value"] == "john.doe@example.com"
        assert email_methods[0]["label"] == "Work"
        assert email_methods[0]["is_primary"] is True

        # Verify phone method was transformed and canonical form used
        phone_methods = [
            m for m in contact_data["methods"] if m["method_type"] == "phone"
        ]
        assert len(phone_methods) == 1
        assert phone_methods[0]["value"] == "+15551234567"
        assert phone_methods[0]["label"] == "Mobile"

    def test_outbox_event_has_required_fields(
        self,
        serialized_contact: dict[str, Any],
    ) -> None:
        """Test that outbox events have all required fields."""
        outbox_event = OutboxEvent.create_contact_sync_event(
            contact_data=serialized_contact,
            integration_source="google",
            external_id="people/c123456789",
            sync_type="created",
        )

        assert hasattr(outbox_event, "event_type")
        assert hasattr(outbox_event, "event_data")
        assert hasattr(outbox_event, "id")
        assert hasattr(outbox_event, "created_at")
        assert hasattr(outbox_event, "processed_at")
        assert hasattr(outbox_event, "retry_count")

        assert outbox_event.event_type == "contact.created"
        assert isinstance(outbox_event.event_data, dict)
        assert outbox_event.processed_at is None
        # retry_count is None until inserted (server default applies on insert)
        assert outbox_event.retry_count is None

    def test_transformer_produces_contact_dict_not_google_format(
        self,
        sample_google_person: GooglePerson,
    ) -> None:
        """Test that transformer produces Contact dict format, not raw Google API format."""
        transformer = GoogleContactTransformer()
        contact = transformer.transform_person(sample_google_person)
        serialized = serialize_contact(contact)

        # Must have Contact dict keys
        assert "first_name" in serialized
        assert "last_name" in serialized
        assert "methods" in serialized
        assert "addresses" in serialized
        assert "notes" in serialized
        assert "tags" in serialized

        # Must NOT have Google API keys
        assert "resourceName" not in serialized
        assert "etag" not in serialized
        assert "names" not in serialized
        assert "emailAddresses" not in serialized
        assert "phoneNumbers" not in serialized

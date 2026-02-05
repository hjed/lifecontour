"""
Integration tests for Google Contacts worker outbox event creation.

Tests that verify the worker correctly creates outbox events
when syncing contacts from Google API.

These tests verify the outbox event creation logic without requiring
a full database setup.
"""

import sys
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, "/core_shared")

from core_shared.models.outbox import OutboxEvent


@pytest.fixture
def sample_google_person():
    """Sample Google Person API response."""
    return {
        "resourceName": "people/c123456789",
        "etag": "etag123",
        "names": [{
            "givenName": "John",
            "familyName": "Doe",
            "displayName": "John Doe"
        }],
        "emailAddresses": [{
            "value": "john.doe@example.com",
            "type": "work"
        }],
        "phoneNumbers": [{
            "value": "+1-555-123-4567",
            "type": "mobile"
        }]
    }


class TestWorkerOutboxEventCreation:
    """Test cases for worker outbox event creation."""

    def test_create_contact_sync_event_for_created_contact(
        self,
        sample_google_person: dict,
    ):
        """Test that OutboxEvent.create_contact_sync_event creates correct event for new contact."""
        # Create outbox event using the factory method
        outbox_event = OutboxEvent.create_contact_sync_event(
            contact_data=sample_google_person,
            integration_source="google_contacts",
            external_id="people/c123456789",
            sync_type="created",
        )

        # Verify event type
        assert outbox_event.event_type == "contact.created"

        # Verify event_data structure
        assert outbox_event.event_data["integration_source"] == "google_contacts"
        assert outbox_event.event_data["external_id"] == "people/c123456789"
        assert outbox_event.event_data["sync_type"] == "created"
        assert outbox_event.event_data["contact_data"] == sample_google_person
        assert "sync_timestamp" in outbox_event.event_data

        # Verify sync_timestamp is a valid ISO format datetime
        sync_timestamp = outbox_event.event_data["sync_timestamp"]
        datetime.fromisoformat(sync_timestamp)  # Should not raise


    def test_create_contact_sync_event_for_updated_contact(
        self,
        sample_google_person: dict,
    ):
        """Test that OutboxEvent.create_contact_sync_event creates correct event for updated contact."""
        # Create outbox event for updated contact
        outbox_event = OutboxEvent.create_contact_sync_event(
            contact_data=sample_google_person,
            integration_source="google_contacts",
            external_id="people/c123456789",
            sync_type="updated",
        )

        # Verify event type
        assert outbox_event.event_type == "contact.updated"

        # Verify event_data structure
        assert outbox_event.event_data["integration_source"] == "google_contacts"
        assert outbox_event.event_data["external_id"] == "people/c123456789"
        assert outbox_event.event_data["sync_type"] == "updated"
        assert outbox_event.event_data["contact_data"] == sample_google_person


    def test_create_contact_sync_event_preserves_all_contact_data(
        self,
        sample_google_person: dict,
    ):
        """Test that all contact data fields are preserved in the outbox event."""
        # Create outbox event
        outbox_event = OutboxEvent.create_contact_sync_event(
            contact_data=sample_google_person,
            integration_source="google_contacts",
            external_id="people/c123456789",
            sync_type="created",
        )

        # Verify all contact data fields are preserved
        contact_data = outbox_event.event_data["contact_data"]
        assert contact_data["resourceName"] == "people/c123456789"
        assert contact_data["etag"] == "etag123"
        assert len(contact_data["names"]) == 1
        assert contact_data["names"][0]["givenName"] == "John"
        assert contact_data["names"][0]["familyName"] == "Doe"
        assert len(contact_data["emailAddresses"]) == 1
        assert contact_data["emailAddresses"][0]["value"] == "john.doe@example.com"
        assert len(contact_data["phoneNumbers"]) == 1
        assert contact_data["phoneNumbers"][0]["value"] == "+1-555-123-4567"


    def test_outbox_event_has_required_fields(
        self,
        sample_google_person: dict,
    ):
        """Test that outbox events have all required fields."""
        # Create outbox event
        outbox_event = OutboxEvent.create_contact_sync_event(
            contact_data=sample_google_person,
            integration_source="google_contacts",
            external_id="people/c123456789",
            sync_type="created",
        )

        # Verify required fields exist
        assert hasattr(outbox_event, "event_type")
        assert hasattr(outbox_event, "event_data")
        assert hasattr(outbox_event, "id")
        assert hasattr(outbox_event, "created_at")
        assert hasattr(outbox_event, "processed_at")
        assert hasattr(outbox_event, "retry_count")

        # Verify initial values
        assert outbox_event.event_type == "contact.created"
        assert isinstance(outbox_event.event_data, dict)
        assert outbox_event.processed_at is None
        # retry_count is None until inserted (server default applies on insert)
        assert outbox_event.retry_count is None


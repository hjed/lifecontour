"""Unit tests for the contact-summary refresh domain events."""

import pytest

from app.core.contacts.models.events import (
    ContactSummaryRefreshDue,
    ContactSummaryRefreshRequested,
    DomainEvent,
)


@pytest.mark.unit
class TestContactSummaryRefreshRequested:
    """Tests for the ContactSummaryRefreshRequested domain event."""

    def test_event_creation(self):
        """Test basic event creation with contact_id."""
        event = ContactSummaryRefreshRequested(contact_id=42)

        assert event.aggregate_id == 42
        assert event.event_type == "ContactSummaryRefreshRequested"
        assert event.event_data["contact_id"] == 42
        assert event.occurred_at is not None
        assert event.event_id is not None

    def test_event_is_domain_event(self):
        """Test that event inherits from DomainEvent."""
        event = ContactSummaryRefreshRequested(contact_id=1)

        assert isinstance(event, DomainEvent)

    def test_event_data_structure(self):
        """Test event_data contains the expected fields."""
        event = ContactSummaryRefreshRequested(contact_id=99)

        assert "contact_id" in event.event_data
        assert event.event_data["contact_id"] == 99

    def test_event_with_transaction(self):
        """Test event creation with a transaction reference."""
        from unittest.mock import MagicMock

        mock_txn = MagicMock()
        event = ContactSummaryRefreshRequested(contact_id=1, transaction=mock_txn)

        assert event.transaction is mock_txn

    def test_event_without_transaction(self):
        """Test event creation without a transaction defaults to None."""
        event = ContactSummaryRefreshRequested(contact_id=1)

        assert event.transaction is None

    def test_unique_event_ids(self):
        """Test that each event gets a unique event_id."""
        event1 = ContactSummaryRefreshRequested(contact_id=1)
        event2 = ContactSummaryRefreshRequested(contact_id=1)

        # Event IDs should be unique (contain timestamp)
        assert event1.event_id != event2.event_id


@pytest.mark.unit
class TestContactSummaryRefreshDue:
    """Tests for the ContactSummaryRefreshDue domain event."""

    def test_event_creation(self):
        """Test basic event creation with contact_id."""
        event = ContactSummaryRefreshDue(contact_id=42)

        assert event.aggregate_id == 42
        assert event.event_type == "ContactSummaryRefreshDue"
        assert event.event_data == {"contact_id": 42}
        assert event.occurred_at is not None
        assert event.event_id.startswith("contact_summary_refresh_due_42_")

    def test_event_is_domain_event(self):
        """Test that event inherits from DomainEvent."""
        event = ContactSummaryRefreshDue(contact_id=1)

        assert isinstance(event, DomainEvent)

    def test_event_with_transaction(self):
        """Test event creation with a transaction reference."""
        from unittest.mock import MagicMock

        mock_txn = MagicMock()
        event = ContactSummaryRefreshDue(contact_id=1, transaction=mock_txn)

        assert event.transaction is mock_txn

    def test_event_without_transaction(self):
        """Test event creation without a transaction defaults to None."""
        event = ContactSummaryRefreshDue(contact_id=1)

        assert event.transaction is None

    def test_unique_event_ids(self):
        """Test that each event gets a unique event_id."""
        event1 = ContactSummaryRefreshDue(contact_id=1)
        event2 = ContactSummaryRefreshDue(contact_id=1)

        assert event1.event_id != event2.event_id

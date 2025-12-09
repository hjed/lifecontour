"""Unit tests for JournalContactRelationship entity."""

from datetime import UTC, datetime

import pytest

from app.core.journal.models.contact_relationship import (
    ContactRelationshipType,
    JournalContactRelationship,
)
from app.core.journal.models.exceptions import JournalContactRelationshipValidationError


class TestContactRelationshipType:
    """Tests for ContactRelationshipType enum."""

    def test_enum_values(self):
        """Test that all relationship types are defined."""
        assert ContactRelationshipType.PARTICIPANT == "PARTICIPANT"
        assert ContactRelationshipType.INVITEE == "INVITEE"
        assert ContactRelationshipType.MENTION == "MENTION"
        assert ContactRelationshipType.ABOUT == "ABOUT"

    def test_enum_count(self):
        """Test that there are exactly 4 relationship types."""
        assert len(ContactRelationshipType) == 4


class TestJournalContactRelationship:
    """Tests for JournalContactRelationship entity."""

    def test_create_valid_relationship(self):
        """Test creating a valid journal contact relationship."""
        now = datetime.now(UTC)
        relationship = JournalContactRelationship(
            journal_id=1,
            contact_id=100,
            relationship_type=ContactRelationshipType.PARTICIPANT,
            created_at=now,
        )

        assert relationship.journal_id == 1
        assert relationship.contact_id == 100
        assert relationship.relationship_type == ContactRelationshipType.PARTICIPANT
        assert relationship.created_at == now

    def test_create_relationship_without_created_at(self):
        """Test creating a relationship without created_at (should be None)."""
        relationship = JournalContactRelationship(
            journal_id=1,
            contact_id=100,
            relationship_type=ContactRelationshipType.INVITEE,
        )

        assert relationship.created_at is None

    def test_all_relationship_types(self):
        """Test creating relationships with all relationship types."""
        for rel_type in ContactRelationshipType:
            relationship = JournalContactRelationship(
                journal_id=1,
                contact_id=100,
                relationship_type=rel_type,
            )
            assert relationship.relationship_type == rel_type

    def test_invalid_journal_id_zero(self):
        """Test that journal_id cannot be zero."""
        with pytest.raises(JournalContactRelationshipValidationError) as exc_info:
            JournalContactRelationship(
                journal_id=0,
                contact_id=100,
                relationship_type=ContactRelationshipType.PARTICIPANT,
            )

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in exc_info.value.message

    def test_invalid_journal_id_negative(self):
        """Test that journal_id cannot be negative."""
        with pytest.raises(JournalContactRelationshipValidationError) as exc_info:
            JournalContactRelationship(
                journal_id=-1,
                contact_id=100,
                relationship_type=ContactRelationshipType.PARTICIPANT,
            )

        assert exc_info.value.field == "journal_id"

    def test_invalid_contact_id_zero(self):
        """Test that contact_id cannot be zero."""
        with pytest.raises(JournalContactRelationshipValidationError) as exc_info:
            JournalContactRelationship(
                journal_id=1,
                contact_id=0,
                relationship_type=ContactRelationshipType.PARTICIPANT,
            )

        assert exc_info.value.field == "contact_id"
        assert "positive integer" in exc_info.value.message

    def test_invalid_contact_id_negative(self):
        """Test that contact_id cannot be negative."""
        with pytest.raises(JournalContactRelationshipValidationError) as exc_info:
            JournalContactRelationship(
                journal_id=1,
                contact_id=-1,
                relationship_type=ContactRelationshipType.PARTICIPANT,
            )

        assert exc_info.value.field == "contact_id"

    def test_invalid_relationship_type(self):
        """Test that relationship_type must be a ContactRelationshipType enum."""
        with pytest.raises(JournalContactRelationshipValidationError) as exc_info:
            JournalContactRelationship(
                journal_id=1,
                contact_id=100,
                relationship_type="INVALID",  # type: ignore
            )

        assert exc_info.value.field == "relationship_type"
        assert "ContactRelationshipType enum" in exc_info.value.message

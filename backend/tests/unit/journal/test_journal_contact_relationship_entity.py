"""Unit tests for JournalContactRelationship entity."""

import pytest
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.contact_event_role import ContactEventRole


@pytest.mark.unit
class TestJournalContactRelationship:
    """Test JournalContactRelationship entity."""

    def test_create_relationship_minimal(self):
        """Test creating relationship with minimal required fields."""
        rel = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        assert rel.journal_id == 1
        assert rel.contact_id == 2
        assert rel.relationship_type == JournalContactRelationshipType.PARTICIPANT
        assert rel.created_at is None

    def test_create_relationship_all_types(self):
        """Test creating relationships with all relationship types."""
        for rel_type in JournalContactRelationshipType:
            rel = JournalContactRelationship(
                journal_id=1,
                contact_id=2,
                relationship_type=rel_type,
            )
            assert rel.relationship_type == rel_type

    def test_create_relationship_invalid_journal_id_zero(self):
        """Test creating relationship with zero journal ID raises error."""
        with pytest.raises(ValueError, match="Journal ID must be positive"):
            JournalContactRelationship(
                journal_id=0,
                contact_id=2,
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            )

    def test_create_relationship_invalid_journal_id_negative(self):
        """Test creating relationship with negative journal ID raises error."""
        with pytest.raises(ValueError, match="Journal ID must be positive"):
            JournalContactRelationship(
                journal_id=-1,
                contact_id=2,
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            )

    def test_create_relationship_invalid_contact_id_zero(self):
        """Test creating relationship with zero contact ID raises error."""
        with pytest.raises(ValueError, match="Contact ID must be positive"):
            JournalContactRelationship(
                journal_id=1,
                contact_id=0,
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            )

    def test_create_relationship_invalid_contact_id_negative(self):
        """Test creating relationship with negative contact ID raises error."""
        with pytest.raises(ValueError, match="Contact ID must be positive"):
            JournalContactRelationship(
                journal_id=1,
                contact_id=-1,
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            )

    def test_relationship_equality(self):
        """Test relationship equality based on composite key."""
        rel1 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        rel2 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        assert rel1 == rel2

    def test_relationship_inequality_different_journal(self):
        """Test relationships with different journal IDs are not equal."""
        rel1 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        rel2 = JournalContactRelationship(
            journal_id=2,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        assert rel1 != rel2

    def test_relationship_inequality_different_contact(self):
        """Test relationships with different contact IDs are not equal."""
        rel1 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        rel2 = JournalContactRelationship(
            journal_id=1,
            contact_id=3,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        assert rel1 != rel2

    def test_relationship_inequality_different_type(self):
        """Test relationships with different types are not equal."""
        rel1 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        rel2 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.INVITEE,
        )
        assert rel1 != rel2

    def test_relationship_hash(self):
        """Test relationship hash is based on composite key."""
        rel1 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        rel2 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        assert hash(rel1) == hash(rel2)

    def test_relationship_in_set(self):
        """Test relationships can be used in sets."""
        rel1 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        rel2 = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        rel_set = {rel1, rel2}
        assert len(rel_set) == 1

    def test_relationship_type_string_representation(self):
        """Test relationship type string representation."""
        rel_type = JournalContactRelationshipType.PARTICIPANT
        assert str(rel_type) == "PARTICIPANT"

    def test_create_with_status_participant(self):
        """Test PARTICIPANT with status=ATTENDING is valid."""
        rel = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.ATTENDING,
        )
        assert rel.status == AttendeeStatus.ATTENDING

    def test_create_with_role_participant(self):
        """Test PARTICIPANT with role=ORGANISER is valid."""
        rel = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            role=ContactEventRole.ORGANISER,
        )
        assert rel.role == ContactEventRole.ORGANISER

    def test_create_with_both_status_and_role(self):
        """Test PARTICIPANT with both status and role is valid."""
        rel = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.ATTENDING,
            role=ContactEventRole.ORGANISER,
        )
        assert rel.status == AttendeeStatus.ATTENDING
        assert rel.role == ContactEventRole.ORGANISER

    def test_create_with_status_invitee(self):
        """Test INVITEE with status is valid."""
        rel = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.INVITEE,
            status=AttendeeStatus.NO_REPLY,
        )
        assert rel.status == AttendeeStatus.NO_REPLY

    def test_create_with_role_invitee(self):
        """Test INVITEE with role is valid."""
        rel = JournalContactRelationship(
            journal_id=1,
            contact_id=2,
            relationship_type=JournalContactRelationshipType.INVITEE,
            role=ContactEventRole.FACILITATOR_HELPER,
        )
        assert rel.role == ContactEventRole.FACILITATOR_HELPER

    def test_status_rejected_on_mention(self):
        """Test MENTION with status raises ValueError."""
        with pytest.raises(
            ValueError,
            match="status and role are only permitted.*PARTICIPANT.*INVITEE",
        ):
            JournalContactRelationship(
                journal_id=1,
                contact_id=2,
                relationship_type=JournalContactRelationshipType.MENTION,
                status=AttendeeStatus.ATTENDING,
            )

    def test_status_rejected_on_about(self):
        """Test ABOUT with status raises ValueError."""
        with pytest.raises(
            ValueError,
            match="status and role are only permitted.*PARTICIPANT.*INVITEE",
        ):
            JournalContactRelationship(
                journal_id=1,
                contact_id=2,
                relationship_type=JournalContactRelationshipType.ABOUT,
                status=AttendeeStatus.MAYBE,
            )

    def test_role_rejected_on_mention(self):
        """Test MENTION with role raises ValueError."""
        with pytest.raises(
            ValueError,
            match="status and role are only permitted.*PARTICIPANT.*INVITEE",
        ):
            JournalContactRelationship(
                journal_id=1,
                contact_id=2,
                relationship_type=JournalContactRelationshipType.MENTION,
                role=ContactEventRole.ORGANISER,
            )

    def test_role_rejected_on_about(self):
        """Test ABOUT with role raises ValueError."""
        with pytest.raises(
            ValueError,
            match="status and role are only permitted.*PARTICIPANT.*INVITEE",
        ):
            JournalContactRelationship(
                journal_id=1,
                contact_id=2,
                relationship_type=JournalContactRelationshipType.ABOUT,
                role=ContactEventRole.FACILITATOR_HELPER,
            )

    def test_create_without_status_role_all_types(self):
        """Test all relationship types work with status=None and role=None (backward compat)."""
        for rel_type in JournalContactRelationshipType:
            rel = JournalContactRelationship(
                journal_id=1,
                contact_id=2,
                relationship_type=rel_type,
            )
            assert rel.status is None
            assert rel.role is None

    def test_all_attendee_status_values(self):
        """Test iterating AttendeeStatus members, verify string representation."""
        expected = {"ATTENDING", "ATTENDED", "MAYBE", "NO_REPLY", "DECLINED"}
        actual = {str(s) for s in AttendeeStatus}
        assert actual == expected

    def test_all_contact_event_role_values(self):
        """Test iterating ContactEventRole members (2 values), verify string representation."""
        expected = {"ORGANISER", "FACILITATOR_HELPER"}
        actual = {str(r) for r in ContactEventRole}
        assert actual == expected

"""Unit tests for contact relationship entities."""

from datetime import datetime

import pytest

from app.core.contacts.models.entities import ContactRelationship, RelationshipType


class TestRelationshipType:
    """Test RelationshipType enum."""

    def test_enum_values(self):
        """Test that enum has expected values."""
        assert RelationshipType.PARTNER.value == "partner"
        assert RelationshipType.CHILD.value == "child"
        assert RelationshipType.PARENT.value == "parent"
        assert RelationshipType.SIBLING.value == "sibling"
        assert RelationshipType.FRIEND.value == "friend"
        assert RelationshipType.COLLEAGUE.value == "colleague"
        assert RelationshipType.FAMILY.value == "family"
        assert RelationshipType.OTHER.value == "other"

    def test_enum_string_representation(self):
        """Test that enum string representation returns the value."""
        assert str(RelationshipType.PARTNER) == "partner"
        assert str(RelationshipType.CHILD) == "child"
        assert str(RelationshipType.PARENT) == "parent"


class TestContactRelationship:
    """Test ContactRelationship entity."""

    def test_create_valid_relationship(self):
        """Test creating a valid contact relationship."""
        relationship = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
        )

        assert relationship.from_contact_id == 1
        assert relationship.to_contact_id == 2
        assert relationship.relationship_type == RelationshipType.FRIEND
        assert relationship.id is None
        assert relationship.created_at is None
        assert relationship.updated_at is None

    def test_create_relationship_with_all_fields(self):
        """Test creating a relationship with all fields."""
        now = datetime.now()
        relationship = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.PARTNER,
            id=123,
            created_at=now,
            updated_at=now,
        )

        assert relationship.id == 123
        assert relationship.from_contact_id == 1
        assert relationship.to_contact_id == 2
        assert relationship.relationship_type == RelationshipType.PARTNER
        assert relationship.created_at == now
        assert relationship.updated_at == now

    def test_self_relationship_validation(self):
        """Test that self-relationships are not allowed."""
        with pytest.raises(
            ValueError, match="Contact cannot have a relationship with itself"
        ):
            ContactRelationship(
                from_contact_id=1,
                to_contact_id=1,
                relationship_type=RelationshipType.FRIEND,
            )

    def test_negative_contact_id_validation(self):
        """Test that negative contact IDs are not allowed."""
        with pytest.raises(ValueError, match="Contact IDs must be positive"):
            ContactRelationship(
                from_contact_id=-1,
                to_contact_id=2,
                relationship_type=RelationshipType.FRIEND,
            )

        with pytest.raises(ValueError, match="Contact IDs must be positive"):
            ContactRelationship(
                from_contact_id=1,
                to_contact_id=-2,
                relationship_type=RelationshipType.FRIEND,
            )

    def test_zero_contact_id_validation(self):
        """Test that zero contact IDs are not allowed."""
        with pytest.raises(ValueError, match="Contact IDs must be positive"):
            ContactRelationship(
                from_contact_id=0,
                to_contact_id=2,
                relationship_type=RelationshipType.FRIEND,
            )

        with pytest.raises(ValueError, match="Contact IDs must be positive"):
            ContactRelationship(
                from_contact_id=1,
                to_contact_id=0,
                relationship_type=RelationshipType.FRIEND,
            )

    def test_relationship_equality(self):
        """Test relationship equality based on contact IDs and type."""
        rel1 = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
        )
        rel2 = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
        )
        rel3 = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.COLLEAGUE,
        )

        assert rel1 == rel2
        assert rel1 != rel3

    def test_get_inverse_relationship_type(self):
        """Test getting inverse relationship types."""
        relationship = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.PARENT,
        )

        assert relationship.get_inverse_type() == RelationshipType.CHILD

        # Test symmetric relationships
        friend_rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
        )
        assert friend_rel.get_inverse_type() == RelationshipType.FRIEND

    def test_is_bidirectional(self):
        """Test checking if relationship type is bidirectional."""
        partner_rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.PARTNER,
        )
        assert partner_rel.is_bidirectional() is True

        parent_rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.PARENT,
        )
        assert parent_rel.is_bidirectional() is False

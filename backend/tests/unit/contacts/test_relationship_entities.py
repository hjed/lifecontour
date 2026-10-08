"""Unit tests for contact relationship entities."""

from datetime import datetime

import pytest
from core_shared.models.contacts.entities import ContactRelationship, RelationshipType


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
        from core_shared.models.contacts.exceptions import ContactValidationError

        with pytest.raises(
            ContactValidationError,
            match="Contact cannot have a relationship with itself",
        ):
            ContactRelationship(
                from_contact_id=1,
                to_contact_id=1,
                relationship_type=RelationshipType.FRIEND,
            )

    def test_negative_contact_id_validation(self):
        """Test that negative contact IDs are not allowed."""
        from core_shared.models.contacts.exceptions import ContactValidationError

        with pytest.raises(
            ContactValidationError, match="Contact IDs must be positive"
        ):
            ContactRelationship(
                from_contact_id=-1,
                to_contact_id=2,
                relationship_type=RelationshipType.FRIEND,
            )

        with pytest.raises(
            ContactValidationError, match="Contact IDs must be positive"
        ):
            ContactRelationship(
                from_contact_id=1,
                to_contact_id=-2,
                relationship_type=RelationshipType.FRIEND,
            )

    def test_zero_contact_id_validation(self):
        """Test that zero contact IDs are not allowed."""
        from core_shared.models.contacts.exceptions import ContactValidationError

        with pytest.raises(
            ContactValidationError, match="Contact IDs must be positive"
        ):
            ContactRelationship(
                from_contact_id=0,
                to_contact_id=2,
                relationship_type=RelationshipType.FRIEND,
            )

        with pytest.raises(
            ContactValidationError, match="Contact IDs must be positive"
        ):
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


class TestUserTargetedRelationship:
    """Test user-targeted relationship validation and semantics."""

    def test_create_user_targeted_relationship(self):
        """Test creating a valid user-targeted relationship (to_user=True, to_contact_id=None)."""
        relationship = ContactRelationship(
            from_contact_id=1,
            to_contact_id=None,
            relationship_type=RelationshipType.FRIEND,
            to_user=True,
        )

        assert relationship.from_contact_id == 1
        assert relationship.to_contact_id is None
        assert relationship.to_user is True
        assert relationship.relationship_type == RelationshipType.FRIEND

    def test_user_targeted_with_to_contact_id_fails(self):
        """Test that to_user=True + to_contact_id set raises validation error."""
        from core_shared.models.contacts.exceptions import ContactValidationError

        with pytest.raises(
            ContactValidationError,
            match="to_contact_id must be None when to_user is True",
        ):
            ContactRelationship(
                from_contact_id=1,
                to_contact_id=5,
                relationship_type=RelationshipType.FRIEND,
                to_user=True,
            )

    def test_contact_targeted_without_to_contact_id_fails(self):
        """Test that to_user=False + to_contact_id=None raises validation error."""
        from core_shared.models.contacts.exceptions import ContactValidationError

        with pytest.raises(
            ContactValidationError,
            match="to_contact_id is required when to_user is False",
        ):
            ContactRelationship(
                from_contact_id=1,
                to_contact_id=None,
                relationship_type=RelationshipType.FRIEND,
                to_user=False,
            )

    def test_user_targeted_no_self_reference_check(self):
        """Test that self-reference check does not apply when to_user=True."""
        # This should NOT raise, even though from_contact_id=1 and there's no "other" contact
        relationship = ContactRelationship(
            from_contact_id=1,
            to_contact_id=None,
            relationship_type=RelationshipType.COLLEAGUE,
            to_user=True,
        )
        assert relationship.to_user is True

    def test_user_targeted_from_contact_id_must_be_positive(self):
        """Test that from_contact_id must still be positive for user-targeted relationships."""
        from core_shared.models.contacts.exceptions import ContactValidationError

        with pytest.raises(
            ContactValidationError, match="from_contact_id must be positive"
        ):
            ContactRelationship(
                from_contact_id=0,
                to_contact_id=None,
                relationship_type=RelationshipType.FRIEND,
                to_user=True,
            )

    def test_user_targeted_equality(self):
        """Test user-targeted relationship equality (same from_contact_id + type + to_user)."""
        rel1 = ContactRelationship(
            from_contact_id=1,
            to_contact_id=None,
            relationship_type=RelationshipType.FRIEND,
            to_user=True,
        )
        rel2 = ContactRelationship(
            from_contact_id=1,
            to_contact_id=None,
            relationship_type=RelationshipType.FRIEND,
            to_user=True,
        )
        rel3 = ContactRelationship(
            from_contact_id=1,
            to_contact_id=None,
            relationship_type=RelationshipType.COLLEAGUE,
            to_user=True,
        )

        assert rel1 == rel2
        assert rel1 != rel3

    def test_user_targeted_not_equal_to_contact_targeted(self):
        """Test that user-targeted and contact-targeted relationships are not equal."""
        user_rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=None,
            relationship_type=RelationshipType.FRIEND,
            to_user=True,
        )
        contact_rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
        )

        assert user_rel != contact_rel

    def test_user_targeted_inverse_type(self):
        """Test that get_inverse_type works for user-targeted relationships."""
        rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=None,
            relationship_type=RelationshipType.PARENT,
            to_user=True,
        )
        assert rel.get_inverse_type() == RelationshipType.CHILD

    def test_user_targeted_is_bidirectional(self):
        """Test that is_bidirectional works for user-targeted relationships."""
        rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=None,
            relationship_type=RelationshipType.PARTNER,
            to_user=True,
        )
        assert rel.is_bidirectional() is True

    def test_default_to_user_is_false(self):
        """Test that to_user defaults to False for backward compatibility."""
        relationship = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
        )
        assert relationship.to_user is False


class TestFromPerspective:
    """relationship_type is what the to-side is to the from-side."""

    def test_from_side_gets_stored_type_of_other_party(self) -> None:
        """Row A→B PARENT: seen from A, B is A's parent."""
        rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.PARENT,
        )
        assert rel.from_perspective(1) == (2, RelationshipType.PARENT)

    def test_to_side_gets_inverse_type_of_other_party(self) -> None:
        """Row A→B PARENT: seen from B, A is B's child."""
        rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.PARENT,
        )
        assert rel.from_perspective(2) == (1, RelationshipType.CHILD)

    def test_user_targeted_other_party_is_the_user(self) -> None:
        """Row A→user PARENT: the user is A's parent, with no other contact id."""
        rel = ContactRelationship(
            from_contact_id=1,
            to_contact_id=None,
            relationship_type=RelationshipType.PARENT,
            to_user=True,
        )
        assert rel.from_perspective(1) == (None, RelationshipType.PARENT)

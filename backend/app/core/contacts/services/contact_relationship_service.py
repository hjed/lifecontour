"""Contact relationship service with business logic for managing relationships."""

from core_shared.models.contacts.entities import ContactRelationship, RelationshipType
from core_shared.models.contacts.exceptions import ContactValidationError

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
)
from app.core.contacts.models.repositories import (
    ContactRelationshipRepository,
    ContactRepository,
)


class ContactRelationshipService:
    """Service for managing contact relationships with business logic."""

    def __init__(
        self,
        contact_repo: ContactRepository,
        relationship_repo: ContactRelationshipRepository,
    ):
        self.contact_repo = contact_repo
        self.relationship_repo = relationship_repo

    async def create_relationship(
        self,
        from_contact_id: int,
        to_contact_id: int,
        relationship_type: RelationshipType,
        create_bidirectional: bool = False,
    ) -> ContactRelationship | list[ContactRelationship]:
        """
        Create a new relationship between contacts.

        Args:
            from_contact_id: ID of the contact initiating the relationship
            to_contact_id: ID of the contact receiving the relationship
            relationship_type: Type of relationship
            create_bidirectional: Whether to create the inverse relationship

        Returns:
            Single relationship or list of relationships if bidirectional

        Raises:
            ContactValidationError: If validation fails
            ContactNotFoundError: If either contact doesn't exist
        """
        # Validate self-relationship
        if from_contact_id == to_contact_id:
            raise ContactValidationError(
                "relationship", "Contact cannot have a relationship with itself"
            )

        # Validate both contacts exist
        from_contact = await self.contact_repo.find_by_id(from_contact_id)
        if not from_contact:
            raise ContactNotFoundError(from_contact_id)

        to_contact = await self.contact_repo.find_by_id(to_contact_id)
        if not to_contact:
            raise ContactNotFoundError(to_contact_id)

        # Create the primary relationship
        relationship = ContactRelationship(
            from_contact_id=from_contact_id,
            to_contact_id=to_contact_id,
            relationship_type=relationship_type,
        )

        created_relationship = await self.relationship_repo.create(relationship)

        # Create bidirectional relationship if requested
        if create_bidirectional:
            inverse_relationship = ContactRelationship(
                from_contact_id=to_contact_id,
                to_contact_id=from_contact_id,
                relationship_type=relationship_type.get_inverse_type(),
            )

            created_inverse = await self.relationship_repo.create(inverse_relationship)
            return [created_relationship, created_inverse]

        return created_relationship

    async def get_relationships_for_contact(
        self, contact_id: int
    ) -> list[ContactRelationship]:
        """
        Get all relationships for a contact.

        Args:
            contact_id: ID of the contact

        Returns:
            List of relationships (both from and to the contact)
        """
        return await self.relationship_repo.get_relationships_for_contact(contact_id)

    async def get_relationships_from_contact(
        self, contact_id: int
    ) -> list[ContactRelationship]:
        """
        Get relationships where the contact is the initiator.

        Args:
            contact_id: ID of the contact

        Returns:
            List of relationships from the contact
        """
        return await self.relationship_repo.get_relationships_from_contact(contact_id)

    async def get_relationships_to_contact(
        self, contact_id: int
    ) -> list[ContactRelationship]:
        """
        Get relationships where the contact is the recipient.

        Args:
            contact_id: ID of the contact

        Returns:
            List of relationships to the contact
        """
        return await self.relationship_repo.get_relationships_to_contact(contact_id)

    async def update_relationship(
        self,
        relationship_id: int,
        relationship_type: RelationshipType,
    ) -> ContactRelationship:
        """
        Update an existing relationship.

        Args:
            relationship_id: ID of the relationship to update
            relationship_type: New relationship type

        Returns:
            Updated relationship

        Raises:
            ContactValidationError: If relationship doesn't exist
        """
        # Validate relationship exists
        existing_relationship = await self.relationship_repo.get_by_id(relationship_id)
        if not existing_relationship:
            raise ContactValidationError(
                "relationship", f"Relationship with ID {relationship_id} not found"
            )

        # Update the relationship
        updated_relationship = ContactRelationship(
            id=existing_relationship.id,
            from_contact_id=existing_relationship.from_contact_id,
            to_contact_id=existing_relationship.to_contact_id,
            relationship_type=relationship_type,
            created_at=existing_relationship.created_at,
            updated_at=existing_relationship.updated_at,
        )

        return await self.relationship_repo.update(updated_relationship)

    async def delete_relationship(
        self,
        relationship_id: int,
    ) -> None:
        """
        Delete a relationship.

        Args:
            relationship_id: ID of the relationship to delete

        Raises:
            ContactValidationError: If relationship doesn't exist
        """
        # Validate relationship exists
        existing_relationship = await self.relationship_repo.get_by_id(relationship_id)
        if not existing_relationship:
            raise ContactValidationError(
                "relationship", f"Relationship with ID {relationship_id} not found"
            )

        await self.relationship_repo.delete(relationship_id)

    async def delete_all_relationships_for_contact(
        self,
        contact_id: int,
    ) -> None:
        """
        Delete all relationships for a contact.

        Args:
            contact_id: ID of the contact
        """
        relationships = await self.get_relationships_for_contact(contact_id)
        for relationship in relationships:
            if relationship.id:
                await self.relationship_repo.delete(relationship.id)

    async def get_relationship_by_id(
        self, relationship_id: int
    ) -> ContactRelationship | None:
        """
        Get a relationship by ID.

        Args:
            relationship_id: ID of the relationship

        Returns:
            Relationship or None if not found
        """
        return await self.relationship_repo.get_by_id(relationship_id)

    async def validate_partner_relationship_compatibility(
        self,
        from_contact_id: int,
        to_contact_id: int,
        relationship_type: RelationshipType,
    ) -> None:
        """
        Validate that a partner relationship doesn't conflict with existing ones.

        Currently only validates partner relationship conflicts. This method
        can be expanded to include other relationship compatibility rules.

        Args:
            from_contact_id: ID of the contact initiating the relationship
            to_contact_id: ID of the contact receiving the relationship
            relationship_type: Type of relationship to validate

        Raises:
            ContactValidationError: If partner relationship conflicts exist
        """
        # Get existing relationships between these contacts
        existing_relationships = (
            await self.relationship_repo.get_relationships_for_contact(from_contact_id)
        )

        # Check for conflicting relationships
        for rel in existing_relationships:
            if (
                rel.from_contact_id == from_contact_id
                and rel.to_contact_id == to_contact_id
            ) or (
                rel.from_contact_id == to_contact_id
                and rel.to_contact_id == from_contact_id
            ):
                # Check for incompatible relationship types
                if (
                    relationship_type == RelationshipType.PARTNER
                    and rel.relationship_type == RelationshipType.PARTNER
                ):
                    raise ContactValidationError(
                        "relationship",
                        "Partner relationship already exists between these contacts",
                    )

    async def resolve_relationship_contact_names(
        self,
        relationships: list[ContactRelationship],
        viewing_contact_id: int,
    ) -> list[ContactRelationship]:
        """
        Populate to_contact_name on each relationship with the other contact's display name.

        For each relationship, determines the "other" contact (the one that is not
        the viewing contact) and sets to_contact_name to their display name.

        Args:
            relationships: List of relationships to resolve names for
            viewing_contact_id: ID of the contact whose detail page is being viewed

        Returns:
            The same list of relationships with to_contact_name populated
        """
        # Collect unique contact IDs that need resolution
        contact_ids: set[int] = set()
        for rel in relationships:
            if rel.from_contact_id == viewing_contact_id:
                contact_ids.add(rel.to_contact_id)
            else:
                contact_ids.add(rel.from_contact_id)

        # Batch-fetch contacts
        contact_names: dict[int, str] = {}
        for cid in contact_ids:
            contact = await self.contact_repo.find_by_id(cid)
            if contact:
                contact_names[cid] = contact.get_display_name()

        # Set to_contact_name on each relationship
        for rel in relationships:
            other_id = (
                rel.to_contact_id
                if rel.from_contact_id == viewing_contact_id
                else rel.from_contact_id
            )
            rel.to_contact_name = contact_names.get(other_id)

        return relationships

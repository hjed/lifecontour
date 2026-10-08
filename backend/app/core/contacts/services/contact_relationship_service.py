"""Contact relationship service with business logic for managing relationships."""

from core_shared.models.contacts.entities import ContactRelationship, RelationshipType
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.value_objects import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import (
    ContactRelationshipCreated,
    ContactRelationshipDeleted,
    ContactRelationshipUpdated,
)
from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
)
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    ContactRelationshipRepository,
    ContactRepository,
)
from app.infrastructure.unit_of_work import transactional


class ContactRelationshipService:
    """Service for managing contact relationships with business logic.

    ITER12-003 Phase 2: relationship history is produced by the event-driven
    HistoryProjectionConsumer from the ContactRelationship* events published here,
    so the service no longer writes history synchronously.
    """

    def __init__(
        self,
        contact_repo: ContactRepository,
        relationship_repo: ContactRelationshipRepository,
        event_publisher: ContactEventPublisher,
    ):
        self.contact_repo = contact_repo
        self.relationship_repo = relationship_repo
        self.event_publisher = event_publisher

    @transactional
    async def create_relationship(
        self,
        from_contact_id: int,
        to_contact_id: int | None,
        relationship_type: RelationshipType,
        create_bidirectional: bool = False,
        *,
        transaction: AsyncConnection,
        to_user: bool = False,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
        user_id: str,
    ) -> ContactRelationship | list[ContactRelationship]:
        """
        Create a new relationship between contacts or from a contact to the user.

        Args:
            from_contact_id: ID of the contact initiating the relationship
            to_contact_id: ID of the target contact (None when to_user=True)
            relationship_type: Type of relationship
            create_bidirectional: Whether to create the inverse relationship
            transaction: Active request connection; required (keyword-only) so
                @transactional commits this write before the response (#945).
            to_user: Whether this relationship targets the user

        Returns:
            Single relationship or list of relationships if bidirectional

        Raises:
            ContactValidationError: If validation fails
            ContactNotFoundError: If either contact doesn't exist
        """
        # Validate the from-contact exists
        from_contact = await self.contact_repo.find_by_id(
            from_contact_id, user_id=user_id
        )
        if not from_contact:
            raise ContactNotFoundError(from_contact_id)

        if to_user:
            # User-targeted relationship: no to_contact_id needed
            if to_contact_id is not None:
                raise ContactValidationError(
                    "relationship",
                    "to_contact_id must not be provided when to_user is True",
                )
            if create_bidirectional:
                raise ContactValidationError(
                    "relationship",
                    "create_bidirectional must be False when to_user is True",
                )

            relationship = ContactRelationship(
                from_contact_id=from_contact_id,
                to_contact_id=None,
                relationship_type=relationship_type,
                to_user=True,
            )
            created = await self.relationship_repo.create(relationship)
            if created.id is None:
                raise ContactValidationError(
                    "relationship",
                    "created relationship is missing an id",
                )
            await self.event_publisher.publish(
                ContactRelationshipCreated(
                    relationship_id=created.id,
                    from_contact_id=created.from_contact_id,
                    to_contact_id=created.to_contact_id,
                    relationship_type=created.relationship_type.value,
                    to_user=created.to_user,
                    source=source,
                    changed_by=changed_by,
                )
            )

            return created
        else:
            # Contact-to-contact relationship
            if to_contact_id is None:
                raise ContactValidationError(
                    "relationship",
                    "to_contact_id is required when to_user is False",
                )

            # Validate self-relationship
            if from_contact_id == to_contact_id:
                raise ContactValidationError(
                    "relationship",
                    "Contact cannot have a relationship with itself",
                )

            to_contact = await self.contact_repo.find_by_id(
                to_contact_id, user_id=user_id
            )
            if not to_contact:
                raise ContactNotFoundError(to_contact_id)

            # Create the primary relationship
            relationship = ContactRelationship(
                from_contact_id=from_contact_id,
                to_contact_id=to_contact_id,
                relationship_type=relationship_type,
            )

            created_relationship = await self.relationship_repo.create(relationship)

            if created_relationship.id is None:
                raise ContactValidationError(
                    "relationship",
                    "created relationship is missing an id",
                )
            await self.event_publisher.publish(
                ContactRelationshipCreated(
                    relationship_id=created_relationship.id,
                    from_contact_id=created_relationship.from_contact_id,
                    to_contact_id=created_relationship.to_contact_id,
                    relationship_type=created_relationship.relationship_type.value,
                    to_user=created_relationship.to_user,
                    source=source,
                    changed_by=changed_by,
                )
            )

            # Create bidirectional relationship if requested
            if create_bidirectional:
                inverse_relationship = ContactRelationship(
                    from_contact_id=to_contact_id,
                    to_contact_id=from_contact_id,
                    relationship_type=relationship_type.get_inverse_type(),
                )

                created_inverse = await self.relationship_repo.create(
                    inverse_relationship
                )
                if created_inverse.id is None:
                    raise ContactValidationError(
                        "relationship",
                        "created inverse relationship is missing an id",
                    )
                await self.event_publisher.publish(
                    ContactRelationshipCreated(
                        relationship_id=created_inverse.id,
                        from_contact_id=created_inverse.from_contact_id,
                        to_contact_id=created_inverse.to_contact_id,
                        relationship_type=created_inverse.relationship_type.value,
                        to_user=created_inverse.to_user,
                        source=source,
                        changed_by=changed_by,
                    )
                )

                return [created_relationship, created_inverse]

            return created_relationship

    async def get_relationships_for_contact(
        self, contact_id: int, *, user_id: str
    ) -> list[ContactRelationship]:
        """
        Get all relationships for a contact.

        Args:
            contact_id: ID of the contact

        Returns:
            List of relationships (both from and to the contact)

        Raises:
            ContactNotFoundError: The contact is missing or another user's.
        """
        if not await self.contact_repo.contact_exists(contact_id, user_id=user_id):
            raise ContactNotFoundError(contact_id)
        return await self.relationship_repo.get_relationships_for_contact(contact_id)

    @transactional
    async def update_relationship(
        self,
        relationship_id: int,
        relationship_type: RelationshipType,
        *,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
        user_id: str,
    ) -> ContactRelationship:
        """
        Update an existing relationship.

        Args:
            relationship_id: ID of the relationship to update
            relationship_type: New relationship type
            transaction: Active request connection; required (keyword-only) so
                @transactional commits this write before the response (#945).

        Returns:
            Updated relationship

        Raises:
            ContactValidationError: If relationship doesn't exist
        """
        # Validate relationship exists and is the user's
        existing_relationship = await self.get_relationship_by_id(
            relationship_id, user_id=user_id
        )
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
            to_user=existing_relationship.to_user,
            created_at=existing_relationship.created_at,
            updated_at=existing_relationship.updated_at,
        )

        updated = await self.relationship_repo.update(updated_relationship)

        if updated.id is None:
            raise ContactValidationError(
                "relationship",
                "updated relationship is missing an id",
            )
        # Compute the (old, new) field change so both the published event and the
        # dual-write history record the same diff; an unchanged type yields an
        # empty changed_fields (the projection then writes no row).
        relationship_changed_fields: dict[str, tuple[str, str]] = {}
        if updated.relationship_type != existing_relationship.relationship_type:
            relationship_changed_fields["relationship_type"] = (
                existing_relationship.relationship_type.value,
                updated.relationship_type.value,
            )

        await self.event_publisher.publish(
            ContactRelationshipUpdated(
                relationship_id=updated.id,
                from_contact_id=updated.from_contact_id,
                to_contact_id=updated.to_contact_id,
                relationship_type=updated.relationship_type.value,
                to_user=updated.to_user,
                changed_fields=relationship_changed_fields,
                source=source,
                changed_by=changed_by,
            )
        )

        return updated

    @transactional
    async def delete_relationship(
        self,
        relationship_id: int,
        *,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
        user_id: str,
    ) -> None:
        """
        Delete a relationship.

        Args:
            relationship_id: ID of the relationship to delete
            transaction: Active request connection; required (keyword-only) so
                @transactional commits this write before the response (#945).

        Raises:
            ContactValidationError: If relationship doesn't exist
        """
        # Validate relationship exists and is the user's
        existing_relationship = await self.get_relationship_by_id(
            relationship_id, user_id=user_id
        )
        if not existing_relationship:
            raise ContactValidationError(
                "relationship", f"Relationship with ID {relationship_id} not found"
            )

        await self.relationship_repo.delete(relationship_id)

        if existing_relationship.id is None:
            raise ContactValidationError(
                "relationship",
                f"Relationship with ID {relationship_id} has no persisted id; cannot publish delete event",
            )
        await self.event_publisher.publish(
            ContactRelationshipDeleted(
                relationship_id=existing_relationship.id,
                from_contact_id=existing_relationship.from_contact_id,
                to_contact_id=existing_relationship.to_contact_id,
                relationship_type=existing_relationship.relationship_type.value,
                to_user=existing_relationship.to_user,
                source=source,
                changed_by=changed_by,
            )
        )

    async def get_relationship_by_id(
        self, relationship_id: int, *, user_id: str
    ) -> ContactRelationship | None:
        """
        Get a relationship by ID.

        Args:
            relationship_id: ID of the relationship

        Returns:
            Relationship, or None if it is missing or not ``user_id``'s

        A relationship carries no owner of its own: it is the user's when the
        contact it starts from is. Both ends of one belong to the same owner, as
        creation proves.
        """
        relationship = await self.relationship_repo.get_by_id(relationship_id)
        if relationship is None or not await self.contact_repo.contact_exists(
            relationship.from_contact_id, user_id=user_id
        ):
            return None
        return relationship

    async def resolve_relationship_contact_names(
        self,
        relationships: list[ContactRelationship],
        viewing_contact_id: int,
        *,
        user_id: str,
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
            other_id, _ = rel.from_perspective(viewing_contact_id)
            if other_id is not None:
                contact_ids.add(other_id)

        # Batch-fetch contacts
        contact_names: dict[int, str] = {}
        for cid in contact_ids:
            contact = await self.contact_repo.find_by_id(cid, user_id=user_id)
            if contact:
                contact_names[cid] = contact.get_display_name()

        import copy

        resolved_relationships = []
        # Set to_contact_name on each relationship
        for rel in relationships:
            resolved_rel = copy.copy(rel)
            if resolved_rel.to_user:
                # User-targeted relationship: show "You" as the target name
                resolved_rel.to_contact_name = "You"
            elif resolved_rel.to_contact_id == viewing_contact_id:
                # The viewing contact is the target of the relationship.
                # Invert the relationship so the viewer sees it from their perspective
                other_id = resolved_rel.from_contact_id
                resolved_rel.relationship_type = (
                    resolved_rel.relationship_type.get_inverse_type()
                )
                # Swap the IDs so it is clearly directional from the viewing contact
                resolved_rel.to_contact_id = other_id
                resolved_rel.from_contact_id = viewing_contact_id
                resolved_rel.to_contact_name = contact_names.get(other_id)
            else:
                other_id_or_none = resolved_rel.to_contact_id
                resolved_rel.to_contact_name = (
                    contact_names.get(other_id_or_none)
                    if other_id_or_none is not None
                    else None
                )
            resolved_relationships.append(resolved_rel)

        return resolved_relationships

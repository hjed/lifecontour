"""SQL implementation of ContactRelationshipRepository."""

from typing import Any

from core_shared.models.contacts.entities import ContactRelationship, RelationshipType
from core_shared.models.contacts.exceptions import ContactValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import ContactRelationshipRepository


class SqlContactRelationshipRepository(ContactRelationshipRepository):
    """SQL implementation of ContactRelationshipRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    async def create(self, relationship: ContactRelationship) -> ContactRelationship:
        """Create a new contact relationship."""
        query = text(
            """
            INSERT INTO contact_relationships
            (from_contact_id, to_contact_id, relationship_type, to_user)
            VALUES (:from_contact_id, :to_contact_id, :relationship_type, :to_user)
            RETURNING id, created_at, updated_at
        """
        )

        try:
            result = await self.conn.execute(
                query,
                {
                    "from_contact_id": relationship.from_contact_id,
                    "to_contact_id": relationship.to_contact_id,
                    "relationship_type": relationship.relationship_type.value,
                    "to_user": relationship.to_user,
                },
            )
            row = result.fetchone()

            if not row:
                raise ContactValidationError(
                    "relationship", "Failed to create relationship"
                )

            # Return the relationship with the assigned ID and timestamps
            return ContactRelationship(
                id=row.id,
                from_contact_id=relationship.from_contact_id,
                to_contact_id=relationship.to_contact_id,
                relationship_type=relationship.relationship_type,
                to_user=relationship.to_user,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

        except IntegrityError as e:
            error_str = str(e)
            if (
                "uq_contact_relationships_contact_target" in error_str
                or "uq_contact_relationships_user_target" in error_str
            ):
                if relationship.to_user:
                    raise ContactValidationError(
                        "relationship",
                        f"User-targeted relationship of type '{relationship.relationship_type.value}' already exists for contact {relationship.from_contact_id}",
                    ) from e
                else:
                    raise ContactValidationError(
                        "relationship",
                        f"Relationship already exists between contacts {relationship.from_contact_id} and {relationship.to_contact_id}",
                    ) from e
            elif "ck_contact_relationships_no_self_reference" in error_str:
                raise ContactValidationError(
                    "relationship", "Contact cannot have a relationship with itself"
                ) from e
            else:
                raise ContactValidationError(
                    "relationship", "Failed to create relationship"
                ) from e

    def _row_to_entity(self, row: Any) -> ContactRelationship:
        """Convert a database row to a ContactRelationship entity."""
        return ContactRelationship(
            id=row.id,
            from_contact_id=row.from_contact_id,
            to_contact_id=row.to_contact_id,
            relationship_type=RelationshipType(row.relationship_type),
            to_user=row.to_user,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_by_id(self, relationship_id: int) -> ContactRelationship | None:
        """Get a relationship by ID."""
        query = text(
            """
            SELECT id, from_contact_id, to_contact_id, relationship_type, to_user, created_at, updated_at
            FROM contact_relationships
            WHERE id = :relationship_id
        """
        )
        result = await self.conn.execute(query, {"relationship_id": relationship_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def get_relationships_for_contact(
        self, contact_id: int
    ) -> list[ContactRelationship]:
        """Get all relationships for a specific contact (from, to, or user-targeted)."""
        query = text(
            """
            SELECT id, from_contact_id, to_contact_id, relationship_type, to_user, created_at, updated_at
            FROM contact_relationships
            WHERE from_contact_id = :contact_id OR to_contact_id = :contact_id
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})
        rows = result.fetchall()

        return [self._row_to_entity(row) for row in rows]

    async def get_relationships_from_contact(
        self, contact_id: int
    ) -> list[ContactRelationship]:
        """Get relationships where the contact is the 'from' contact."""
        query = text(
            """
            SELECT id, from_contact_id, to_contact_id, relationship_type, to_user, created_at, updated_at
            FROM contact_relationships
            WHERE from_contact_id = :contact_id
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})
        rows = result.fetchall()

        return [self._row_to_entity(row) for row in rows]

    async def get_relationships_to_contact(
        self, contact_id: int
    ) -> list[ContactRelationship]:
        """Get relationships where the contact is the 'to' contact."""
        query = text(
            """
            SELECT id, from_contact_id, to_contact_id, relationship_type, to_user, created_at, updated_at
            FROM contact_relationships
            WHERE to_contact_id = :contact_id
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})
        rows = result.fetchall()

        return [self._row_to_entity(row) for row in rows]

    async def update(self, relationship: ContactRelationship) -> ContactRelationship:
        """Update an existing relationship."""
        if relationship.id is None:
            raise ContactValidationError(
                "id", "Relationship ID is required for updates"
            )

        query = text(
            """
            UPDATE contact_relationships
            SET relationship_type = :relationship_type, updated_at = CURRENT_TIMESTAMP
            WHERE id = :relationship_id
            RETURNING id, from_contact_id, to_contact_id, relationship_type, to_user, created_at, updated_at
        """
        )

        try:
            result = await self.conn.execute(
                query,
                {
                    "relationship_id": relationship.id,
                    "relationship_type": relationship.relationship_type.value,
                },
            )
            row = result.fetchone()

            if not row:
                raise ContactValidationError(
                    "relationship", f"Relationship with ID {relationship.id} not found"
                )

            return self._row_to_entity(row)

        except IntegrityError as e:
            error_str = str(e)
            if (
                "uq_contact_relationships_contact_target" in error_str
                or "uq_contact_relationships_user_target" in error_str
            ):
                raise ContactValidationError(
                    "relationship",
                    f"Relationship already exists between contacts {relationship.from_contact_id} and {relationship.to_contact_id}",
                ) from e
            else:
                raise ContactValidationError(
                    "relationship", "Failed to update relationship"
                ) from e

    async def delete(self, relationship_id: int) -> None:
        """Delete a relationship by ID."""
        query = text(
            """
            DELETE FROM contact_relationships
            WHERE id = :relationship_id
        """
        )
        result = await self.conn.execute(query, {"relationship_id": relationship_id})

        if result.rowcount == 0:
            raise ContactValidationError(
                "relationship", f"Relationship with ID {relationship_id} not found"
            )

    async def relationship_exists(
        self,
        from_contact_id: int,
        to_contact_id: int | None,
        relationship_type: str,
        *,
        to_user: bool = False,
    ) -> bool:
        """Check if a specific relationship already exists."""
        if to_user:
            query = text(
                """
                SELECT 1 FROM contact_relationships
                WHERE from_contact_id = :from_contact_id
                AND to_user = true
                AND relationship_type = :relationship_type
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "from_contact_id": from_contact_id,
                    "relationship_type": relationship_type,
                },
            )
        else:
            query = text(
                """
                SELECT 1 FROM contact_relationships
                WHERE from_contact_id = :from_contact_id
                AND to_contact_id = :to_contact_id
                AND relationship_type = :relationship_type
                AND to_user = false
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "from_contact_id": from_contact_id,
                    "to_contact_id": to_contact_id,
                    "relationship_type": relationship_type,
                },
            )
        return result.fetchone() is not None

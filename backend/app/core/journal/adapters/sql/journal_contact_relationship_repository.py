"""SQL implementation of JournalContactRelationshipRepository."""

from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import JournalContactRelationshipRepository


class SqlJournalContactRelationshipRepository(JournalContactRelationshipRepository):
    """SQL implementation of journal-contact relationship repository."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    async def create(
        self, relationship: JournalContactRelationship
    ) -> JournalContactRelationship:
        """Create a new journal-contact relationship."""
        query = text(
            """
            INSERT INTO journal_contact_relationships
            (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            RETURNING created_at
        """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": relationship.journal_id,
                "contact_id": relationship.contact_id,
                "relationship_type": relationship.relationship_type.value,
            },
        )
        row = result.fetchone()
        if row is not None:
            relationship.created_at = row.created_at

        return relationship

    async def delete(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
    ) -> None:
        """Delete a specific journal-contact relationship."""
        query = text(
            """
            DELETE FROM journal_contact_relationships
            WHERE journal_id = :journal_id
            AND contact_id = :contact_id
            AND relationship_type = :relationship_type
        """
        )
        await self.conn.execute(
            query,
            {
                "journal_id": journal_id,
                "contact_id": contact_id,
                "relationship_type": relationship_type.value,
            },
        )

    async def get_by_journal(self, journal_id: int) -> list[JournalContactRelationship]:
        """Get all relationships for a journal."""
        query = text(
            """
            SELECT journal_id, contact_id, relationship_type, created_at
            FROM journal_contact_relationships
            WHERE journal_id = :journal_id
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        rows = result.fetchall()

        return [
            JournalContactRelationship(
                journal_id=row.journal_id,
                contact_id=row.contact_id,
                relationship_type=JournalContactRelationshipType(row.relationship_type),
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def get_by_contact(self, contact_id: int) -> list[JournalContactRelationship]:
        """Get all relationships for a contact."""
        query = text(
            """
            SELECT journal_id, contact_id, relationship_type, created_at
            FROM journal_contact_relationships
            WHERE contact_id = :contact_id
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})
        rows = result.fetchall()

        return [
            JournalContactRelationship(
                journal_id=row.journal_id,
                contact_id=row.contact_id,
                relationship_type=JournalContactRelationshipType(row.relationship_type),
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def get_by_journal_and_type(
        self, journal_id: int, relationship_type: JournalContactRelationshipType
    ) -> list[JournalContactRelationship]:
        """Get all relationships of a specific type for a journal."""
        query = text(
            """
            SELECT journal_id, contact_id, relationship_type, created_at
            FROM journal_contact_relationships
            WHERE journal_id = :journal_id
            AND relationship_type = :relationship_type
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": journal_id,
                "relationship_type": relationship_type.value,
            },
        )
        rows = result.fetchall()

        return [
            JournalContactRelationship(
                journal_id=row.journal_id,
                contact_id=row.contact_id,
                relationship_type=JournalContactRelationshipType(row.relationship_type),
                created_at=row.created_at,
            )
            for row in rows
        ]

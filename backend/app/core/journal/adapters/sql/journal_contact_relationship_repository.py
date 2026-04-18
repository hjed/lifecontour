"""SQL implementation of JournalContactRelationshipRepository."""

from datetime import datetime

from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.contact_event_role import ContactEventRole
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import JournalContactRelationshipRepository


class SqlJournalContactRelationshipRepository(JournalContactRelationshipRepository):
    """SQL implementation of journal-contact relationship repository."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    @staticmethod
    def _row_to_entity(row: object) -> JournalContactRelationship:
        """Convert a database row to a JournalContactRelationship entity."""
        return JournalContactRelationship(
            journal_id=row.journal_id,  # type: ignore[attr-defined]
            contact_id=row.contact_id,  # type: ignore[attr-defined]
            relationship_type=JournalContactRelationshipType(
                row.relationship_type  # type: ignore[attr-defined]
            ),
            created_at=row.created_at,  # type: ignore[attr-defined]
            status=(
                AttendeeStatus(row.status)  # type: ignore[attr-defined]
                if row.status is not None  # type: ignore[attr-defined]
                else None
            ),
            role=(
                ContactEventRole(row.role)  # type: ignore[attr-defined]
                if row.role is not None  # type: ignore[attr-defined]
                else None
            ),
        )

    async def create(
        self, relationship: JournalContactRelationship
    ) -> JournalContactRelationship:
        """Create a new journal-contact relationship."""
        query = text(
            """
            INSERT INTO journal_contact_relationships
            (journal_id, contact_id, relationship_type, status, role)
            VALUES (:journal_id, :contact_id, :relationship_type, :status, :role)
            RETURNING created_at
        """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": relationship.journal_id,
                "contact_id": relationship.contact_id,
                "relationship_type": relationship.relationship_type.value,
                "status": (relationship.status.value if relationship.status else None),
                "role": relationship.role.value if relationship.role else None,
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
            SELECT journal_id, contact_id, relationship_type, created_at,
                   status, role
            FROM journal_contact_relationships
            WHERE journal_id = :journal_id
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        rows = result.fetchall()

        return [self._row_to_entity(row) for row in rows]

    async def get_by_contact(self, contact_id: int) -> list[JournalContactRelationship]:
        """Get all relationships for a contact."""
        query = text(
            """
            SELECT journal_id, contact_id, relationship_type, created_at,
                   status, role
            FROM journal_contact_relationships
            WHERE contact_id = :contact_id
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})
        rows = result.fetchall()

        return [self._row_to_entity(row) for row in rows]

    async def get_by_journal_and_type(
        self, journal_id: int, relationship_type: JournalContactRelationshipType
    ) -> list[JournalContactRelationship]:
        """Get all relationships of a specific type for a journal."""
        query = text(
            """
            SELECT journal_id, contact_id, relationship_type, created_at,
                   status, role
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

        return [self._row_to_entity(row) for row in rows]

    async def update_status(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        status: AttendeeStatus,
    ) -> JournalContactRelationship | None:
        """Update the attendee status of a journal-contact relationship."""
        query = text(
            """
            UPDATE journal_contact_relationships
            SET status = :status
            WHERE journal_id = :journal_id
            AND contact_id = :contact_id
            AND relationship_type = :relationship_type
            RETURNING journal_id, contact_id, relationship_type,
                      created_at, status, role
        """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": journal_id,
                "contact_id": contact_id,
                "relationship_type": relationship_type.value,
                "status": status.value,
            },
        )
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_entity(row)

    async def find_attending_for_past_events(
        self,
        cutoff_time: datetime,
        batch_size: int = 100,
    ) -> list[JournalContactRelationship]:
        """Find relationships with ATTENDING status on past events.

        Joins with the journals table to check event_date_range_end.
        """
        query = text(
            """
            SELECT jcr.journal_id, jcr.contact_id, jcr.relationship_type,
                   jcr.created_at, jcr.status, jcr.role
            FROM journal_contact_relationships jcr
            INNER JOIN journals j ON j.id = jcr.journal_id
            WHERE jcr.status = :attending_status
            AND j.event_date_range_end < :cutoff_time
            ORDER BY j.event_date_range_end ASC
            LIMIT :batch_size
        """
        )
        result = await self.conn.execute(
            query,
            {
                "attending_status": AttendeeStatus.ATTENDING.value,
                "cutoff_time": cutoff_time,
                "batch_size": batch_size,
            },
        )
        rows = result.fetchall()
        return [self._row_to_entity(row) for row in rows]

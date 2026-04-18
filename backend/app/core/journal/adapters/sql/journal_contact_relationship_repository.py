"""SQL implementation of JournalContactRelationshipRepository."""

from datetime import datetime
from typing import Any

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

    async def update(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        updates: dict[str, Any],
    ) -> JournalContactRelationship | None:
        """Update an existing relationship's status and/or role."""
        if not updates:
            # If nothing to update, just return the current one or fetch it?
            # But the caller should ensure updates is not empty.
            raise ValueError("No fields provided for update")

        set_clauses = []
        params: dict[str, Any] = {
            "journal_id": journal_id,
            "contact_id": contact_id,
            "relationship_type": relationship_type.value,
        }

        if "status" in updates:
            set_clauses.append("status = :status")
            params["status"] = updates["status"].value if updates["status"] else None

        if "role" in updates:
            set_clauses.append("role = :role")
            params["role"] = updates["role"].value if updates["role"] else None

        query_str = f"""
            UPDATE journal_contact_relationships
            SET {", ".join(set_clauses)}
            WHERE journal_id = :journal_id
            AND contact_id = :contact_id
            AND relationship_type = :relationship_type
            RETURNING journal_id, contact_id, relationship_type, status, role, created_at
        """

        result = await self.conn.execute(text(query_str), params)
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def transition_attending_to_attended(
        self, before: datetime, batch_size: int = 500
    ) -> int:
        """Bulk transition ATTENDING status to ATTENDED for past events."""
        query = text(
            """
            WITH to_update AS (
                SELECT r.journal_id, r.contact_id, r.relationship_type
                FROM journal_contact_relationships r
                JOIN journals j on j.id = r.journal_id
                WHERE r.status = 'ATTENDING'
                AND j.event_date_range_end < :before
                LIMIT :batch_size
            )
            UPDATE journal_contact_relationships r
            SET status = 'ATTENDED'
            FROM to_update t
            WHERE r.journal_id = t.journal_id
            AND r.contact_id = t.contact_id
            AND r.relationship_type = t.relationship_type
            """
        )
        result = await self.conn.execute(
            query, {"before": before, "batch_size": batch_size}
        )
        return result.rowcount

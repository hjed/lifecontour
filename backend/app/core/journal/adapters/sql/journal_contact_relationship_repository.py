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

from app.core.journal.adapters.sql.journal_touch import lock_journal, touch_journal
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
        # Parent lock before the child write, so this cannot deadlock against a
        # conditional update that locks the journal first; see ``lock_journal``.
        await lock_journal(self.conn, relationship.journal_id)

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

        # A journal's contact relationships are part of what a read of it
        # returns, so the aggregate's version moves with them; see
        # ``touch_journal``.
        await touch_journal(self.conn, relationship.journal_id)

        return relationship

    async def delete(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
    ) -> None:
        """Delete a specific journal-contact relationship."""
        await lock_journal(self.conn, journal_id)

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
        await touch_journal(self.conn, journal_id)

    async def repoint_contact(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's journal links onto the survivor.

        Source rows that collide with an existing survivor row on the
        ``(journal_id, contact_id, relationship_type)`` composite primary key are
        deleted first (survivor's link wins), then the remaining source rows are
        re-pointed to the survivor.
        """
        params = {"source_id": source_id, "survivor_id": survivor_id}

        await transaction.execute(
            text(
                """
                DELETE FROM journal_contact_relationships src
                WHERE src.contact_id = :source_id
                AND EXISTS (
                    SELECT 1 FROM journal_contact_relationships tgt
                    WHERE tgt.contact_id = :survivor_id
                    AND tgt.journal_id = src.journal_id
                    AND tgt.relationship_type = src.relationship_type
                )
                """
            ),
            params,
        )

        await transaction.execute(
            text(
                """
                UPDATE journal_contact_relationships
                SET contact_id = :survivor_id
                WHERE contact_id = :source_id
                """
            ),
            params,
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
        expected_current_status: AttendeeStatus | None = None,
    ) -> JournalContactRelationship | None:
        """Update the attendee status of a journal-contact relationship.

        When expected_current_status is provided, the update is applied
        only if the current row status still matches that expected value.
        This provides atomic transitions inside SQL.
        """
        status_condition = ""
        params = {
            "journal_id": journal_id,
            "contact_id": contact_id,
            "relationship_type": relationship_type.value,
            "status": status.value,
        }

        if expected_current_status is not None:
            status_condition = " AND status = :expected_current_status"
            params["expected_current_status"] = expected_current_status.value

        query = text(
            f"""
            UPDATE journal_contact_relationships
            SET status = :status
            WHERE journal_id = :journal_id
            AND contact_id = :contact_id
            AND relationship_type = :relationship_type{status_condition}
            RETURNING journal_id, contact_id, relationship_type,
                      created_at, status, role
        """
        )
        result = await self.conn.execute(query, params)
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_entity(row)

    async def update_attributes(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        status: AttendeeStatus | None = None,
        role: ContactEventRole | None = None,
        update_status: bool = False,
        update_role: bool = False,
    ) -> JournalContactRelationship | None:
        """Update the attributes (status, role) of a journal-contact relationship."""
        await lock_journal(self.conn, journal_id)

        set_clauses = []
        from typing import Any

        params: dict[str, Any] = {
            "journal_id": journal_id,
            "contact_id": contact_id,
            "relationship_type": relationship_type.value,
        }

        if update_status:
            set_clauses.append("status = :status")
            params["status"] = status.value if status is not None else None

        if update_role:
            set_clauses.append("role = :role")
            params["role"] = role.value if role is not None else None

        if not set_clauses:
            # If nothing to update, return the current entity for the exact relationship.
            query = text(
                """
                SELECT journal_id, contact_id, relationship_type,
                       created_at, status, role
                FROM journal_contact_relationships
                WHERE journal_id = :journal_id
                AND contact_id = :contact_id
                AND relationship_type = :relationship_type
            """
            )
            result = await self.conn.execute(query, params)
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_entity(row)

        set_sql = ", ".join(set_clauses)

        query = text(
            f"""
            UPDATE journal_contact_relationships
            SET {set_sql}
            WHERE journal_id = :journal_id
            AND contact_id = :contact_id
            AND relationship_type = :relationship_type
            RETURNING journal_id, contact_id, relationship_type,
                      created_at, status, role
        """
        )

        result = await self.conn.execute(query, params)
        row = result.fetchone()
        if row is None:
            return None

        await touch_journal(self.conn, journal_id)
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

"""SQL implementation of ClimbingDataRepository."""

from typing import Any
from uuid import UUID

from core_shared.models.journals import ClimbingData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import ClimbingDataRepository


class SqlClimbingDataRepository(ClimbingDataRepository):
    """SQL implementation of ClimbingDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> ClimbingData:
        """Convert a database row to a ClimbingData entity."""
        template_id = row.template_id
        if template_id is not None and not isinstance(template_id, (str, UUID)):
            template_id = str(template_id)
        return ClimbingData(
            journal_id=row.journal_id,
            template_id=template_id,
            climbing_type=row.climbing_type,
            grade=row.grade,
            length=row.length,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> ClimbingData | None:
        """Find climbing data by journal ID."""
        query = text(
            """
            SELECT journal_id, template_id, climbing_type, grade, length,
                   created_at, updated_at
            FROM journal_climbing_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: ClimbingData) -> ClimbingData:
        """
        Save climbing data (insert or update) using atomic UPSERT.

        Args:
            data: The climbing data to save

        Returns:
            The saved data with updated timestamps
        """
        query = text(
            """
            INSERT INTO journal_climbing_data (
                journal_id, template_id, climbing_type, grade, length
            )
            VALUES (
                :journal_id, :template_id, :climbing_type, :grade, :length
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                template_id = EXCLUDED.template_id,
                climbing_type = EXCLUDED.climbing_type,
                grade = EXCLUDED.grade,
                length = EXCLUDED.length,
                updated_at = now()
            RETURNING journal_id, template_id, climbing_type, grade, length,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "template_id": str(data.template_id) if data.template_id else None,
                "climbing_type": data.climbing_type,
                "grade": data.grade,
                "length": data.length,
            },
        )
        row = result.fetchone()
        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete climbing data by journal ID."""
        query = text("DELETE FROM journal_climbing_data WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

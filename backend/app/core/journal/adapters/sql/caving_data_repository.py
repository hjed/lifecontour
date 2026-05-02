"""SQL implementation of CavingDataRepository."""

from typing import Any

from core_shared.models.journals import CavingData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import CavingDataRepository


class SqlCavingDataRepository(CavingDataRepository):
    """SQL implementation of CavingDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> CavingData:
        """Convert a database row to a CavingData entity."""
        # Convert UUID to string if it's present
        template_id = str(row.template_id) if row.template_id else None

        return CavingData(
            journal_id=row.journal_id,
            template_id=template_id,
            is_vertical=row.is_vertical,
            is_horizontal=row.is_horizontal,
        )

    async def find_by_journal_id(self, journal_id: int) -> CavingData | None:
        """Find caving data by journal ID."""
        query = text(
            """
            SELECT journal_id, template_id, is_vertical, is_horizontal
            FROM journal_caving_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: CavingData) -> CavingData:
        """Save caving data (upsert based on journal_id)."""
        query = text(
            """
            INSERT INTO journal_caving_data (
                journal_id, template_id, is_vertical, is_horizontal
            )
            VALUES (
                :journal_id, :template_id, :is_vertical, :is_horizontal
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                template_id = EXCLUDED.template_id,
                is_vertical = EXCLUDED.is_vertical,
                is_horizontal = EXCLUDED.is_horizontal
            RETURNING journal_id, template_id, is_vertical, is_horizontal
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "template_id": data.template_id,
                "is_vertical": data.is_vertical,
                "is_horizontal": data.is_horizontal,
            },
        )
        row = result.fetchone()

        # If no row returned, something went wrong with the query
        if not row:
            raise ValueError("Failed to save caving data")

        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete caving data by journal ID."""
        query = text("DELETE FROM journal_caving_data WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

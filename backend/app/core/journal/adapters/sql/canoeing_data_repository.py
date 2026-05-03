"""SQL implementation of CanoeingDataRepository."""

from typing import Any

from core_shared.models.journals import CanoeingData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import CanoeingDataRepository


class SqlCanoeingDataRepository(CanoeingDataRepository):
    """SQL implementation of CanoeingDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> CanoeingData:
        """Convert a database row to a CanoeingData entity."""
        return CanoeingData(
            journal_id=row.journal_id,
            water_type=row.water_type,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> CanoeingData | None:
        """Find canoeing data by journal ID."""
        query = text(
            """
            SELECT journal_id, water_type, created_at, updated_at
            FROM journal_canoeing_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: CanoeingData) -> CanoeingData:
        """Save canoeing data (upsert based on journal_id)."""
        query = text(
            """
            INSERT INTO journal_canoeing_data (
                journal_id, water_type
            )
            VALUES (
                :journal_id, :water_type
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                water_type = EXCLUDED.water_type,
                updated_at = now()
            RETURNING journal_id, water_type, created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "water_type": data.water_type,
            },
        )
        row = result.fetchone()

        # If no row returned, something went wrong with the query
        if not row:
            raise ValueError("Failed to save canoeing data")

        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete canoeing data by journal ID."""
        query = text("DELETE FROM journal_canoeing_data WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

"""SQL implementation of KayakingDataRepository."""

from typing import Any

from core_shared.models.journals import KayakingData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import KayakingDataRepository


class SqlKayakingDataRepository(KayakingDataRepository):
    """SQL implementation of KayakingDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> KayakingData:
        """Convert a database row to a KayakingData entity."""
        return KayakingData(
            journal_id=row.journal_id,
            water_type=row.water_type,
            is_white_water=row.is_white_water,
            rapids_grade=row.rapids_grade,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> KayakingData | None:
        """Find kayaking data by journal ID."""
        query = text(
            """
            SELECT journal_id, water_type, is_white_water, rapids_grade,
                   created_at, updated_at
            FROM journal_kayaking_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: KayakingData) -> KayakingData:
        """
        Save kayaking data (insert or update) using atomic UPSERT.

        Args:
            data: The kayaking data to save

        Returns:
            The saved data with updated timestamps
        """
        query = text(
            """
            INSERT INTO journal_kayaking_data (
                journal_id, water_type, is_white_water, rapids_grade
            )
            VALUES (
                :journal_id, :water_type, :is_white_water, :rapids_grade
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                water_type = EXCLUDED.water_type,
                is_white_water = EXCLUDED.is_white_water,
                rapids_grade = EXCLUDED.rapids_grade,
                updated_at = now()
            RETURNING journal_id, water_type, is_white_water, rapids_grade,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "water_type": data.water_type,
                "is_white_water": data.is_white_water,
                "rapids_grade": data.rapids_grade,
            },
        )
        row = result.fetchone()
        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete kayaking data by journal ID."""
        query = text("DELETE FROM journal_kayaking_data WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

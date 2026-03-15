"""SQL implementation of JoggingDataRepository."""

from typing import Any

from core_shared.models.journals import JoggingData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import JoggingDataRepository


class SqlJoggingDataRepository(JoggingDataRepository):
    """SQL implementation of JoggingDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> JoggingData:
        """Convert a database row to a JoggingData entity."""
        return JoggingData(
            journal_id=row.journal_id,
            pace=row.pace,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> JoggingData | None:
        """Find jogging data by journal ID."""
        query = text(
            """
            SELECT journal_id, pace, created_at, updated_at
            FROM journal_jogging_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: JoggingData) -> JoggingData:
        """
        Save jogging data (insert or update) using atomic UPSERT.

        Args:
            data: The jogging data to save

        Returns:
            The saved data with updated timestamps
        """
        query = text(
            """
            INSERT INTO journal_jogging_data (
                journal_id, pace
            )
            VALUES (
                :journal_id, :pace
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                pace = EXCLUDED.pace,
                updated_at = now()
            RETURNING journal_id, pace, created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "pace": data.pace,
            },
        )
        row = result.fetchone()
        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete jogging data by journal ID."""
        query = text("DELETE FROM journal_jogging_data WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

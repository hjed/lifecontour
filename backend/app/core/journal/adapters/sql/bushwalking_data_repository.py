"""SQL implementation of BushwalkingDataRepository."""

from typing import Any

from core_shared.models.journals import BushwalkingData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import BushwalkingDataRepository


class SqlBushwalkingDataRepository(BushwalkingDataRepository):
    """SQL implementation of BushwalkingDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> BushwalkingData:
        """Convert a database row to a BushwalkingData entity."""
        return BushwalkingData(
            journal_id=row.journal_id,
            track_grading=row.track_grading,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> BushwalkingData | None:
        """Find bushwalking data by journal ID."""
        query = text(
            """
            SELECT journal_id, track_grading, created_at, updated_at
            FROM journal_bushwalking_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: BushwalkingData) -> BushwalkingData:
        """
        Save bushwalking data (insert or update) using atomic UPSERT.

        Args:
            data: The bushwalking data to save

        Returns:
            The saved data with updated timestamps
        """
        query = text(
            """
            INSERT INTO journal_bushwalking_data (
                journal_id, track_grading
            )
            VALUES (
                :journal_id, :track_grading
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                track_grading = EXCLUDED.track_grading,
                updated_at = now()
            RETURNING journal_id, track_grading, created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "track_grading": data.track_grading,
            },
        )
        row = result.fetchone()
        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete bushwalking data by journal ID."""
        query = text(
            "DELETE FROM journal_bushwalking_data WHERE journal_id = :journal_id"
        )
        await self.conn.execute(query, {"journal_id": journal_id})

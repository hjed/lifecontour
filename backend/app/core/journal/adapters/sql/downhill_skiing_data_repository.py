"""SQL implementation of DownhillSkiingDataRepository."""

from datetime import UTC, datetime
from typing import Any

from core_shared.models.journals import DownhillSkiingData
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import DownhillSkiingDataRepository


class SqlDownhillSkiingDataRepository(DownhillSkiingDataRepository):
    """SQL-based implementation of DownhillSkiingDataRepository."""

    def __init__(self, connection: AsyncConnection):
        """Initialize the repository."""
        self._connection = connection

    def _row_to_entity(self, row: Row[Any]) -> DownhillSkiingData:
        """Convert a database row to a DownhillSkiingData entity."""
        return DownhillSkiingData(
            journal_id=row.journal_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> DownhillSkiingData | None:
        """Find downhill skiing data by journal ID."""
        query = text(
            """
            SELECT journal_id, created_at, updated_at
            FROM journal_downhill_skiing_data
            WHERE journal_id = :journal_id
            """
        )

        result = await self._connection.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: DownhillSkiingData) -> DownhillSkiingData:
        """Save downhill skiing data (insert or update)."""
        now = datetime.now(UTC)

        query = text(
            """
            INSERT INTO journal_downhill_skiing_data (
                journal_id, created_at, updated_at
            )
            VALUES (
                :journal_id, :created_at, :updated_at
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                updated_at = EXCLUDED.updated_at
            RETURNING journal_id, created_at, updated_at
            """
        )

        result = await self._connection.execute(
            query,
            {
                "journal_id": data.journal_id,
                "created_at": data.created_at or now,
                "updated_at": now,
            },
        )

        row = result.fetchone()
        if not row:
            raise RuntimeError("Failed to save downhill skiing data")

        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete downhill skiing data by journal ID."""
        query = text(
            """
            DELETE FROM journal_downhill_skiing_data
            WHERE journal_id = :journal_id
            """
        )

        await self._connection.execute(query, {"journal_id": journal_id})

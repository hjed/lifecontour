"""SQL implementation of AbseilingDataRepository."""

from typing import Any

from core_shared.models.journals import AbseilingData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import AbseilingDataRepository


class SqlAbseilingDataRepository(AbseilingDataRepository):
    """SQL implementation of AbseilingDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> AbseilingData:
        """Convert a database row to an AbseilingData entity."""
        return AbseilingData(
            journal_id=row.journal_id,
            number_of_abseils=row.number_of_abseils,
            total_length=row.total_length,
            number_of_setups=row.number_of_setups,
            number_of_rescues=row.number_of_rescues,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> AbseilingData | None:
        """Find abseiling data by journal ID."""
        query = text(
            """
            SELECT journal_id, number_of_abseils, total_length,
                   number_of_setups, number_of_rescues,
                   created_at, updated_at
            FROM journal_abseiling_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: AbseilingData) -> AbseilingData:
        """
        Save abseiling data (insert or update) using atomic UPSERT.

        Args:
            data: The abseiling data to save

        Returns:
            The saved data with updated timestamps
        """
        query = text(
            """
            INSERT INTO journal_abseiling_data (
                journal_id, number_of_abseils, total_length,
                number_of_setups, number_of_rescues
            )
            VALUES (
                :journal_id, :number_of_abseils, :total_length,
                :number_of_setups, :number_of_rescues
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                number_of_abseils = EXCLUDED.number_of_abseils,
                total_length = EXCLUDED.total_length,
                number_of_setups = EXCLUDED.number_of_setups,
                number_of_rescues = EXCLUDED.number_of_rescues,
                updated_at = now()
            RETURNING journal_id, number_of_abseils, total_length,
                      number_of_setups, number_of_rescues,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "number_of_abseils": data.number_of_abseils,
                "total_length": data.total_length,
                "number_of_setups": data.number_of_setups,
                "number_of_rescues": data.number_of_rescues,
            },
        )
        row = result.fetchone()
        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete abseiling data by journal ID."""
        query = text(
            "DELETE FROM journal_abseiling_data WHERE journal_id = :journal_id"
        )
        await self.conn.execute(query, {"journal_id": journal_id})

"""SQL implementation of CrossCountrySkiingDataRepository."""

from typing import Any
from uuid import UUID

from core_shared.models.journals import CrossCountrySkiingData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import CrossCountrySkiingDataRepository


class SqlCrossCountrySkiingDataRepository(CrossCountrySkiingDataRepository):
    """SQL implementation of CrossCountrySkiingDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> CrossCountrySkiingData:
        """Convert a database row to a CrossCountrySkiingData entity."""
        return CrossCountrySkiingData(
            journal_id=row.journal_id,
            route_id=UUID(str(row.route_id)) if row.route_id is not None else None,
            snow_conditions=row.snow_conditions,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(
        self, journal_id: int
    ) -> CrossCountrySkiingData | None:
        """Find cross-country skiing data by journal ID."""
        query = text(
            """
            SELECT journal_id, route_id, snow_conditions,
                   created_at, updated_at
            FROM journal_skiing_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: CrossCountrySkiingData) -> CrossCountrySkiingData:
        """
        Save cross-country skiing data (insert or update) using atomic UPSERT.

        Args:
            data: The cross-country skiing data to save

        Returns:
            The saved data with updated timestamps
        """
        query = text(
            """
            INSERT INTO journal_skiing_data (
                journal_id, route_id, snow_conditions
            )
            VALUES (
                :journal_id, :route_id, :snow_conditions
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                route_id = EXCLUDED.route_id,
                snow_conditions = EXCLUDED.snow_conditions,
                updated_at = now()
            RETURNING journal_id, route_id, snow_conditions,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "route_id": str(data.route_id) if data.route_id is not None else None,
                "snow_conditions": data.snow_conditions,
            },
        )
        row = result.fetchone()
        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete cross-country skiing data by journal ID."""
        query = text("DELETE FROM journal_skiing_data WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

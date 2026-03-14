"""SQL implementation of CanyoningDataRepository."""

from typing import Any
from uuid import UUID

from core_shared.models.journals import CanyoningData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import CanyoningDataRepository


class SqlCanyoningDataRepository(CanyoningDataRepository):
    """SQL implementation of CanyoningDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> CanyoningData:
        """Convert a database row to a CanyoningData entity."""
        return CanyoningData(
            journal_id=row.journal_id,
            route_id=UUID(str(row.route_id)) if row.route_id is not None else None,
            french_grade=row.french_grade,
            water_guage_name=row.water_guage_name,
            water_guage_level=row.water_guage_level,
            is_vertical=row.is_vertical,
            is_night_canyon=row.is_night_canyon,
            is_white_water=row.is_white_water,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> CanyoningData | None:
        """Find canyoning data by journal ID."""
        query = text(
            """
            SELECT journal_id, route_id, french_grade, water_guage_name,
                   water_guage_level, is_vertical, is_night_canyon, is_white_water,
                   created_at, updated_at
            FROM journal_canyoning_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: CanyoningData) -> CanyoningData:
        """
        Save canyoning data (insert or update) using atomic UPSERT.

        Args:
            data: The canyoning data to save

        Returns:
            The saved data with updated timestamps
        """
        query = text(
            """
            INSERT INTO journal_canyoning_data (
                journal_id, route_id, french_grade, water_guage_name,
                water_guage_level, is_vertical, is_night_canyon, is_white_water
            )
            VALUES (
                :journal_id, :route_id, :french_grade, :water_guage_name,
                :water_guage_level, :is_vertical, :is_night_canyon, :is_white_water
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                route_id = EXCLUDED.route_id,
                french_grade = EXCLUDED.french_grade,
                water_guage_name = EXCLUDED.water_guage_name,
                water_guage_level = EXCLUDED.water_guage_level,
                is_vertical = EXCLUDED.is_vertical,
                is_night_canyon = EXCLUDED.is_night_canyon,
                is_white_water = EXCLUDED.is_white_water,
                updated_at = now()
            RETURNING journal_id, route_id, french_grade, water_guage_name,
                      water_guage_level, is_vertical, is_night_canyon, is_white_water,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "route_id": str(data.route_id) if data.route_id is not None else None,
                "french_grade": data.french_grade,
                "water_guage_name": data.water_guage_name,
                "water_guage_level": data.water_guage_level,
                "is_vertical": data.is_vertical,
                "is_night_canyon": data.is_night_canyon,
                "is_white_water": data.is_white_water,
            },
        )
        row = result.fetchone()
        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete canyoning data by journal ID."""
        query = text(
            "DELETE FROM journal_canyoning_data WHERE journal_id = :journal_id"
        )
        await self.conn.execute(query, {"journal_id": journal_id})

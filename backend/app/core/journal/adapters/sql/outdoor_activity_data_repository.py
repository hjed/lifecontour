"""SQL implementation of OutdoorActivityDataRepository."""

from typing import Any

from core_shared.models.journals import OutdoorActivityData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import OutdoorActivityDataRepository


class SqlOutdoorActivityDataRepository(OutdoorActivityDataRepository):
    """SQL implementation of OutdoorActivityDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> OutdoorActivityData:
        """Convert a database row to an OutdoorActivityData entity."""
        return OutdoorActivityData(
            journal_id=row.journal_id,
            weather_conditions=row.weather_conditions,
            role=row.role,
            in_leadership_role=row.in_leadership_role,
            participant_notes=row.participant_notes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> OutdoorActivityData | None:
        """Find outdoor activity data by journal ID."""
        query = text(
            """
            SELECT journal_id, weather_conditions, role,
                   in_leadership_role, participant_notes, created_at, updated_at
            FROM journal_outdoor_activity_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def save(self, data: OutdoorActivityData) -> OutdoorActivityData:
        """
        Save outdoor activity data (insert or update) using atomic UPSERT.

        Args:
            data: The outdoor activity data to save

        Returns:
            The saved data with updated timestamps
        """
        query = text(
            """
            INSERT INTO journal_outdoor_activity_data (
                journal_id, weather_conditions, role,
                in_leadership_role, participant_notes
            )
            VALUES (
                :journal_id, :weather_conditions, :role,
                :in_leadership_role, :participant_notes
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                weather_conditions = EXCLUDED.weather_conditions,
                role = EXCLUDED.role,
                in_leadership_role = EXCLUDED.in_leadership_role,
                participant_notes = EXCLUDED.participant_notes,
                updated_at = now()
            RETURNING journal_id, weather_conditions, role,
                      in_leadership_role, participant_notes, created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": data.journal_id,
                "weather_conditions": data.weather_conditions,
                "role": data.role,
                "in_leadership_role": data.in_leadership_role,
                "participant_notes": data.participant_notes,
            },
        )
        row = result.fetchone()
        return self._row_to_entity(row)

    async def delete(self, journal_id: int) -> None:
        """Delete outdoor activity data by journal ID."""
        query = text(
            "DELETE FROM journal_outdoor_activity_data WHERE journal_id = :journal_id"
        )
        await self.conn.execute(query, {"journal_id": journal_id})

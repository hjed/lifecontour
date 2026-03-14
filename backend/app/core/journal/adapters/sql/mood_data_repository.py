"""SQL implementation of MoodDataRepository."""

from typing import Any

from core_shared.models.journals import MoodData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import MoodDataRepository


class SqlMoodDataRepository(MoodDataRepository):
    """SQL implementation of MoodDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_mood_data(self, row: Any) -> MoodData:
        """Convert a database row to a MoodData entity."""
        return MoodData(
            journal_id=row.journal_id,
            mood_value=row.mood_value,
            mood_label=row.mood_label,
            energy_level=row.energy_level,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> MoodData | None:
        """Find mood data by journal ID."""
        query = text(
            """
            SELECT journal_id, mood_value, mood_label, energy_level,
                   created_at, updated_at
            FROM journal_mood_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_mood_data(row)

    async def save(self, mood_data: MoodData) -> MoodData:
        """Save mood data (insert or update)."""
        # Check if row exists
        existing = await self.find_by_journal_id(mood_data.journal_id)
        if existing is None:
            return await self._insert(mood_data)
        else:
            return await self._update(mood_data)

    async def _insert(self, mood_data: MoodData) -> MoodData:
        """Insert new mood data."""
        query = text(
            """
            INSERT INTO journal_mood_data (
                journal_id, mood_value, mood_label, energy_level
            )
            VALUES (
                :journal_id, :mood_value, :mood_label, :energy_level
            )
            RETURNING journal_id, mood_value, mood_label, energy_level,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": mood_data.journal_id,
                "mood_value": mood_data.mood_value,
                "mood_label": mood_data.mood_label,
                "energy_level": mood_data.energy_level,
            },
        )
        row = result.fetchone()
        return self._row_to_mood_data(row)

    async def _update(self, mood_data: MoodData) -> MoodData:
        """Update existing mood data."""
        query = text(
            """
            UPDATE journal_mood_data
            SET mood_value = :mood_value,
                mood_label = :mood_label,
                energy_level = :energy_level,
                updated_at = now()
            WHERE journal_id = :journal_id
            RETURNING journal_id, mood_value, mood_label, energy_level,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": mood_data.journal_id,
                "mood_value": mood_data.mood_value,
                "mood_label": mood_data.mood_label,
                "energy_level": mood_data.energy_level,
            },
        )
        row = result.fetchone()
        return self._row_to_mood_data(row)

    async def delete(self, journal_id: int) -> None:
        """Delete mood data by journal ID."""
        query = text("DELETE FROM journal_mood_data WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

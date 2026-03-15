"""SQL implementation of FitnessDataRepository."""

from typing import Any

from core_shared.models.journals import FitnessData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import FitnessDataRepository


class SqlFitnessDataRepository(FitnessDataRepository):
    """SQL implementation of FitnessDataRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_fitness_data(self, row: Any) -> FitnessData:
        """Convert a database row to a FitnessData entity."""
        return FitnessData(
            journal_id=row.journal_id,
            heart_rate_avg=row.heart_rate_avg,
            heart_rate_max=row.heart_rate_max,
            distance=row.distance,
            elevation_gain=row.elevation_gain,
            elevation_loss=row.elevation_loss,
            duration=row.duration,
            calories=row.calories,
            strava_activity_id=row.strava_activity_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> FitnessData | None:
        """Find fitness data by journal ID."""
        query = text(
            """
            SELECT journal_id, heart_rate_avg, heart_rate_max, distance,
                   elevation_gain, elevation_loss, duration, calories,
                   strava_activity_id,
                   created_at, updated_at
            FROM journal_fitness_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_fitness_data(row)

    async def save(self, fitness_data: FitnessData) -> FitnessData:
        """
        Save fitness data (insert or update) using atomic UPSERT.

        Uses PostgreSQL's INSERT ... ON CONFLICT to avoid race conditions
        between concurrent requests. This is atomic and handles the case
        where multiple requests try to create the same journal_id simultaneously.

        Args:
            fitness_data: The fitness data to save

        Returns:
            The saved fitness data with updated timestamps
        """
        query = text(
            """
            INSERT INTO journal_fitness_data (
                journal_id, heart_rate_avg, heart_rate_max, distance,
                elevation_gain, elevation_loss, duration, calories,
                strava_activity_id
            )
            VALUES (
                :journal_id, :heart_rate_avg, :heart_rate_max, :distance,
                :elevation_gain, :elevation_loss, :duration, :calories,
                :strava_activity_id
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                heart_rate_avg = EXCLUDED.heart_rate_avg,
                heart_rate_max = EXCLUDED.heart_rate_max,
                distance = EXCLUDED.distance,
                elevation_gain = EXCLUDED.elevation_gain,
                elevation_loss = EXCLUDED.elevation_loss,
                duration = EXCLUDED.duration,
                calories = EXCLUDED.calories,
                strava_activity_id = EXCLUDED.strava_activity_id,
                updated_at = now()
            RETURNING journal_id, heart_rate_avg, heart_rate_max, distance,
                      elevation_gain, elevation_loss, duration, calories,
                      strava_activity_id,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": fitness_data.journal_id,
                "heart_rate_avg": fitness_data.heart_rate_avg,
                "heart_rate_max": fitness_data.heart_rate_max,
                "distance": fitness_data.distance,
                "elevation_gain": fitness_data.elevation_gain,
                "elevation_loss": fitness_data.elevation_loss,
                "duration": fitness_data.duration,
                "calories": fitness_data.calories,
                "strava_activity_id": fitness_data.strava_activity_id,
            },
        )
        row = result.fetchone()
        return self._row_to_fitness_data(row)

    async def delete(self, journal_id: int) -> None:
        """Delete fitness data by journal ID."""
        query = text("DELETE FROM journal_fitness_data WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

"""SQL implementation of the OutdoorTrainingDataRepository."""

import json

from core_shared.models.journals import OutdoorTrainingData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import OutdoorTrainingDataRepository


class SqlOutdoorTrainingDataRepository(OutdoorTrainingDataRepository):
    """SQL implementation of OutdoorTrainingDataRepository."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialize with database connection."""
        self.connection = connection

    async def find_by_journal_id(self, journal_id: int) -> OutdoorTrainingData | None:
        """Find outdoor training data by journal ID."""
        query = text(
            """
            SELECT journal_id, focus_areas, created_at, updated_at
            FROM journal_outdoor_training_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.connection.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        # Handle JSONB parsing for focus_areas
        focus_areas = row.focus_areas
        if isinstance(focus_areas, str):
            focus_areas = json.loads(focus_areas)

        return OutdoorTrainingData(
            journal_id=row.journal_id,
            focus_areas=focus_areas,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, data: OutdoorTrainingData) -> OutdoorTrainingData:
        """Save outdoor training data (insert or update)."""
        # Convert list to JSON string if needed for SQLAlchemy parameterized queries
        focus_areas_json = (
            json.dumps(data.focus_areas) if data.focus_areas is not None else None
        )

        query = text(
            """
            INSERT INTO journal_outdoor_training_data (
                journal_id, focus_areas, created_at, updated_at
            ) VALUES (
                :journal_id, CAST(:focus_areas AS jsonb), COALESCE(:created_at, now()), COALESCE(:updated_at, now())
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                focus_areas = EXCLUDED.focus_areas,
                updated_at = now()
            RETURNING journal_id, focus_areas, created_at, updated_at
            """
        )

        result = await self.connection.execute(
            query,
            {
                "journal_id": data.journal_id,
                "focus_areas": focus_areas_json,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            },
        )
        row = result.fetchone()

        if not row:
            raise RuntimeError("Failed to save outdoor training data")

        focus_areas = row.focus_areas
        if isinstance(focus_areas, str):
            focus_areas = json.loads(focus_areas)

        data.created_at = row.created_at
        data.updated_at = row.updated_at
        data.focus_areas = focus_areas

        return data

    async def delete(self, journal_id: int) -> None:
        """Delete outdoor training data by journal ID."""
        query = text(
            "DELETE FROM journal_outdoor_training_data WHERE journal_id = :journal_id"
        )
        await self.connection.execute(query, {"journal_id": journal_id})

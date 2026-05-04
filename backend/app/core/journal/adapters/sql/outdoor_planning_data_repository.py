"""SQL implementation of the OutdoorPlanningDataRepository."""

import json

from core_shared.models.journals import OutdoorPlanningData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import OutdoorPlanningDataRepository


class SqlOutdoorPlanningDataRepository(OutdoorPlanningDataRepository):
    """SQL implementation of OutdoorPlanningDataRepository."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialize with database connection."""
        self.connection = connection

    async def find_by_journal_id(self, journal_id: int) -> OutdoorPlanningData | None:
        """Find outdoor planning data by journal ID."""
        query = text(
            """
            SELECT journal_id, topics, activity_types, created_at, updated_at
            FROM journal_outdoor_planning_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.connection.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        # Handle JSONB parsing for activity_types
        activity_types = row.activity_types
        if isinstance(activity_types, str):
            activity_types = json.loads(activity_types)

        return OutdoorPlanningData(
            journal_id=row.journal_id,
            topics=row.topics,
            activity_types=activity_types if activity_types else [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, data: OutdoorPlanningData) -> OutdoorPlanningData:
        """Save outdoor planning data (insert or update)."""
        # Convert list to JSON string if needed for SQLAlchemy parameterized queries
        activity_types_json = (
            json.dumps(data.activity_types) if data.activity_types else "[]"
        )

        query = text(
            """
            INSERT INTO journal_outdoor_planning_data (
                journal_id, topics, activity_types, created_at, updated_at
            ) VALUES (
                :journal_id, :topics, CAST(:activity_types AS jsonb), COALESCE(:created_at, now()), COALESCE(:updated_at, now())
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                topics = EXCLUDED.topics,
                activity_types = EXCLUDED.activity_types,
                updated_at = now()
            RETURNING journal_id, topics, activity_types, created_at, updated_at
            """
        )

        result = await self.connection.execute(
            query,
            {
                "journal_id": data.journal_id,
                "topics": data.topics,
                "activity_types": activity_types_json,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            },
        )
        row = result.fetchone()

        if not row:
            raise RuntimeError("Failed to save outdoor planning data")

        activity_types = row.activity_types
        if isinstance(activity_types, str):
            activity_types = json.loads(activity_types)

        data.created_at = row.created_at
        data.updated_at = row.updated_at
        data.activity_types = activity_types if activity_types else []

        return data

    async def delete(self, journal_id: int) -> None:
        """Delete outdoor planning data by journal ID."""
        query = text(
            "DELETE FROM journal_outdoor_planning_data WHERE journal_id = :journal_id"
        )
        await self.connection.execute(query, {"journal_id": journal_id})

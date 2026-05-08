from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class SqlJournalUnmatchedStravaAthleteRepository:
    """Repository for managing unmatched Strava athletes on journals."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def get_by_journal_id(self, journal_id: int) -> list[dict[str, Any]]:
        """Get unmatched athletes for a specific journal."""
        query = text(
            """
            SELECT strava_athlete_id, strava_athlete_name
            FROM journal_unmatched_strava_athletes
            WHERE journal_id = :journal_id
            """
        )
        result = await self.connection.execute(query, {"journal_id": journal_id})
        return [
            {
                "strava_athlete_id": row.strava_athlete_id,
                "strava_athlete_name": row.strava_athlete_name,
            }
            for row in result.fetchall()
        ]

    async def get_journal_ids_by_strava_id(self, strava_athlete_id: str) -> list[int]:
        """Get all journal IDs that have this unmatched Strava athlete."""
        query = text(
            """
            SELECT journal_id
            FROM journal_unmatched_strava_athletes
            WHERE strava_athlete_id = :strava_athlete_id
            """
        )
        result = await self.connection.execute(
            query, {"strava_athlete_id": strava_athlete_id}
        )
        return [row.journal_id for row in result.fetchall()]

    async def delete_by_strava_id(self, strava_athlete_id: str) -> None:
        """Delete all unmatched records for a specific Strava athlete."""
        query = text(
            """
            DELETE FROM journal_unmatched_strava_athletes
            WHERE strava_athlete_id = :strava_athlete_id
            """
        )
        await self.connection.execute(query, {"strava_athlete_id": strava_athlete_id})

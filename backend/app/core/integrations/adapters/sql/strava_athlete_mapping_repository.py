from core_shared.models.strava_athlete_mapping import StravaAthleteMapping
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class SqlStravaAthleteMappingRepository:
    """Repository for managing Strava athlete to Contact mappings."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def get_by_strava_id(
        self, user_id: str, strava_athlete_id: str
    ) -> StravaAthleteMapping | None:
        """Get a mapping by user ID and Strava athlete ID."""
        query = text(
            """
            SELECT id, user_id, strava_athlete_id, strava_athlete_name, contact_id, created_at, updated_at
            FROM strava_athlete_mappings
            WHERE user_id = :user_id AND strava_athlete_id = :strava_athlete_id
            """
        )
        result = await self.connection.execute(
            query,
            {"user_id": user_id, "strava_athlete_id": strava_athlete_id},
        )
        row = result.fetchone()

        if row is None:
            return None

        return StravaAthleteMapping(
            id=row.id,
            user_id=row.user_id,
            strava_athlete_id=row.strava_athlete_id,
            strava_athlete_name=row.strava_athlete_name,
            contact_id=row.contact_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, mapping: StravaAthleteMapping) -> StravaAthleteMapping:
        """Save a mapping, inserting or updating as necessary."""
        if mapping.id is None:
            query = text(
                """
                INSERT INTO strava_athlete_mappings (user_id, strava_athlete_id, strava_athlete_name, contact_id)
                VALUES (:user_id, :strava_athlete_id, :strava_athlete_name, :contact_id)
                ON CONFLICT (user_id, strava_athlete_id) DO UPDATE
                SET strava_athlete_name = EXCLUDED.strava_athlete_name, contact_id = EXCLUDED.contact_id, updated_at = now()
                RETURNING id, created_at, updated_at
                """
            )
            result = await self.connection.execute(
                query,
                {
                    "user_id": mapping.user_id,
                    "strava_athlete_id": mapping.strava_athlete_id,
                    "strava_athlete_name": mapping.strava_athlete_name,
                    "contact_id": mapping.contact_id,
                },
            )
            row = result.fetchone()
            if not row:
                raise RuntimeError("Failed to insert or update mapping")

            return StravaAthleteMapping(
                id=row.id,
                user_id=mapping.user_id,
                strava_athlete_id=mapping.strava_athlete_id,
                strava_athlete_name=mapping.strava_athlete_name,
                contact_id=mapping.contact_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        else:
            query = text(
                """
                UPDATE strava_athlete_mappings
                SET strava_athlete_name = :strava_athlete_name, contact_id = :contact_id, updated_at = now()
                WHERE id = :id
                RETURNING updated_at
                """
            )
            result = await self.connection.execute(
                query,
                {
                    "id": mapping.id,
                    "strava_athlete_name": mapping.strava_athlete_name,
                    "contact_id": mapping.contact_id,
                },
            )
            row = result.fetchone()
            if not row:
                raise RuntimeError("Failed to update mapping")

            return StravaAthleteMapping(
                id=mapping.id,
                user_id=mapping.user_id,
                strava_athlete_id=mapping.strava_athlete_id,
                strava_athlete_name=mapping.strava_athlete_name,
                contact_id=mapping.contact_id,
                created_at=mapping.created_at,
                updated_at=row.updated_at,
            )

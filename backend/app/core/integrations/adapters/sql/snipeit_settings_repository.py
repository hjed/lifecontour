from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.models.snipeit import SnipeItSettings


class SqlSnipeItSettingsRepository:
    """Repository for managing Snipe-IT integration settings."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def get_by_user_id(self, user_id: str) -> SnipeItSettings | None:
        """Get Snipe-IT settings for a specific user."""
        stmt = text(
            """
            SELECT user_id, base_url, snipeit_user_id, created_at, updated_at
            FROM snipeit_settings
            WHERE user_id = :user_id
            """
        )
        result = await self.connection.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if not row:
            return None

        return SnipeItSettings(
            user_id=str(row.user_id),
            base_url=str(row.base_url),
            snipeit_user_id=row.snipeit_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, settings: SnipeItSettings) -> SnipeItSettings:
        """Create or update Snipe-IT settings for a user."""
        stmt = text(
            """
            INSERT INTO snipeit_settings (user_id, base_url, snipeit_user_id, updated_at)
            VALUES (:user_id, :base_url, :snipeit_user_id, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                base_url = EXCLUDED.base_url,
                snipeit_user_id = EXCLUDED.snipeit_user_id,
                updated_at = NOW()
            RETURNING user_id, base_url, snipeit_user_id, created_at, updated_at
            """
        )
        result = await self.connection.execute(
            stmt,
            {
                "user_id": settings.user_id,
                "base_url": settings.base_url,
                "snipeit_user_id": settings.snipeit_user_id,
            },
        )
        row = result.fetchone()

        if not row:
            raise RuntimeError("Failed to save Snipe-IT settings")

        return SnipeItSettings(
            user_id=str(row.user_id),
            base_url=str(row.base_url),
            snipeit_user_id=row.snipeit_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

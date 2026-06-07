"""SQL implementation of the user settings repository."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.models import UserSettings
from app.core.settings.timezone_utils import DEFAULT_TIMEZONE


class SqlUserSettingsRepository:
    """Repository for managing per-user settings (timezone, etc.)."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def get_by_user_id(self, user_id: str) -> UserSettings | None:
        """Get settings for a specific user."""
        stmt = text(
            """
            SELECT user_id, timezone, created_at, updated_at
            FROM user_settings
            WHERE user_id = :user_id
            """
        )
        result = await self.connection.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if not row:
            return None

        return UserSettings(
            user_id=str(row.user_id),
            timezone=str(row.timezone),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, settings: UserSettings) -> UserSettings:
        """Create or update settings for a user."""
        stmt = text(
            """
            INSERT INTO user_settings (user_id, timezone, updated_at)
            VALUES (:user_id, :timezone, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                timezone = EXCLUDED.timezone,
                updated_at = NOW()
            RETURNING user_id, timezone, created_at, updated_at
            """
        )
        result = await self.connection.execute(
            stmt,
            {
                "user_id": settings.user_id,
                "timezone": settings.timezone,
            },
        )
        row = result.fetchone()

        if not row:
            raise RuntimeError("Failed to save user settings")

        return UserSettings(
            user_id=str(row.user_id),
            timezone=str(row.timezone),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_timezone(self, user_id: str) -> str:
        """Return the user's stored timezone, or the default if unset."""
        settings = await self.get_by_user_id(user_id)
        if settings and settings.timezone:
            return settings.timezone
        return DEFAULT_TIMEZONE

    async def get_default_timezone(self) -> str:
        """Return the sole stored timezone, or the default (single-user fallback)."""
        stmt = text(
            """
            SELECT timezone
            FROM user_settings
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
        result = await self.connection.execute(stmt)
        row = result.fetchone()
        if row and row.timezone:
            return str(row.timezone)
        return DEFAULT_TIMEZONE

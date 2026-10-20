"""SQL implementation of the user settings repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.models import UNSET, UserSettings, UserSettingsChanges
from app.core.settings.timezone_utils import DEFAULT_TIMEZONE

_COLUMNS = "user_id, timezone, default_country, created_at, updated_at"


class SqlUserSettingsRepository:
    """Repository for managing per-user settings (timezone, default country)."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def get_by_user_id(self, user_id: str) -> UserSettings | None:
        """Get settings for a specific user."""
        stmt = text(
            f"""
            SELECT {_COLUMNS}
            FROM user_settings
            WHERE user_id = :user_id
            """
        )
        result = await self.connection.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if not row:
            return None

        return _to_settings(row)

    async def save(self, settings: UserSettings) -> UserSettings:
        """Create or update every field of a user's settings."""
        stmt = text(
            f"""
            INSERT INTO user_settings
                (user_id, timezone, default_country, updated_at)
            VALUES (:user_id, :timezone, :default_country, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                timezone = EXCLUDED.timezone,
                default_country = EXCLUDED.default_country,
                updated_at = NOW()
            RETURNING {_COLUMNS}
            """
        )
        return await self._upsert(
            stmt,
            {
                "user_id": settings.user_id,
                "timezone": settings.timezone,
                "default_country": settings.default_country,
            },
        )

    async def update(self, user_id: str, changes: UserSettingsChanges) -> UserSettings:
        """Create or update only the fields ``changes`` names.

        A new row leaves every other field NULL — "not chosen" — rather than
        recording a default the user never picked (issue #1401).
        """
        stmt = text(
            f"""
            INSERT INTO user_settings
                (user_id, timezone, default_country, updated_at)
            VALUES (:user_id, :timezone, :default_country, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                timezone = CASE WHEN :set_timezone
                    THEN EXCLUDED.timezone ELSE user_settings.timezone END,
                default_country = CASE WHEN :set_default_country
                    THEN EXCLUDED.default_country
                    ELSE user_settings.default_country END,
                updated_at = NOW()
            RETURNING {_COLUMNS}
            """
        )
        return await self._upsert(
            stmt,
            {
                "user_id": user_id,
                "timezone": None if changes.timezone is UNSET else changes.timezone,
                "set_timezone": changes.timezone is not UNSET,
                "default_country": (
                    None
                    if changes.default_country is UNSET
                    else changes.default_country
                ),
                "set_default_country": changes.default_country is not UNSET,
            },
        )

    async def get_timezone(self, user_id: str) -> str:
        """Return the user's stored timezone, or the default if unset."""
        settings = await self.get_by_user_id(user_id)
        if settings and settings.timezone:
            return settings.timezone
        return DEFAULT_TIMEZONE

    async def _upsert(self, stmt: Any, params: dict[str, object]) -> UserSettings:
        result = await self.connection.execute(stmt, params)
        row = result.fetchone()

        if not row:
            raise RuntimeError("Failed to save user settings")

        return _to_settings(row)


def _to_settings(row: Any) -> UserSettings:
    """The settings a row holds; NULL stays ``None``, never ``"None"``."""
    return UserSettings(
        user_id=str(row.user_id),
        timezone=row.timezone,
        default_country=row.default_country,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )

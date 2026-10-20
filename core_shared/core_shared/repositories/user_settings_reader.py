"""Read-only access to ``user_settings`` for the integration workers.

The backend owns writes (``SqlUserSettingsRepository``); a worker only needs
the syncing user's preferences while it imports.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


class UserSettingsReader:
    """Read one user's settings.

    Args:
        connection: An async connection (backend) or session (workers).
    """

    def __init__(self, connection: AsyncConnection | AsyncSession) -> None:
        self._conn = connection

    async def get_default_country(self, user_id: str) -> str | None:
        """The user's default country (ISO 3166-1 alpha-2), or None if unset.

        Filled in for imported addresses with no country of their own (#1820).
        """
        result = await self._conn.execute(
            text("SELECT default_country FROM user_settings WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        value = result.scalar()
        return str(value) if value is not None else None

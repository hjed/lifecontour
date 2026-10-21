"""SQL access to a user's Google contacts sync tokens."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class SqlGoogleContactsSyncTokenRepository:
    """Clears the token incremental contacts syncs resume from."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def force_full_contacts_sync(self, user_id: str) -> None:
        """Make ``user_id``'s next Google contacts sync a full one.

        With no token the next smart sync is a full sync, which re-applies
        every person whatever its etag (``force_apply``) - the 0131/0139
        backfill, for one user. A user with no Google account is unaffected.
        """
        await self.connection.execute(
            text(
                """
                UPDATE user_google_integration
                SET contacts_sync_token = NULL, updated_at = NOW()
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )

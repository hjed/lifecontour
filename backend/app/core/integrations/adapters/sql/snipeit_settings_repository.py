from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.models.snipeit import SnipeItSettings, SnipeItWebhookToken


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

    async def save(
        self, settings: SnipeItSettings, new_webhook_token: SnipeItWebhookToken
    ) -> SnipeItSettings:
        """
        Create or update Snipe-IT settings for a user.

        ``new_webhook_token`` is stored only when the settings are created; an
        update keeps the user's existing token so their webhook URL still works.
        """
        stmt = text(
            """
            INSERT INTO snipeit_settings (
                user_id, base_url, snipeit_user_id, webhook_token, updated_at
            )
            VALUES (:user_id, :base_url, :snipeit_user_id, :webhook_token, NOW())
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
                "webhook_token": new_webhook_token,
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

    async def get_webhook_token(self, user_id: str) -> SnipeItWebhookToken | None:
        """Get the user's webhook token, or None when they have no settings."""
        result = await self.connection.execute(
            text("SELECT webhook_token FROM snipeit_settings WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        token = result.scalar_one_or_none()
        return SnipeItWebhookToken(token) if token is not None else None

    async def get_user_id_by_webhook_token(
        self, webhook_token: SnipeItWebhookToken
    ) -> str | None:
        """Get the id of the user owning ``webhook_token``, or None if nobody does."""
        result = await self.connection.execute(
            text(
                "SELECT user_id FROM snipeit_settings "
                "WHERE webhook_token = :webhook_token"
            ),
            {"webhook_token": webhook_token},
        )
        user_id = result.scalar_one_or_none()
        return str(user_id) if user_id is not None else None

    async def set_webhook_token(
        self, user_id: str, webhook_token: SnipeItWebhookToken
    ) -> bool:
        """Replace the user's webhook token; False when they have no settings."""
        result = await self.connection.execute(
            text(
                """
                UPDATE snipeit_settings
                SET webhook_token = :webhook_token, updated_at = NOW()
                WHERE user_id = :user_id
                RETURNING user_id
                """
            ),
            {"user_id": user_id, "webhook_token": webhook_token},
        )
        return result.scalar_one_or_none() is not None

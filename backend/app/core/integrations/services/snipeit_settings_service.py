"""Service layer for Snipe-IT settings mutations.

Wraps the settings upsert in an explicit unit of work so the write is committed
before the HTTP response is sent (issue #945), keeping transaction ownership in
the service layer rather than the controller.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.snipeit_settings_repository import (
    SqlSnipeItSettingsRepository,
)
from app.core.integrations.models.snipeit import (
    SnipeItSettings,
    SnipeItWebhookToken,
    generate_webhook_token,
)
from app.infrastructure.unit_of_work import transactional


class SnipeItSettingsService:
    """Service for persisting per-user Snipe-IT integration settings."""

    def __init__(self, settings_repo: SqlSnipeItSettingsRepository) -> None:
        self.settings_repo = settings_repo

    @transactional
    async def save_settings(
        self,
        settings: SnipeItSettings,
        transaction: AsyncConnection,
    ) -> SnipeItSettings:
        """
        Create or update the user's Snipe-IT settings (upsert) as a committed unit.

        New settings get a webhook token; existing settings keep theirs.
        """
        return await self.settings_repo.save(
            settings, new_webhook_token=generate_webhook_token()
        )

    @transactional
    async def rotate_webhook_token(
        self,
        user_id: str,
        transaction: AsyncConnection,
    ) -> SnipeItWebhookToken | None:
        """
        Replace the user's webhook token as a committed unit.

        The previous webhook URL stops working immediately. Returns the new
        token, or None when the user has no Snipe-IT settings.
        """
        webhook_token = generate_webhook_token()
        if not await self.settings_repo.set_webhook_token(user_id, webhook_token):
            return None
        return webhook_token

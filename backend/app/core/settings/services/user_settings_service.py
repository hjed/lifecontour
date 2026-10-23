"""Service layer for user settings mutations.

Wraps the settings upsert in an explicit unit of work so the write is committed
before the HTTP response is sent (issue #945), keeping transaction ownership in
the service layer rather than the controller.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.models import (
    UserSettings,
    UserSettingsChanges,
    UserSettingsRepository,
)
from app.infrastructure.unit_of_work import transactional


class UserSettingsService:
    """Service for persisting per-user settings."""

    def __init__(self, settings_repo: UserSettingsRepository) -> None:
        self.settings_repo = settings_repo

    @transactional
    async def update_settings(
        self,
        user_id: str,
        changes: UserSettingsChanges,
        transaction: AsyncConnection,
    ) -> UserSettings:
        """Write the fields ``changes`` names (upsert) as a committed unit."""
        return await self.settings_repo.update(user_id, changes)

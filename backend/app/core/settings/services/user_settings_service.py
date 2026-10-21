"""Service layer for user settings mutations.

Wraps the settings upsert in an explicit unit of work so the write is committed
before the HTTP response is sent (issue #945), keeping transaction ownership in
the service layer rather than the controller.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.models import (
    UNSET,
    ContactsReimport,
    UserSettings,
    UserSettingsChanges,
    UserSettingsRepository,
)
from app.infrastructure.unit_of_work import transactional


class UserSettingsService:
    """Service for persisting per-user settings."""

    def __init__(
        self, settings_repo: UserSettingsRepository, contacts_reimport: ContactsReimport
    ) -> None:
        self.settings_repo = settings_repo
        self.contacts_reimport = contacts_reimport

    @transactional
    async def update_settings(
        self,
        user_id: str,
        changes: UserSettingsChanges,
        transaction: AsyncConnection,
    ) -> UserSettings:
        """Write the fields ``changes`` names (upsert) as a committed unit.

        Saving the default country forces a full contacts re-import in the same
        unit, so it is never saved without one (#1820). That holds even when
        the value is unchanged: re-saving it is how to recover a re-import that
        never ran, and comparing against a value read first would race another
        save.
        """
        saved = await self.settings_repo.update(user_id, changes)
        if changes.default_country is not UNSET:
            await self.contacts_reimport.force_full_contacts_sync(user_id)
        return saved

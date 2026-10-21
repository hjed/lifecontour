"""Domain models and repository protocol for user-level settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final, Protocol


class _Unset(Enum):
    """Marks a settings field a partial update leaves as it is."""

    UNSET = "unset"


UNSET: Final = _Unset.UNSET


@dataclass
class UserSettings:
    """Per-user application settings.

    ``timezone`` renders dates/times (including in AI prompts) in the user's
    local time. ``default_country`` (ISO 3166-1 alpha-2) fills in addresses
    imported without a country (#1820). Either is ``None`` when the user has not
    chosen one; callers wanting a zone to resolve with use
    ``UserSettingsRepository.get_timezone``, which applies the default.
    """

    user_id: str
    timezone: str | None = None
    default_country: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class UserSettingsChanges:
    """The fields a partial update writes; ``UNSET`` ones are left as they are.

    The timezone can be set but not cleared. ``None`` clears the country.
    """

    timezone: str | _Unset = UNSET
    default_country: str | None | _Unset = UNSET


class ContactsReimport(Protocol):
    """Re-imports a user's integration contacts in full.

    The default country fills in imported addresses with none (#1820); a
    contact an integration has not changed is never re-pulled, so saving the
    default has to force a full re-import for it to reach every contact.
    """

    async def force_full_contacts_sync(self, user_id: str) -> None:
        """Make the user's next contacts sync a full one."""
        ...


class UserSettingsRepository(Protocol):
    """Persistence boundary for user settings."""

    async def get_by_user_id(self, user_id: str) -> UserSettings | None:
        """Return the settings for a user, or None if none are stored."""
        ...

    async def save(self, settings: UserSettings) -> UserSettings:
        """Create or update every field of a user's settings (upsert)."""
        ...

    async def update(self, user_id: str, changes: UserSettingsChanges) -> UserSettings:
        """Create or update only the fields ``changes`` names (upsert)."""
        ...

    async def get_timezone(self, user_id: str) -> str:
        """Return the user's stored timezone, or the default if unset."""
        ...

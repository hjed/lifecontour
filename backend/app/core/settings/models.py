"""Domain models and repository protocol for user-level settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.settings.timezone_utils import DEFAULT_TIMEZONE


@dataclass
class UserSettings:
    """Per-user application settings.

    Currently holds the user's default timezone, used to render dates/times
    (including in AI prompts) in the user's local time.
    """

    user_id: str
    timezone: str = DEFAULT_TIMEZONE
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserSettingsRepository(Protocol):
    """Persistence boundary for user settings."""

    async def get_by_user_id(self, user_id: str) -> UserSettings | None:
        """Return the settings for a user, or None if none are stored."""
        ...

    async def save(self, settings: UserSettings) -> UserSettings:
        """Create or update the settings for a user (upsert)."""
        ...

    async def get_timezone(self, user_id: str) -> str:
        """Return the user's stored timezone, or the default if unset."""
        ...

    async def get_default_timezone(self) -> str:
        """Return a timezone for contexts without a user (single-user fallback).

        Background workers (e.g. contact-summary generation) have no request
        user. In this single-user system, return the sole stored timezone, or
        the default when none is configured.
        """
        ...

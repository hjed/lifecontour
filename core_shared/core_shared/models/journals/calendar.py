"""Calendar entity for the journal domain.

Calendars allow journals to be organized into groups and optionally
synced to Google Calendar. They provide color-coding for visual
organization in the UI.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .constants import MAX_CALENDAR_NAME_LENGTH
from .exceptions import CalendarValidationError

# Regex pattern for validating hex color format (#RRGGBB)
HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass
class Calendar:
    """
    Calendar entity for organizing journals.

    Calendars can be associated with journals (via CalendarInfo for EVENT types)
    and optionally synced to Google Calendar.

    Attributes:
        id: Unique identifier (UUID, auto-generated)
        user_id: User who owns this calendar
        name: Display name for the calendar (max 100 chars)
        color: Hex color for visual display (#RRGGBB format)
        description: Optional description
        is_synced_to_google: Whether to sync events to Google Calendar
        google_calendar_id: Google Calendar ID for sync (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    user_id: str
    name: str
    color: str
    id: UUID | None = None
    description: str | None = None
    is_synced_to_google: bool = False
    google_calendar_id: str | None = None
    access_role: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate calendar properties."""
        self._validate_user_id()
        self._validate_name()
        self._validate_color()
        self._validate_google_sync()

    def _validate_user_id(self) -> None:
        """Validate user_id is not empty."""
        if not self.user_id or not self.user_id.strip():
            raise CalendarValidationError("user_id", "User ID is required")

    def _validate_name(self) -> None:
        """Validate name is not empty and within length limit."""
        if not self.name or not self.name.strip():
            raise CalendarValidationError("name", "Calendar name is required")

        if len(self.name) > MAX_CALENDAR_NAME_LENGTH:
            raise CalendarValidationError(
                "name",
                f"Calendar name cannot exceed {MAX_CALENDAR_NAME_LENGTH} characters",
            )

    def _validate_color(self) -> None:
        """Validate color is in hex format (#RRGGBB)."""
        if not self.color:
            raise CalendarValidationError("color", "Calendar color is required")

        if not HEX_COLOR_PATTERN.match(self.color):
            raise CalendarValidationError(
                "color",
                "Calendar color must be in hex format (#RRGGBB)",
            )

    def _validate_google_sync(self) -> None:
        """Validate Google sync configuration."""
        if self.is_synced_to_google and not self.google_calendar_id:
            raise CalendarValidationError(
                "google_calendar_id",
                "Google Calendar ID is required when sync is enabled",
            )

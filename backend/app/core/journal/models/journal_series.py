"""Journal series entity.

A series groups related journal entries — either auto-created from a Google
Calendar recurring event (identified by ``calendar_id`` + ``recurring_event_id``)
or created manually via UI/MCP (e.g. a series of medical appointments). A journal
may belong to multiple series.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

MAX_SERIES_NAME_LENGTH = 500


@dataclass
class JournalSeries:
    """
    Journal series entity.

    Attributes:
        name: Series name (required, max 500 chars)
        user_id: User who owns this series
        id: UUID primary key (auto-generated)
        description: Optional free-text description
        calendar_id: Calendar the series was auto-created from (nullable)
        recurring_event_id: Google recurring master event id (nullable; set only
            for series auto-created from calendar sync)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    name: str
    user_id: str
    id: UUID | None = None
    description: str | None = None
    calendar_id: UUID | None = None
    recurring_event_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate series properties."""
        if not self.name or not self.name.strip():
            raise ValueError("Series name cannot be empty")
        if len(self.name) > MAX_SERIES_NAME_LENGTH:
            raise ValueError(
                f"Series name cannot exceed {MAX_SERIES_NAME_LENGTH} characters"
            )
        if not self.user_id or not self.user_id.strip():
            raise ValueError("Series user_id is required")

    @property
    def auto_created(self) -> bool:
        """Whether this series was auto-created from a recurring calendar event."""
        return self.recurring_event_id is not None

"""Value objects for the journal domain."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .exceptions import JournalValidationError


@dataclass(frozen=True)
class EventDateRange:
    """
    Value object representing a date range for journal events.

    Encapsulates the start and end timestamps for a journal entry,
    with validation to ensure start <= end.

    Attributes:
        start: The start datetime of the event (UTC timezone expected)
        end: The end datetime of the event (UTC timezone expected)
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """Validate the date range."""
        if self.start > self.end:
            raise JournalValidationError(
                "event_date_range",
                "event_date_range.start must be before or equal to event_date_range.end",
            )

    @property
    def duration(self) -> timedelta:
        """Calculate the duration of the event."""
        return self.end - self.start

    @property
    def is_point_in_time(self) -> bool:
        """Check if the event is a point in time (start == end)."""
        return self.start == self.end

    @property
    def is_multi_day(self) -> bool:
        """Check if the event spans multiple days."""
        return self.start.date() != self.end.date()

    def contains(self, dt: datetime) -> bool:
        """Check if a datetime falls within this date range."""
        return self.start <= dt <= self.end

    def overlaps(self, other: EventDateRange) -> bool:
        """Check if this date range overlaps with another."""
        return self.start <= other.end and other.start <= self.end

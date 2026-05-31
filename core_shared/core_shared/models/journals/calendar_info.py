"""CalendarInfo entity for the journal domain.

CalendarInfo represents the EVENT journal type data. A journal has the
EVENT type if a row exists in the journal_calendar_info table.

This entity stores calendar-specific information like times, location,
and sync settings for event-type journals.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from uuid import UUID

from .constants import MAX_LOCATION_LENGTH, MAX_TIMEZONE_LENGTH
from .event_state import EventState
from .exceptions import CalendarInfoValidationError


@dataclass
class CalendarInfo:
    """
    CalendarInfo entity for EVENT type journals.

    This entity represents additional data for journals that have the EVENT type.
    A journal is considered to have the EVENT type if a row exists in
    journal_calendar_info for that journal_id.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        calendar_id: Required calendar reference (UUID)
        description: Optional public event description
        start_time: Optional start time (null for all-day events)
        end_time: Optional end time (null for all-day events)
        is_all_day: Whether this is an all-day event
        location: Optional location string
        timezone: Optional IANA timezone string (e.g. 'Australia/Sydney')
        sync_invitees: Whether to sync invitees to Google Calendar
        private_description: When True, the description is not synced to external
            calendars and inbound description changes are blocked
        event_state: Event participation state (invited/tentative/confirmed/cancelled)
        event_start_date: Optional event start date for date-aware time validation
            (not persisted — used only during construction to validate time ordering
            for multi-day events that cross midnight)
        event_end_date: Optional event end date (same as above)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    calendar_id: UUID
    journal_id: int | None = None
    description: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    is_all_day: bool = False
    location: str | None = None
    timezone: str | None = None
    sync_invitees: bool = False
    private_description: bool = False
    event_state: EventState = EventState.CONFIRMED
    event_start_date: date | None = field(default=None, repr=False)
    event_end_date: date | None = field(default=None, repr=False)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate calendar info properties."""
        self._validate_journal_id()
        self._validate_calendar_id()
        self._validate_times()
        self._validate_location()
        self._validate_timezone()
        self._validate_event_state()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive if provided."""
        if self.journal_id is not None and self.journal_id <= 0:
            raise CalendarInfoValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_calendar_id(self) -> None:
        """Validate calendar_id is provided."""
        if self.calendar_id is None:
            raise CalendarInfoValidationError(
                "calendar_id", "Calendar ID is required for EVENT type journals"
            )

    def _validate_times(self) -> None:
        """Validate time consistency.

        Rules:
        - If is_all_day is True, start_time and end_time should be None
        - If is_all_day is False, either both times are None or both are provided
        - If both times are provided, start_time must be <= end_time
          (when event dates are provided, combines date+time for comparison
          to properly handle multi-day events that cross midnight)
        """
        if self.is_all_day:
            # All-day events should not have times
            if self.start_time is not None or self.end_time is not None:
                raise CalendarInfoValidationError(
                    "is_all_day",
                    "All-day events should not have start_time or end_time",
                )
        else:
            # Non-all-day events: both times provided or both None
            if (self.start_time is None) != (self.end_time is None):
                raise CalendarInfoValidationError(
                    "start_time",
                    "Both start_time and end_time must be provided, or both null",
                )

            # If both provided, validate order
            if self.start_time is not None and self.end_time is not None:
                if (
                    self.event_start_date is not None
                    and self.event_end_date is not None
                ):
                    # Use full date+time comparison for multi-day events
                    start_dt = datetime.combine(self.event_start_date, self.start_time)
                    end_dt = datetime.combine(self.event_end_date, self.end_time)
                    if start_dt > end_dt:
                        raise CalendarInfoValidationError(
                            "end_time",
                            "end_time must be after or equal to start_time",
                        )
                elif self.start_time > self.end_time:
                    raise CalendarInfoValidationError(
                        "end_time",
                        "end_time must be after or equal to start_time",
                    )

    def _validate_location(self) -> None:
        """Validate location length."""
        if self.location is not None and len(self.location) > MAX_LOCATION_LENGTH:
            raise CalendarInfoValidationError(
                "location",
                f"Location cannot exceed {MAX_LOCATION_LENGTH} characters",
            )

    def _validate_event_state(self) -> None:
        """Validate event_state is a valid EventState value."""
        if not isinstance(self.event_state, EventState):
            try:
                self.event_state = EventState(self.event_state)
            except ValueError, KeyError, TypeError:
                raise CalendarInfoValidationError(
                    "event_state",
                    f"Invalid event state: {self.event_state}. "
                    f"Must be one of: {', '.join(e.value for e in EventState)}",
                ) from None

    def _validate_timezone(self) -> None:
        """Validate timezone is a valid IANA timezone string."""
        if self.timezone is not None:
            if len(self.timezone) > MAX_TIMEZONE_LENGTH:
                raise CalendarInfoValidationError(
                    "timezone",
                    f"Timezone cannot exceed {MAX_TIMEZONE_LENGTH} characters",
                )
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError, KeyError:
                raise CalendarInfoValidationError(
                    "timezone",
                    f"Invalid IANA timezone: {self.timezone}",
                ) from None

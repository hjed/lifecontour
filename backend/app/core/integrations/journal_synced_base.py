"""The synced base of a journal's calendar event, as the journal holds it.

The journal push sends Google only the fields local changed since the base
(#1899), so an applied pull records, per field, whether the journal now holds
Google's value: these key the journal's side of that comparison.
"""

from typing import Any

from core_shared.calendar_sync_base import (
    CalendarSyncField,
    description_key,
    local_when,
    location_key,
    summary_key,
    when_key,
)
from core_shared.models.journals import CalendarInfo, Journal


def stored_calendar_info(row: Any) -> CalendarInfo | None:
    """A ``journal_calendar_info`` row as the entity the keys are read from."""
    if row is None:
        return None
    return CalendarInfo(
        calendar_id=row.calendar_id,
        is_all_day=bool(row.is_all_day),
        start_time=row.start_time,
        end_time=row.end_time,
        timezone=row.timezone,
        location=row.location,
        validate=False,
    )


def local_event_keys(
    journal: Journal, calendar_info: CalendarInfo | None, *, user_timezone: str | None
) -> dict[CalendarSyncField, str]:
    """The key of each event field as the journal holds it now."""
    keys = {
        CalendarSyncField.SUMMARY: summary_key(journal.title),
        CalendarSyncField.DESCRIPTION: description_key(journal.content),
    }
    if calendar_info is not None:
        keys[CalendarSyncField.LOCATION] = location_key(calendar_info.location)
        keys[CalendarSyncField.WHEN] = when_key(
            *local_when(
                journal.event_date_range.start,
                journal.event_date_range.end,
                calendar_info,
                user_timezone=user_timezone,
            )
        )
    return keys

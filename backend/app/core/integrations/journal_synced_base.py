"""What an inbound calendar update may change, judged against the synced base.

The journal push sends Google only the fields local changed since the base
(#1899), so an applied pull can be just as precise: it takes Google's value
for every field local has *not* changed since the base, and keeps local's for
the rest — those are edits the push still owes Google. Before bases existed
the only signal was journal-wide (``journals.updated_at`` after the link's), so
a local edit to the notes held back Google's new title, and the next push then
overwrote it. That rule still applies to whatever the base does not record.
"""

from collections.abc import Mapping
from typing import Any, Final

from core_shared.calendar_sync_base import (
    CalendarBase,
    CalendarSyncField,
    description_key,
    local_when,
    location_key,
    summary_key,
    when_key,
)
from core_shared.models.journals import CalendarInfo, Journal

# The journal fields an inbound merge writes for each event field. Location
# lives on the calendar info alone, so it is kept there rather than here.
JOURNAL_FIELDS: Final[Mapping[CalendarSyncField, tuple[str, ...]]] = {
    CalendarSyncField.SUMMARY: ("title",),
    CalendarSyncField.DESCRIPTION: ("content",),
    CalendarSyncField.WHEN: ("event_date_range_start", "event_date_range_end"),
    CalendarSyncField.LOCATION: (),
}

# Without a base, a local edit protects these, and only these.
_PROTECTED_BY_LOCAL_EDITS: Final = (
    CalendarSyncField.SUMMARY,
    CalendarSyncField.DESCRIPTION,
)


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


def protected_journal_fields(
    base: CalendarBase,
    changed: frozenset[CalendarSyncField],
    *,
    local_edits: bool,
) -> frozenset[str]:
    """The journal fields an inbound merge must keep as they are.

    Those of every field local changed since the base, and — for a field the
    base does not record — what a local edit protected before bases existed.
    """
    fields = set(changed)
    if local_edits:
        fields.update(field for field in _PROTECTED_BY_LOCAL_EDITS if field not in base)
    return frozenset(name for field in fields for name in JOURNAL_FIELDS[field])


def kept_calendar_info_data(
    inbound: Mapping[str, Any],
    stored: CalendarInfo | None,
    changed: frozenset[CalendarSyncField],
) -> dict[str, Any]:
    """The calendar info to save: the inbound one, with local's changes kept."""
    kept = dict(inbound)
    if stored is None:
        return kept
    if CalendarSyncField.WHEN in changed:
        kept.update(
            is_all_day=stored.is_all_day,
            start_time=stored.start_time,
            end_time=stored.end_time,
            timezone=stored.timezone,
        )
    if CalendarSyncField.LOCATION in changed:
        kept["location"] = stored.location
    return kept

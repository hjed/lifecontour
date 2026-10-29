"""The synced base of a calendar event a journal is pushed to (#1899).

The journal push PATCHes four fields of a Google Calendar event. Each is
keyed here (see :mod:`core_shared.sync_base`) so the worker and the backend
agree on what "unchanged since the base" means: the push sends only the fields
whose local key is not in the base, and an applied pull takes Google's value
only for a field whose local key still is.

A field's base is a *set* of keys: the value the push sent and the value
Google answered with, which differ when Google reformats it. Either spelling
counts as the agreed value on both sides.

Values are keyed in the form the push sends them, and Google's in the form a
pull would store them, so the two compare like for like: a title as the
inbound transformer normalises it, and the event's times as the
``start``/``end`` blocks of the Google payload, read as instants.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

from core_shared.models.journals import CalendarInfo
from core_shared.sync_base import entry_key

# The title a pull gives an event Google holds with a blank summary, and the
# one the push sends for an untitled journal.
UNTITLED_EVENT: Final = "Untitled Event"

UTC_OFFSET_SUFFIX: Final = "+00:00"


class CalendarSyncField(StrEnum):
    """A field of the Google event that the journal push writes.

    ``WHEN`` is the start and end together: they are only valid as a pair (a
    timed start with an all-day end is refused), so they merge as one.
    """

    SUMMARY = "summary"
    DESCRIPTION = "description"
    LOCATION = "location"
    WHEN = "when"


# Fields an inbound *update* applies to the journal. A pull writes the
# description only when it creates the journal, so Google winning it on a push
# leaves nothing for the next pull to import.
IMPORTABLE_ON_UPDATE: Final = frozenset(
    {CalendarSyncField.SUMMARY, CalendarSyncField.LOCATION, CalendarSyncField.WHEN}
)

type CalendarBase = Mapping[CalendarSyncField, frozenset[str]]


def summary_key(summary: str | None) -> str:
    """The key of an event's title, blank read as the untitled title."""
    return entry_key((summary or "").strip() or UNTITLED_EVENT)


def description_key(description: str | None) -> str:
    """The key of an event's description; absent and empty are the same."""
    return entry_key((description or "").strip())


def location_key(location: str | None) -> str:
    """The key of an event's location; absent and empty are the same."""
    return entry_key((location or "").strip())


def _instant(block: Mapping[str, object]) -> tuple[str, str] | None:
    """One ``start``/``end`` block as a comparable ``(kind, value)``.

    A date is kept as the date; a date-time is read as a UTC instant, since
    Google echoes it in the event's own zone rather than as it was sent.
    """
    date_value = block.get("date")
    if isinstance(date_value, str):
        return ("date", date_value)
    date_time = block.get("dateTime")
    if not isinstance(date_time, str):
        return None
    parsed = datetime.fromisoformat(date_time.replace("Z", UTC_OFFSET_SUFFIX))
    if parsed.tzinfo is None:
        time_zone = block.get("timeZone")
        named = zone(time_zone if isinstance(time_zone, str) else None) or UTC
        parsed = parsed.replace(tzinfo=named)
    return ("dateTime", parsed.astimezone(UTC).isoformat())


def when_key(start: Mapping[str, object], end: Mapping[str, object]) -> str:
    """The key of an event's ``start`` and ``end`` blocks, as one field."""
    return entry_key(_instant(start), _instant(end))


def changed(key: str, base: frozenset[str] | None) -> bool:
    """Whether a value moved away from the base; with no base, always."""
    return base is None or key not in base


def zone(timezone_str: str | None) -> tzinfo | None:
    """The zone ``timezone_str`` names, or ``None`` when absent or unknown."""
    if not timezone_str:
        return None
    try:
        return ZoneInfo(timezone_str)
    except Exception:  # noqa: BLE001
        return None


def _anchor(instant: datetime, clock: time, tz: tzinfo) -> datetime:
    """``clock`` on the local date of ``instant`` in ``tz``, as a UTC instant.

    On the day clocks go back a wall time in the repeated hour names two
    instants, and the ``TIME`` column that held ``clock`` cannot say which.
    The stored instant can: if the second pass reproduces it, that is the
    one meant; otherwise the first pass, which is also what an unambiguous
    time resolves to.
    """
    first = datetime.combine(instant.astimezone(tz).date(), clock, tzinfo=tz)
    second = first.replace(fold=1)
    # Compared in UTC: an ambiguous aware datetime never compares equal
    # across zones (PEP 495), so a direct comparison would always be false.
    if second.utcoffset() != first.utcoffset() and second.astimezone(UTC) == instant:
        return second.astimezone(UTC)
    return first.astimezone(UTC)


def local_datetime(dt_utc: datetime, timezone_str: str | None) -> datetime:
    """``dt_utc`` read in ``timezone_str``, or unchanged when there is no zone."""
    tz = zone(timezone_str)
    return dt_utc if tz is None else dt_utc.astimezone(tz)


def google_event_times(
    start_dt: datetime, end_dt: datetime, calendar_info: CalendarInfo
) -> tuple[dict[str, str], dict[str, str]]:
    """The ``start`` and ``end`` blocks of a Google Calendar event payload.

    Journal date-range bounds are UTC instants of *local* midnight, so the
    calendar date an event falls on has to be read in the event's timezone:
    midnight on 5 Sept in Sydney is 14:00 UTC on 4 Sept. Without a zone the
    UTC date is used.

    An all-day event becomes a ``date`` pair with Google's exclusive end (the
    day after the last day). A timed event becomes a ``dateTime`` pair. Its
    clock times are only meaningful in the zone they were entered in, so they
    are anchored to the local date in the event's *own* zone and otherwise
    left alone: an event with no zone, or no clock times, pushes the stored
    instants as they are. (An imported event's times are local to the Google
    event's zone; re-anchoring them in any other zone would move the event.)
    """
    if calendar_info.is_all_day:
        local_start = local_datetime(start_dt, calendar_info.timezone)
        local_end = local_datetime(end_dt, calendar_info.timezone)
        return (
            {"date": local_start.strftime("%Y-%m-%d")},
            {"date": (local_end + timedelta(days=1)).strftime("%Y-%m-%d")},
        )

    tz = zone(calendar_info.timezone)
    if tz is not None:
        if calendar_info.start_time is not None:
            start_dt = _anchor(start_dt, calendar_info.start_time, tz)
        if calendar_info.end_time is not None:
            end_dt = _anchor(end_dt, calendar_info.end_time, tz)

    # ISO 8601 with a 'Z' suffix for UTC; Google accepts offsets either way.
    start_payload = {"dateTime": start_dt.isoformat().replace(UTC_OFFSET_SUFFIX, "Z")}
    end_payload = {"dateTime": end_dt.isoformat().replace(UTC_OFFSET_SUFFIX, "Z")}
    if calendar_info.timezone:
        start_payload["timeZone"] = calendar_info.timezone
        end_payload["timeZone"] = calendar_info.timezone
    return start_payload, end_payload


def local_when(
    start_dt: datetime,
    end_dt: datetime,
    calendar_info: CalendarInfo,
    *,
    user_timezone: str | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """The ``start`` and ``end`` blocks the push sends for a journal.

    The stored bounds are UTC instants of local midnight, so the date an
    all-day event falls on is read in the event's own zone, else the user's
    configured one, else UTC. A timed event's clock times are only anchored
    in the zone the row itself records: an imported event's times are local
    to the Google event's zone, which older rows never stored, and
    re-anchoring them in the user's zone would move the event.
    """
    timezone = calendar_info.timezone
    if calendar_info.is_all_day and not timezone:
        timezone = user_timezone
    anchored = CalendarInfo(
        calendar_id=calendar_info.calendar_id,
        journal_id=calendar_info.journal_id,
        start_time=calendar_info.start_time,
        end_time=calendar_info.end_time,
        is_all_day=calendar_info.is_all_day,
        timezone=timezone,
        validate=False,
    )
    return google_event_times(start_dt, end_dt, anchored)

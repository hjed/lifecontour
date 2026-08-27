"""Cross-calendar identity for a Google Calendar event.

The same real-world event appears in two calendars whenever one calendar
invites the other, and Google gives each copy its own event id — so
``external_event_id`` identifies an event only *within* one calendar. Syncing
on that alone produces two journals for one meeting.

This module is the single place that knows how Google says "these are the
same event", and it collapses that knowledge into one opaque token. The
outbox payload, the backend and the database all treat the token as a
meaningless string whose only property is equality, so the whole scheme can
change here without anything downstream knowing.

Two facts from the `Events reference
<https://developers.google.com/workspace/calendar/api/v3/reference/events>`_
shape it:

- ``iCalUID`` "uniquely identifies an event across calendaring systems" — it
  is what survives the copy into the invited calendar.
- **Every occurrence of a recurring event shares one ``iCalUID``.** So the
  uid alone would collapse a weekly meeting into a single journal; the
  instance's ``originalStartTime`` is what tells the occurrences apart.

Hence ``iCalUID`` + ``originalStartTime``, the latter normalised to UTC
because each calendar reports it in its own timezone.
"""

import hashlib
from datetime import UTC, date, datetime, tzinfo

from calendar_models import GoogleEvent, GoogleEventStartEnd

SOURCE_PREFIX = "google"

# Matches journal_external_event_links.external_identity.
MAX_IDENTITY_LENGTH = 512

_UTC_OFFSET_SUFFIX = "+00:00"


def build_event_identity(google_event: GoogleEvent) -> str | None:
    """Build the cross-calendar identity token for an event.

    Args:
        google_event: The inbound event, as returned by ``events.list``.

    Returns:
        A token equal for every copy of this event in any calendar, or
        ``None`` when the event carries no trustworthy identity — in which
        case the caller falls back to per-calendar behaviour and the event
        may still be journalled twice. That is the lesser failure: a token
        built on a guess could merge two genuinely different events, and a
        wrongly merged journal is far harder to recover from than a
        duplicate one.
    """
    ical_uid = (google_event.ical_uid or "").strip()
    if not ical_uid:
        return None

    instance_start = _normalise_instance_start(google_event.original_start_time)
    if instance_start is None:
        # A recurring instance whose start we cannot read would otherwise
        # fall back to the bare uid — which every other instance of the
        # series shares. Withhold the token rather than merge the series.
        return None

    return _cap_length(f"{SOURCE_PREFIX}:{ical_uid}:{instance_start}")


def _normalise_instance_start(
    original_start: GoogleEventStartEnd | None,
) -> str | None:
    """Reduce an instance's original start to a stable UTC string.

    Returns an empty string for a single event, an ISO-8601 UTC instant for
    a recurring instance, or ``None`` when the value cannot be parsed.
    """
    if original_start is None:
        return ""

    if original_start.date:
        parsed_date = _parse_date(original_start.date)
        if parsed_date is None:
            return None
        # An all-day instance is a date, not an instant; both calendars
        # report the same date, so pin it to UTC midnight.
        return datetime(
            parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC
        ).isoformat()

    if original_start.date_time:
        parsed_instant = _parse_instant(
            original_start.date_time, original_start.time_zone
        )
        if parsed_instant is None:
            return None
        return parsed_instant.isoformat()

    # An originalStartTime carrying neither field says nothing about which
    # instance this is, so treat it as a single event.
    return ""


def _parse_date(date_str: str) -> date | None:
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def _parse_instant(date_time_str: str, time_zone_str: str | None) -> datetime | None:
    """Parse a Google datetime into UTC.

    Each calendar renders the same instant in its own timezone, so the
    offset has to be resolved before the value can be compared.
    """
    if date_time_str.endswith("Z"):
        date_time_str = date_time_str[:-1] + _UTC_OFFSET_SUFFIX

    try:
        parsed = datetime.fromisoformat(date_time_str)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_resolve_timezone(time_zone_str))

    return parsed.astimezone(UTC)


def _resolve_timezone(time_zone_str: str | None) -> tzinfo:
    """Resolve the event's IANA timezone, falling back to UTC."""
    if not time_zone_str:
        return UTC
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(time_zone_str)
    except Exception:  # noqa: BLE001
        return UTC


def _cap_length(identity: str) -> str:
    """Keep the token inside the column it is stored in.

    Hashing preserves the only property the token has — equality — so two
    copies of an event with a very long uid still match.
    """
    if len(identity) <= MAX_IDENTITY_LENGTH:
        return identity

    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{SOURCE_PREFIX}:sha256:{digest}"

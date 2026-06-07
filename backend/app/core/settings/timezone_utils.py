"""Timezone resolution and formatting helpers.

Centralises how the application converts UTC timestamps into the user's
preferred timezone and renders them with explicit timezone information.
This is used when building AI prompts so the model never has to guess the
timezone of a date/time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# IANA name used whenever no timezone is configured or a stored value is
# invalid. Kept as a plain string so callers can compare against it directly.
DEFAULT_TIMEZONE = "UTC"


def resolve_timezone(name: str | None) -> ZoneInfo:
    """Resolve an IANA timezone name to a ``ZoneInfo``.

    Falls back to UTC when the name is missing or not a known timezone, so
    callers never have to handle invalid configuration.
    """
    if not name:
        return ZoneInfo(DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def to_user_tz(dt: datetime, tz: ZoneInfo) -> datetime:
    """Return ``dt`` expressed in ``tz``.

    Naive datetimes are assumed to be UTC (the database stores UTC), matching
    the rest of the codebase's convention.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz)


def now_in_tz(timezone: str | None, now: datetime | None = None) -> datetime:
    """Return the current time (or ``now``) expressed in ``timezone``."""
    base = now if now is not None else datetime.now(tz=UTC)
    return to_user_tz(base, resolve_timezone(timezone))


def _offset_label(local: datetime) -> str:
    """Render the UTC offset of an aware datetime as ``+HH:MM``."""
    offset = local.strftime("%z")  # e.g. "+1000"
    if not offset:
        return "+00:00"
    return f"{offset[:3]}:{offset[3:]}"


def format_datetime(dt: datetime, timezone: str | None) -> str:
    """Format ``dt`` in ``timezone`` with an explicit timezone label.

    Example: ``2026-06-07 10:00:00 AEST (UTC+10:00)``.
    """
    local = to_user_tz(dt, resolve_timezone(timezone))
    return (
        f"{local.strftime('%Y-%m-%d %H:%M:%S')} "
        f"{local.tzname()} (UTC{_offset_label(local)})"
    )


def isoformat_in_tz(dt: datetime, timezone: str | None) -> str:
    """Return ``dt`` as an ISO-8601 string in ``timezone`` (offset included)."""
    return to_user_tz(dt, resolve_timezone(timezone)).isoformat()

"""Activity journals and their aggregates, as ``ActivityStatsRepository`` reads them.

An *activity journal* is a journal with fitness data. Its **effective activity
type** is the most specific activity subtype it carries, chosen by
:data:`ACTIVITY_TYPE_PRECEDENCE` — a canyoning trip also carries outdoor-activity
and fitness rows, and is reported as canyoning — falling back to ``fitness``.

The metrics are read from the journal's fitness row, in that row's units, with a
missing value counted as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from core_shared.models.journals import EventDateRange, Journal, JournalType

ACTIVITY_TYPE_PRECEDENCE: tuple[JournalType, ...] = (
    JournalType.CANYONING,
    JournalType.CAVING,
    JournalType.CROSS_COUNTRY_SKIING,
    JournalType.KAYAKING,
    JournalType.CLIMBING,
    JournalType.ABSEILING_TRIP,
    JournalType.BUSHWALKING,
    JournalType.JOGGING,
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
)


class ActivityMetric(StrEnum):
    """A fitness metric a personal record can be set on."""

    DISTANCE = "distance"
    DURATION = "duration"
    ELEVATION_GAIN = "elevation_gain"
    CALORIES = "calories"


class TrendInterval(StrEnum):
    """The bucket width an activity trend is grouped by."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


def parse_activity_type(activity_type: str | None) -> str | None:
    """Normalise an effective activity type filter, rejecting unknown types.

    Raises:
        ValueError: If ``activity_type`` is not one of the effective types.
    """
    if activity_type is None:
        return None

    normalized = activity_type.strip().lower()
    allowed_types = {journal_type.value for journal_type in ACTIVITY_TYPE_PRECEDENCE}
    if normalized not in allowed_types:
        allowed = ", ".join(sorted(allowed_types))
        raise ValueError(
            f"Invalid activity_type '{activity_type}'. Must be one of: {allowed}"
        )
    return normalized


@dataclass(frozen=True)
class ActivityFilters:
    """Which of a user's activity journals a read covers.

    ``activity_type`` is an effective type already normalised by
    :func:`parse_activity_type`. The date bounds select journals whose event range
    overlaps ``[start_date, end_date]``. ``search_query`` matches title or content
    as a case-insensitive substring.
    """

    user_id: str
    activity_type: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    search_query: str | None = None


@dataclass(frozen=True)
class ActivityJournalRow:
    """An activity journal with its effective type and metrics."""

    journal: Journal
    activity_type: str
    distance: int
    duration: int
    elevation_gain: int
    calories: int


@dataclass(frozen=True)
class ActivityTotalsRow:
    """Metric totals across every matching activity journal."""

    total_activities: int
    total_distance: int
    total_duration: int
    total_elevation_gain: int
    total_calories: int


@dataclass(frozen=True)
class ActivityTypeTotalsRow:
    """Metric totals for the matching journals of one effective activity type."""

    activity_type: str
    count: int
    total_distance: int
    total_duration: int
    total_elevation_gain: int
    total_calories: int


@dataclass(frozen=True)
class ActivityPersonalRecordRow:
    """The matching journal with the highest value of one metric."""

    activity_type: str
    journal_id: int
    journal_title: str
    value: int


@dataclass(frozen=True)
class ActivityTrendRow:
    """Metric totals for the matching journals starting in one interval bucket."""

    period_start: date
    activity_count: int
    total_distance: int
    total_duration: int
    total_elevation_gain: int


@dataclass(frozen=True)
class RouteUsageRow:
    """A journal a route was used on, with that journal's fitness metrics if any."""

    journal_id: int
    journal_title: str
    activity_type: str
    event_date_range: EventDateRange
    distance: int | None
    duration: int | None

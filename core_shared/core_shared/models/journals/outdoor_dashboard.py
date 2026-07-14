"""Read-model contracts and pure rules for the outdoor logbook dashboard.

The dashboard is a projection over existing tables — no new journal state. A
repository gathers the per-journal rows below and the service applies the
window/cap/grouping rules:

- **Upcoming activities** — outdoor journals and OUTDOOR_PLANNING journals
  overlapping the next ~30 days, soonest-first, capped.
- **Activity totals** — counts of outdoor activities by *effective* journal
  type over rolling 30/365-day windows. Journal types are detected purely by
  subtype-row presence, so :func:`effective_outdoor_journal_types` reduces
  dependency-implied rows (e.g. the bushwalking row every canyoning journal
  carries) to the composite type the user actually recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .journal_types import JournalType
from .value_objects import EventDateRange

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .outdoor_activity_subtypes import OutdoorActivitySubtype


@dataclass
class UpcomingOutdoorActivity:
    """An upcoming outdoor journal or OUTDOOR_PLANNING event for the widget."""

    journal_id: int
    title: str
    event_date_range: EventDateRange
    subtypes: list[OutdoorActivitySubtype] = field(default_factory=list)
    is_planning: bool = False


@dataclass
class OutdoorActivityTypeFacts:
    """Per-journal facts the activity-totals grouping is computed from."""

    journal_id: int
    event_date_range: EventDateRange
    subtypes: list[OutdoorActivitySubtype] = field(default_factory=list)


@dataclass
class OutdoorActivityTotals:
    """Outdoor activity counts by journal type over the two rolling windows."""

    last_30_days: dict[str, int] = field(default_factory=dict)
    last_365_days: dict[str, int] = field(default_factory=dict)


def effective_outdoor_journal_types(
    subtypes: Sequence[OutdoorActivitySubtype],
) -> list[JournalType]:
    """Reduce present subtype rows to the journal types the user recorded.

    Present types minus dependency-implied types (via
    :meth:`JournalType.get_dependencies`): canyoning + bushwalking + abseiling
    rows reduce to ``[CANYONING]``, while genuinely independent subtypes each
    count. A journal with no subtype rows is still an outdoor activity, so an
    empty sequence yields ``[OUTDOOR_ACTIVITY]``. Sorted for determinism.
    """
    present = {JournalType(subtype.value) for subtype in subtypes}
    implied = {
        dependency
        for journal_type in present
        for dependency in JournalType.get_dependencies(journal_type)
    }
    effective = present - implied
    if not effective:
        return [JournalType.OUTDOOR_ACTIVITY]
    return sorted(effective, key=lambda journal_type: journal_type.value)

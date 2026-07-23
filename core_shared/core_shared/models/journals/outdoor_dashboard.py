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
- **Checked-out gear** — GEAR_USAGE journals whose *resolved* checkout window
  contains "now" and that Snipe-IT hasn't already returned.
  :func:`is_currently_checked_out` is the single source of that rule; the
  buffer-date/event-range resolution itself happens in SQL (``COALESCE``),
  mirroring the Snipe-IT worker's check-in sweep.
- **Templates done** — per-template done-counts over the abseiling-derived
  journals referencing each template, grouped by template type, plus a count of
  the distinct templates done inside the dashboard's recent window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .journal_types import JournalType
from .value_objects import EventDateRange

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

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
    """Outdoor activity counts by journal type over the two rolling windows.

    ``total_last_*`` count *journals*, not type-buckets: a journal recording two
    genuinely independent subtypes contributes to two per-type counts but is
    still one logged activity, so the totals cannot be recovered by summing the
    per-type mappings.
    """

    last_30_days: dict[str, int] = field(default_factory=dict)
    last_365_days: dict[str, int] = field(default_factory=dict)
    total_last_30_days: int = 0
    total_last_365_days: int = 0


@dataclass
class GearCheckoutFacts:
    """Per-usage facts the checked-out-gear determination is computed from.

    ``checkout_date``/``checkin_date`` are the *resolved* window bounds —
    the optional buffer overrides falling back to the journal's event range
    (``COALESCE`` in SQL) — matching the Snipe-IT worker's date resolution.
    ``snipeit_checked_in`` is True when a successful ``snipeit_checkin``
    sync row records that the asset has already been returned.
    """

    journal_id: int
    gear_item_id: str
    gear_name: str
    checkout_date: datetime
    checkin_date: datetime
    snipeit_checked_in: bool = False


@dataclass
class CheckedOutGearItem:
    """A gear item currently checked out, for the dashboard widget."""

    gear_item_id: str
    name: str
    checked_out_since: datetime
    journal_id: int


@dataclass
class TemplateReferenceFacts:
    """One abseiling-derived journal's reference to an activity template.

    ``event_date_range`` is the referencing journal's own event range — when the
    template was actually done — so the recent-templates window can be applied
    without a second query.
    """

    journal_id: int
    template_id: str
    template_name: str
    template_type: str
    event_date_range: EventDateRange


@dataclass
class TemplateDone:
    """A template the user has done, with its per-template done-count."""

    template_id: str
    name: str
    template_type: str
    done_count: int


@dataclass
class TemplatesDoneSummary:
    """The templates-done widget's grouping plus its recent-unique headline.

    ``by_type`` is the all-time grouping shown in the widget;
    ``recent_unique_count`` is how many *distinct* templates were done inside
    the dashboard's recent window, which is the headline stat and cannot be
    derived from ``by_type`` (whose counts are all-time).
    """

    by_type: dict[str, list[TemplateDone]] = field(default_factory=dict)
    recent_unique_count: int = 0


def is_currently_checked_out(facts: GearCheckoutFacts, now: datetime) -> bool:
    """Whether a gear usage means the item is checked out right now.

    Checked out ⇔ the resolved window contains ``now`` (checkout inclusive,
    check-in exclusive — at the resolved check-in instant the sweep returns
    the asset) and Snipe-IT hasn't already recorded the return.
    """
    return (
        not facts.snipeit_checked_in and facts.checkout_date <= now < facts.checkin_date
    )


def checked_out_gear(
    facts: Sequence[GearCheckoutFacts], now: datetime
) -> list[CheckedOutGearItem]:
    """The gear items currently checked out, longest-out first.

    A gear item appears once even when several open usages reference it —
    the earliest active checkout is when it physically left. Ordered by
    ``checked_out_since`` ascending (journal id tiebreak) for determinism.
    """
    earliest_active: dict[str, GearCheckoutFacts] = {}
    for entry in facts:
        if not is_currently_checked_out(entry, now):
            continue
        current = earliest_active.get(entry.gear_item_id)
        if current is None or (entry.checkout_date, entry.journal_id) < (
            current.checkout_date,
            current.journal_id,
        ):
            earliest_active[entry.gear_item_id] = entry
    return [
        CheckedOutGearItem(
            gear_item_id=entry.gear_item_id,
            name=entry.gear_name,
            checked_out_since=entry.checkout_date,
            journal_id=entry.journal_id,
        )
        for entry in sorted(
            earliest_active.values(),
            key=lambda entry: (entry.checkout_date, entry.journal_id),
        )
    ]


def templates_done_by_type(
    references: Sequence[TemplateReferenceFacts],
) -> dict[str, list[TemplateDone]]:
    """Unique templates done with per-template counts, grouped by type.

    Each referencing journal counts once toward its template's done-count.
    Types and the templates within them are name-sorted for determinism.
    """
    counts: dict[str, int] = {}
    templates: dict[str, TemplateReferenceFacts] = {}
    for reference in references:
        counts[reference.template_id] = counts.get(reference.template_id, 0) + 1
        templates.setdefault(reference.template_id, reference)

    grouped: dict[str, list[TemplateDone]] = {}
    for reference in sorted(
        templates.values(),
        key=lambda entry: (entry.template_type, entry.template_name, entry.template_id),
    ):
        grouped.setdefault(reference.template_type, []).append(
            TemplateDone(
                template_id=reference.template_id,
                name=reference.template_name,
                template_type=reference.template_type,
                done_count=counts[reference.template_id],
            )
        )
    return grouped


def count_unique_templates_in_window(
    references: Sequence[TemplateReferenceFacts], window: EventDateRange
) -> int:
    """How many distinct templates were done inside ``window``.

    A template done several times in the window counts once. Membership uses
    the same overlap predicate as the activity totals, so a multi-day trip
    straddling a window boundary still counts.
    """
    return len(
        {
            reference.template_id
            for reference in references
            if reference.event_date_range.overlaps(window)
        }
    )


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

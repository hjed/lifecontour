"""Which days a change makes a daily summary stale.

The pure half of ITER18-005 Phase 7's invalidation: no I/O, no repositories and
no clock, so the whole mapping is a unit test and the service above it is left
with the reads.

**A journal occupies a span of days, not a day.** ``SqlJournalRepository.get_all``
selects a day's journals by *overlap* —
``event_date_range_end >= :start AND event_date_range_start <= :end`` — so a
journal running Friday to Sunday is part of three days' summaries and a change
to it makes three stale. The handler this phase replaces mapped every journal to
``event_date_range.start.date()``, a single **UTC** date, which is two of the
four defects ITER18-004 Phase 4f recorded against it: the multi-day case and the
zone.

**A task's days follow its due journal, and the two halves are different
questions.** The current day's prompt lists the not-done tasks whose due journal
*starts* inside ``[today, today + 7]`` (``find_upcoming_tasks`` filters on the
start instant); a past day's prompt lists what was due in *that day's* journals,
which is the overlap set again. So a due span behind the user invalidates the
days it covers, and one ahead of the user invalidates **today** — never both,
because a span starting before today cannot start inside a window that opens on
it.

The result is a set of **ranges** rather than dates on purpose: invalidation is
one guarded ``UPDATE`` per range over rows that already exist, so an unbounded
span needs neither a cap nor an enumeration of its days.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.journal.services.journal_date_resolver import local_date

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from core_shared.models.date_window import UpcomingWindow
    from core_shared.models.journals import EventDateRange


@dataclass(frozen=True)
class DaySpan:
    """A run of consecutive local days, both ends **inclusive**.

    Inclusive because that is what "the days this journal is part of" means and
    because :class:`~core_shared.models.date_window.UpcomingWindow` is inclusive
    for the same reason — one convention across the phase, rather than an
    off-by-one waiting at every boundary between them.

    Attributes:
        first_day: The earliest day of the span
        last_day: The latest day of the span; equal to ``first_day`` for a
            journal that begins and ends on one local day
    """

    first_day: datetime.date
    last_day: datetime.date

    def __post_init__(self) -> None:
        """Refuse a reversed span.

        A caller that produced one has a bug — the same call
        ``resolve_occurrence`` makes about a reversed window — and reporting it
        as "no days to invalidate" would leave a summary stale with nothing to
        show for it.
        """
        if self.last_day < self.first_day:
            raise ValueError(
                f"last_day {self.last_day} must not precede first_day {self.first_day}"
            )

    def contains(self, day: datetime.date) -> bool:
        """Whether a day falls in the span, both ends included."""
        return self.first_day <= day <= self.last_day

    def clipped_before(self, day: datetime.date) -> DaySpan | None:
        """The part of this span strictly before ``day``, if any.

        The past-day half of a task's answer: the days that already describe how
        the task resolved, as opposed to the week ahead, which is rendered on
        the current day's prompt alone.

        Returns:
            The clipped span, or ``None`` when nothing of it lies before
            ``day``.
        """
        if self.first_day >= day:
            return None
        return DaySpan(
            first_day=self.first_day,
            last_day=min(self.last_day, day - datetime.timedelta(days=1)),
        )


@dataclass(frozen=True)
class InvalidationTarget:
    """A user's summaries over a span of days, to be marked stale.

    Frozen and hashable so a set collapses the duplicates the mapping naturally
    produces — an edit that moved a journal's clock but not its day yields the
    same span twice, and that should cost one statement rather than two.
    """

    user_id: str
    span: DaySpan

    @classmethod
    def for_day(cls, user_id: str, day: datetime.date) -> InvalidationTarget:
        """The single-day case, which is most of them."""
        return cls(user_id=user_id, span=DaySpan(first_day=day, last_day=day))


def day_span_of(event_date_range: EventDateRange, tz: ZoneInfo) -> DaySpan:
    """The local days an event date range touches, in the acting user's zone.

    ``local_date`` rather than ``.date()``: the instants are stored in UTC, and
    22:00 UTC is already tomorrow in Sydney. Every day question in this codebase
    resolves through that pair, so this cannot disagree with the window the
    assembler builds for the same journal.

    An event ending exactly at local midnight reaches the following day, which
    is deliberate: the day query selects on ``event_date_range_end >= :start``
    and that day's window begins at precisely that instant, so the journal *is*
    in that day's summary and the span has to agree or the day would never be
    invalidated.
    """
    return DaySpan(
        first_day=local_date(event_date_range.start, tz),
        last_day=local_date(event_date_range.end, tz),
    )


def targets_for_journal(user_id: str, *spans: DaySpan) -> frozenset[InvalidationTarget]:
    """Every day of every span given, as targets.

    Variadic because a journal whose dates moved has **two** spans — where it
    was and where it is — and invalidating only the second is the defect
    ITER18-004 Phase 4f recorded first: the day the journal left keeps a
    ``GENERATED`` summary whose counters still include it.
    """
    return frozenset(InvalidationTarget(user_id=user_id, span=span) for span in spans)


def targets_for_task_due_span(
    user_id: str,
    due_span: DaySpan,
    *,
    today: datetime.date,
    window: UpcomingWindow,
) -> frozenset[InvalidationTarget]:
    """The days a change to this task makes stale.

    Args:
        user_id: The task's owner
        due_span: The local day span of the task's **due** journal
        today: Today's date, already resolved in that user's timezone
        window: The week ahead, from the same ``today``

    Returns:
        At most one target. The past half is the span clipped to the days behind
        the user; the forward half is today itself, and only when the due
        journal *starts* inside the window — which is the predicate
        ``find_upcoming_tasks`` applies, rather than an overlap, so a journal
        that began last week and runs into this one is in no upcoming listing.
    """
    past = due_span.clipped_before(today)
    if past is not None:
        return frozenset({InvalidationTarget(user_id=user_id, span=past)})
    if window.contains(due_span.first_day):
        return frozenset({InvalidationTarget.for_day(user_id, today)})
    return frozenset()

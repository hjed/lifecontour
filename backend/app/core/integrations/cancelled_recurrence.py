"""The keep-next rule for a recurrence whose occurrences are being cancelled.

Google never sends a "this recurrence now ends" message. A truncated or deleted
recurrence arrives as one cancellation per upcoming occurrence, delivered in
whatever order the outbox relay replays them. The rule this module encodes is:

    Within each unbroken run of cancelled, not-yet-started occurrences, the
    first one stays (marked cancelled, so the user sees what is no longer on)
    and every later one is deleted.

A live occurrence ends a run. Occurrences that have already started are
history: they are never kept *as the next one* and never deleted.

The planner is pure and looks at the whole recurrence, which is what makes the
outcome independent of arrival order. A single cancellation can only change
the verdicts of the cancelled occurrence and of its successor, so the processor
acts on just those two (:func:`affected_by_cancel`) instead of re-checking the
whole recurrence each time. Whether a ``DELETE`` verdict is actually carried
out - a journal the user has added to is kept - is decided by the caller.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CancelledInstanceVerdict(StrEnum):
    """What the keep-next rule says about one cancelled upcoming occurrence."""

    KEEP_AS_NEXT = "keep_as_next"
    DELETE = "delete"


@dataclass(frozen=True)
class RecurrenceInstance:
    """One occurrence of a recurrence, as far as the keep-next rule cares."""

    journal_id: int
    start: datetime
    cancelled: bool


def _upcoming_in_order(
    instances: Iterable[RecurrenceInstance], now: datetime
) -> list[RecurrenceInstance]:
    """Not-yet-started occurrences, earliest first, ties broken by journal id."""
    return sorted(
        (i for i in instances if i.start > now),
        key=lambda i: (i.start, i.journal_id),
    )


def plan_cancelled_recurrence(
    instances: Iterable[RecurrenceInstance], now: datetime
) -> dict[int, CancelledInstanceVerdict]:
    """A verdict for every cancelled, not-yet-started occurrence.

    Live and started occurrences get no verdict.
    """
    verdicts: dict[int, CancelledInstanceVerdict] = {}
    previous_cancelled = False
    for instance in _upcoming_in_order(instances, now):
        if instance.cancelled:
            verdicts[instance.journal_id] = (
                CancelledInstanceVerdict.DELETE
                if previous_cancelled
                else CancelledInstanceVerdict.KEEP_AS_NEXT
            )
        previous_cancelled = instance.cancelled
    return verdicts


def affected_by_cancel(
    instances: Sequence[RecurrenceInstance], journal_id: int, now: datetime
) -> tuple[int, ...]:
    """The occurrences whose verdict one cancellation can change.

    That is the cancelled occurrence itself and the next one to start after
    it: cancelling an occurrence can only turn its successor from the first of
    a run into a continuation of one. Empty when the occurrence is unknown.
    """
    subject = next((i for i in instances if i.journal_id == journal_id), None)
    if subject is None:
        return ()
    successor = next(
        (
            i
            for i in _upcoming_in_order(instances, now)
            if (i.start, i.journal_id) > (subject.start, subject.journal_id)
        ),
        None,
    )
    if successor is None:
        return (subject.journal_id,)
    return (subject.journal_id, successor.journal_id)


def next_upcoming_after(
    instances: Iterable[RecurrenceInstance], after: datetime, now: datetime
) -> int | None:
    """The first not-yet-started occurrence starting after ``after``.

    Used when an occurrence leaves the recurrence altogether (a split's new
    recurrence adopted its journal): the one after the slot it left is the
    only verdict its going can change.
    """
    return next(
        (i.journal_id for i in _upcoming_in_order(instances, now) if i.start > after),
        None,
    )

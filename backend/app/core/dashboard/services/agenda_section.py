"""The order today's agenda is read in.

The wireframe states it in two clauses — all-day entries pinned above timed ones
(**W12**), timed ones ascending by start (**W13**) — and the specification states
the same thing in prose: *"Today's event journals are listed in time order.
All-day items are pinned above timed items."*

**It is a pin, not a tie-break.** An all-day entry outranks every timed one
however early the timed one begins, because an all-day item is not a thing
happening at 00:00; it is a thing true of the whole day, and the card marks it
``ALL DAY`` rather than giving it a time.

**Timed entries sort by the stored instant, not by the clock time the card
draws.** A journal that began yesterday and runs through today carries a
``start_time`` belonging to another day, so ordering by that component would
interleave it with today's entries at an hour that never happened today. The
instant is also the quantity the day window compares against, so the list is
ordered by the same measure that decided which entries are on it. Ties fall back
to the journal id, so two events that really do start at once render the same way
on every request.

Pure, and deliberately not a method on the service: the rule is the whole product
of this phase, it is only meaningful at its boundaries, and a function over a
sequence is the shape those boundaries can be asserted at without a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from app.core.dashboard.models.sections import AgendaEntry


def order_agenda_entries(entries: Iterable[AgendaEntry]) -> tuple[AgendaEntry, ...]:
    """Today's entries in the order the agenda card renders them.

    Args:
        entries: The day's event journals, in any order — typically a
            repository's list, which is left untouched.

    Returns:
        A new tuple: every all-day entry first, then the timed ones, each group
        ascending by the instant it starts and then by journal id.
    """
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                not entry.is_all_day,
                entry.starts_at,
                entry.journal_id,
            ),
        )
    )

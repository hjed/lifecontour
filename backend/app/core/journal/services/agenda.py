"""Reading a day's agenda, and the order it comes back in.

Both callers of the agenda — the home dashboard's card and the daily summary's
prompt — come through ``agenda_for_day``, so neither builds the day window
itself and neither can order the day differently. The rule below is what
"differently" would mean.

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

Pure, and deliberately not a method on a service: the rule is only meaningful at
its boundaries, and a function over a sequence is the shape those boundaries can
be asserted at without a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.journal.services.journal_date_resolver import local_day_window

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date
    from zoneinfo import ZoneInfo

    from app.core.journal.models.agenda import AgendaEntry
    from app.core.journal.models.repositories import AgendaRepository


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


async def agenda_for_day(
    repo: AgendaRepository, user_id: str, day: date, tz: ZoneInfo
) -> tuple[AgendaEntry, ...]:
    """One local day's event journals, in the order the agenda draws them.

    The window and the anchor are the whole of what a caller could get wrong,
    and neither is visible in the entries that come back: an all-day event is
    matched against the *date*, a timed one by overlap against the *instants*,
    and a window built from anything but ``local_day_window`` would quietly
    disagree with the dashboard about which events are on today.

    So this exists rather than each caller assembling the same three lines. The
    home dashboard reads today and tomorrow through it; the daily summary reads
    the current day through it, and the two therefore cannot describe different
    days as "today" or order the same day differently.

    Args:
        repo: The agenda read port.
        user_id: The acting user — every window is scoped to them.
        day: The local day to read, in ``tz``.
        tz: The user's configured timezone, which decides where the day starts.

    Returns:
        The day's entries, all-day first and then ascending by start instant.
    """
    entries = await repo.list_entries_in_window(
        user_id, window=local_day_window(day, tz), anchor=day
    )
    return order_agenda_entries(entries)

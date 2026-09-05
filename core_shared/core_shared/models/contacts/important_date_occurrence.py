"""When a stored important date next comes round, and what that makes it.

A contact's important date is stored as loose components — a year, a month and
a day, any of which may be absent — rather than as a date. This module turns one
of those rows into the **occurrence** falling inside a window of days: the date
it lands on, how far away that is, and how many years it makes when the row
carries a year to count from.

**Precision decides whether a date recurs at all**, and it is the only thing
that decides:

===================  ====================================  ==================
``DatePrecision``    Occurrence                            Derived ``years``
===================  ====================================  ==================
``YEAR``             none — no month or day to place it    —
``DAY_MONTH``        the month and day, in some year       ``None``
``FULL``             the month and day, in some year       years since stored
===================  ====================================  ==================

**No ``date_type`` is excluded** (ITER18-004's open decision 4). The question
the iteration document asked — whether ``first_met`` belongs, since it has no
in-window occurrence at ``year`` precision — is already answered by the table
above: ``year`` precision yields nothing *whatever the type*, so a type filter
would be a second rule overlapping the first. Birthdays and the two anniversary
types recur by definition; ``custom`` is user-named and the user is the only
authority on what it means; and a ``first_met`` somebody recorded to the day is
a real anniversary. Naming the type is presentation — "turns 35" against
"34 years" — and belongs to the surface, so what travels back is a bare count.

**The window is two dates, and that is what keeps this module pure.** It reads
no clock and takes no timezone: a day window is only meaningful once somebody
has anchored it in the acting user's configured zone, and that anchoring belongs
to the caller that knows whose day it is. Both ends are **inclusive**, so a date
occurring today is in the window — which is the whole point of a dashboard
section that exists to give notice.

Nothing here raises over data, and there is more malformed data possible than
one might expect. A row whose month and day are not a real date is storable (the
day is range-checked 1–31 with no month cross-check), and so is one whose *year*
is not a calendar year at all — the year is range-checked nowhere, unlike the
month and the day. A surface resolving a page of contacts must degrade on those
rows rather than fail on them or report nonsense from them.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .important_date_types import DatePrecision

if TYPE_CHECKING:
    from .entities import ImportantDate

#: February, and the day of it that only exists every fourth year.
_FEBRUARY = 2
_LEAP_DAY = 29

#: Where 29 February is observed in a year that does not have one.
#:
#: The alternatives were to drop the date — which hides a birthday in three
#: years out of four, from a section whose only job is to give notice — or to
#: move it to 1 March, which puts it in a month the user did not write down.
#: The 28th keeps it in February and adjacent to the real day.
_OBSERVED_LEAP_DAY = 28


@dataclass(frozen=True)
class ImportantDateOccurrence:
    """A stored date, placed on the day it falls in a window.

    Frozen because it is entirely derived: everything on it is a function of the
    important date and the window it was judged against, so there is nothing a
    caller could correct by editing it.

    Attributes:
        important_date: The row this resolves, carried so a caller resolving
            many need not pair the answers back up with their questions
        occurs_on: The date it lands on — the *observed* date where those
            differ, so this is always a day that exists
        days_away: Days from the window's ``first_day``, which every real caller
            anchors on today; zero means today
        years: Full years between the stored date and this occurrence, or
            ``None`` where there is no answer — either the row carries no year,
            or it carries one *after* the occurrence, and a negative age is not
            an age. ``0`` is a real count, not a missing one: it is what the
            year a date was first recorded makes
        observed_for_leap_day: Whether ``occurs_on`` is a stand-in — true only
            for 29 February resolved into a year without one. It exists so the
            substitution is inspectable rather than a silently different date
    """

    important_date: ImportantDate
    occurs_on: datetime.date
    days_away: int
    years: int | None
    observed_for_leap_day: bool


def _place(year: int, month: int, day: int) -> tuple[datetime.date, bool] | None:
    """The day a month-and-day lands on in ``year``, and whether it stood in.

    Returns ``None`` when the components are not a date in any year — 30
    February, 31 April — as distinct from 29 February, which is not a date in
    *this* year but is observed rather than dropped.
    """
    try:
        return datetime.date(year, month, day), False
    except ValueError:
        pass

    if (month, day) == (_FEBRUARY, _LEAP_DAY):
        return datetime.date(year, _FEBRUARY, _OBSERVED_LEAP_DAY), True

    return None


def _years_since(important_date: ImportantDate, occurs_on: datetime.date) -> int | None:
    """Full years from the stored date to this occurrence, where there are any.

    ``None`` in three cases, and the occurrence is returned in all of them
    because the month and day are still real:

    - the row carries no year to count from;
    - its year is not a **calendar** year. Unlike the month and the day, the
      year is range-checked nowhere — not by ``__post_init__``, not by the API
      schema, and not by a column constraint — so ``year=0`` is storable, and
      subtracting it would report a birthday as "turns 2026";
    - its year is *after* the occurrence. A date stored in the future still
      recurs, but the count it implies is negative, and a negative age is not
      an age.
    """
    if important_date.precision is not DatePrecision.FULL:
        return None
    if important_date.year is None:  # pragma: no cover - the entity forbids it
        return None
    if not datetime.MINYEAR <= important_date.year <= datetime.MAXYEAR:
        return None

    difference = occurs_on.year - important_date.year
    return difference if difference >= 0 else None


def resolve_occurrence(
    important_date: ImportantDate,
    *,
    first_day: datetime.date,
    last_day: datetime.date,
) -> ImportantDateOccurrence | None:
    """The occurrence of ``important_date`` inside the window, if there is one.

    Every year the window touches is a candidate, which is what lets a window
    running from December into January find a January date, and what makes the
    answer for a window longer than a year the **earliest** occurrence in it
    rather than an arbitrary one.

    Args:
        important_date: The stored row, at whatever precision it was recorded
        first_day: The first day of the window, **inclusive** — today, for every
            caller that resolved it in the acting user's timezone. ``days_away``
            is measured from here
        last_day: The last day of the window, **inclusive**

    Returns:
        The occurrence, or ``None`` when the date does not fall in the window,
        has no month and day to place, or names a day no year has.

        The **precision** is the authority on whether a row recurs, not the
        components it happens to be carrying. ``ImportantDate`` is a mutable
        dataclass whose ``__post_init__`` clears the month and day of a
        ``YEAR``-precision row on construction, but a row reassigned afterwards
        would keep them, and answering from the leftovers would resurrect a date
        the user said they only knew the year of.

    Raises:
        ValueError: ``last_day`` precedes ``first_day``. A reversed window is a
            bug in the caller rather than a question with an empty answer, so it
            is not quietly reported as "nothing coming up".
    """
    if last_day < first_day:
        raise ValueError(f"last_day {last_day} must not precede first_day {first_day}")

    if important_date.precision is DatePrecision.YEAR:
        return None

    month, day = important_date.month, important_date.day
    if month is None or day is None:
        return None

    for year in range(first_day.year, last_day.year + 1):
        placed = _place(year, month, day)
        if placed is None:
            continue

        occurs_on, observed_for_leap_day = placed
        if first_day <= occurs_on <= last_day:
            return ImportantDateOccurrence(
                important_date=important_date,
                occurs_on=occurs_on,
                days_away=(occurs_on - first_day).days,
                years=_years_since(important_date, occurs_on),
                observed_for_leap_day=observed_for_leap_day,
            )

    return None

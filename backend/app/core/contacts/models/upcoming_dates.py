"""Which important contact dates are coming up, and in what order to show them.

The home dashboard's upcoming-dates section shows "important contact dates
falling in the next **seven days** ... ordered by date ascending then by
**contact importance descending**". That is this module, and it is **pure**: the
window is arithmetic over a date the caller resolved in the user's timezone, the
recurrence is ITER18-004 Phase 9's ``resolve_occurrence``, and the importance is
ITER18-004 Phase 10's shared read. Nothing here touches a clock, a timezone or a
database.

**The recurrence is not pushed into SQL, and the query is not allowed to guess.**
A stored row carries loose components — a month and a day, sometimes a year —
so "does it fall in the next seven days" is a question about a rule, not about a
column. What the database is asked instead is the narrow question it *can*
answer cheaply: *which stored ``(month, day)`` pairs could possibly land in this
window*. :func:`window_month_days` decides that, and it has one rule beyond the
obvious.

**The leap day is that rule.** A row stored as 29 February is **observed on 28
February** in a year that has no 29th, so its occurrence date and its stored
pair are not the same. A candidate set built only from the days the window
spells would never fetch the row, and a leap-day birthday would be missing from
the section in three years out of four — silently, since a date that is never
fetched cannot be reported as dropped. So the 29th is asked for whenever the
window covers a 28 February that is not itself a leap day.

**Importance breaks ties within a day; it never reorders the days.**
``ContactImportance.ranking_key`` is negated for exactly this, so
``(occurs_on, *ranking_key, …)`` sorts ascending in one pass — soonest date
first and, within a date, most important contact first — rather than sorting
twice or reversing a key that would flip the date too.

**The window is not capped here.** ITER18-004 Phase 13 settled the shape for
both evidence sections: the whole window travels with its total and the card
applies the cap, so a show-more reveals the remainder without a second request.
The count is named anyway because that is what the show-more renders.
"""

from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.important_date_occurrence import resolve_occurrence
from core_shared.models.date_window import (
    DEFAULT_UPCOMING_DAYS_AHEAD,
    DateWindowError,
    UpcomingWindow,
)
from core_shared.models.date_window import upcoming_window as _shared_upcoming_window

from app.core.contacts.models.importance import ContactImportance

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from core_shared.models.contacts.entities import ImportantDate
    from core_shared.models.contacts.important_date_occurrence import (
        ImportantDateOccurrence,
    )

#: February, and the day of it that only exists every fourth year.
_FEBRUARY = 2
_LEAP_DAY = 29

#: Where 29 February is observed in a year that does not have one. Stated in
#: ``important_date_occurrence`` and repeated here only as the *question* the
#: candidate query must ask; the substitution itself is made there.
_OBSERVED_LEAP_DAY = 28


@dataclass(frozen=True)
class UpcomingDateContact:
    """The contact a date belongs to, as a dashboard row shows them.

    A plain reference. Deliberately not the ``Contact`` aggregate: a section
    that renders an avatar and a name has no use for methods, addresses, notes
    or tags, and carrying them would make the read fetch what nothing displays.

    Attributes:
        id: The contact's id, which the row links to
        display_name: The name to show — their nickname where they have one
        photo_url: Their avatar, when they have one
    """

    id: int
    display_name: str
    photo_url: str | None


@dataclass(frozen=True)
class ContactImportantDate:
    """A stored important date and the contact it belongs to.

    What the candidate query returns, and nothing more: no occurrence, no
    ranking, nothing derived. Keeping the adapter's output this dumb is what
    stops a second copy of the recurrence rule appearing in SQL.
    """

    important_date: ImportantDate
    contact: UpcomingDateContact


@dataclass(frozen=True)
class UpcomingContactDate:
    """One date coming up: whose it is, when it lands, and why it ranks there.

    Attributes:
        occurrence: The resolved occurrence — the day it falls on, how far away
            that is, the derived years where the precision allows one, and
            whether the day stood in for a 29 February
        contact: Whose date it is
        importance: The signals it was ranked by, carried so a surface can show
            what the ordering was based on rather than re-reading it
    """

    occurrence: ImportantDateOccurrence
    contact: UpcomingDateContact
    importance: ContactImportance


@dataclass(frozen=True)
class UpcomingContactDates:
    """The answer to "whose dates are coming up", carrying the question with it.

    The window travels beside the dates for the same reason ``UpcomingTasks``
    carries its own: a surface renders "the next seven days" too, and a caller
    that had to re-derive the window from the rows could not describe an
    **empty** one at all.

    Attributes:
        window: The window these dates were selected for
        dates: The survivors, in display order
    """

    window: UpcomingWindow
    dates: tuple[UpcomingContactDate, ...]

    @property
    def total(self) -> int:
        """How many dates fall in the window.

        The same as ``len(dates)``, because the window is **not capped** —
        ITER18-004 Phase 13 settled that the whole window travels and the card
        applies the cap, so a show-more costs no second request. It is named
        anyway because that is what the show-more renders, and naming it keeps a
        later reader from mistaking it for a pagination total that might exceed
        the rows returned.
        """
        return len(self.dates)


def upcoming_dates_window(
    today: datetime.date, days_ahead: int = DEFAULT_UPCOMING_DAYS_AHEAD
) -> UpcomingWindow:
    """The window this section covers, in the acting user's timezone.

    The **same** window the tasks section uses — the specification requires the
    two to match, so both are built by
    :func:`core_shared.models.date_window.upcoming_window` and cannot drift into
    disagreeing about which days "this week" means. Only the error is this
    domain's: a bad ``days_ahead`` on a contacts surface is a
    ``ContactValidationError``, and a caller catching that would not catch the
    shared module's own exception.

    Args:
        today: Today's date **in the acting user's timezone**
        days_ahead: How far to look; zero is today alone

    Returns:
        The window, both ends inclusive.

    Raises:
        ContactValidationError: ``days_ahead`` is negative or beyond the shared
            maximum.
    """
    try:
        return _shared_upcoming_window(today, days_ahead)
    except DateWindowError as error:
        raise ContactValidationError(error.field, error.reason) from error


def window_month_days(window: UpcomingWindow) -> tuple[tuple[int, int], ...]:
    """The stored ``(month, day)`` pairs that could land in ``window``.

    Every day the window covers, plus **29 February** whenever the window covers
    a 28 February in a year that has no 29th — because that is the day a
    leap-day row is observed on, and a candidate set without it would never
    fetch the row to observe.

    Nothing broader is needed. When the window covers a *real* 29 February the
    pair is already one of the window's own days, and every other unplaceable
    pair (30 February, 31 April) yields no occurrence at all, so it cannot be
    missed by an exact-pair filter.

    Args:
        window: The window, whose length the shared bound caps at 91 days

    Returns:
        The pairs, in window order and without repeats, ready to be handed to
        the candidate query as two parallel integer arrays.
    """
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()

    def add(pair: tuple[int, int]) -> None:
        if pair not in seen:
            seen.add(pair)
            pairs.append(pair)

    for day in window.days():
        add((day.month, day.day))
        if (day.month, day.day) == (
            _FEBRUARY,
            _OBSERVED_LEAP_DAY,
        ) and not calendar.isleap(day.year):
            add((_FEBRUARY, _LEAP_DAY))

    return tuple(pairs)


def _no_signals(contact_id: int) -> ContactImportance:
    """The importance of a contact the signals read did not answer for.

    ``for_contacts`` omits ids that no longer exist, and a contact deleted
    between the two reads must not blank a whole dashboard section over a
    missing ranking input. Zero signals rank last, which is where an unknown
    contact belongs anyway.
    """
    return ContactImportance(
        contact_id=contact_id,
        is_favourite=False,
        journal_count_30d=0,
        activity_count_30d=0,
        last_activity_at=None,
    )


def _sort_key(date: UpcomingContactDate) -> tuple[int | datetime.date, ...]:
    """Soonest date first, then most important contact, then a stable tail.

    The importance terms are already negated by ``ranking_key``, so the whole
    key sorts **ascending** in one pass. The tail is load-bearing rather than
    defensive: a week routinely holds two dates on one day, and two contacts
    with identical signals are ordinary — without it the same request could
    answer in a different order between runs, which a user sees as the list
    shuffling itself.

    The contact comes before the date row because a contact with two dates on
    one day should have them adjacent rather than interleaved with somebody
    else's.
    """
    return (
        date.occurrence.occurs_on,
        *date.importance.ranking_key,
        date.contact.id,
        date.occurrence.important_date.id or 0,
    )


def select_upcoming_dates(
    candidates: Iterable[ContactImportantDate],
    window: UpcomingWindow,
    importance: Mapping[int, ContactImportance],
) -> UpcomingContactDates:
    """The dates a dashboard shows for this window, in display order.

    Pure: the rows arrive fetched and the signals arrive read, so nothing here
    can contradict either. A candidate that does not resolve to an occurrence
    inside the window is dropped — which duplicates what the query's pair filter
    almost certainly achieved already, deliberately, so the boundary is
    assertable without a database and a query that over-fetches still fails its
    own tests rather than being papered over here.

    Args:
        candidates: The stored rows the query judged possible, in any order
        window: The window they should be judged against
        importance: Signals by contact id; a missing contact ranks last

    Returns:
        The window and its survivors, ordered by occurrence date, then contact
        importance descending, then contact and date row for stability.
    """
    resolved: list[UpcomingContactDate] = []

    for row in candidates:
        occurrence = resolve_occurrence(
            row.important_date,
            first_day=window.first_day,
            last_day=window.last_day,
        )
        if occurrence is None:
            continue
        resolved.append(
            UpcomingContactDate(
                occurrence=occurrence,
                contact=row.contact,
                importance=importance.get(row.contact.id)
                or _no_signals(row.contact.id),
            )
        )

    return UpcomingContactDates(
        window=window, dates=tuple(sorted(resolved, key=_sort_key))
    )

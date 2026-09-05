"""The span of days a "what is coming up" listing covers.

Two sections of the home dashboard look ahead over the **same** days: the tasks
section shows "not-done tasks whose due journal falls between today and seven
days ahead", and the upcoming-dates section shows important contact dates over
"the next seven days, matching the tasks window". That is one span, and this is
where it is defined, so the two cannot drift apart into a Sunday one section
includes and the other does not.

**It lives here rather than in either domain** because neither owns it. The
window was built first in ``models/tasks/upcoming.py`` (ITER18-001 Phase 14),
which was right while tasks were its only caller; ITER18-004 Phase 9 declined to
reuse it from the contacts side and said the judgement belonged to the phase
where a second real caller existed. This is that phase, and the alternative — a
parallel ``OccurrenceWindow`` — would have been a second definition of the same
seven days.

**What does not live here is the error type.** A rejected ``days_ahead`` is a
400 about a *surface's* parameter, and a contacts endpoint answering with a task
validation error would be nonsense. So the bound is checked once, here, and
raises a neutral :class:`DateWindowError` that each domain translates into its
own validation error. One rule, two vocabularies.

**The window is dates, not instants.** Turning ``first_day``/``last_day`` into
the instants a query needs belongs to the caller that knows the user's timezone;
doing it here would mean this module took a ``ZoneInfo``, and the whole point of
a date-shaped window is that the timezone has already been applied.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

#: The specification's default: today and the seven days after it.
DEFAULT_UPCOMING_DAYS_AHEAD = 7

#: The furthest ahead a caller may look.
#:
#: There is deliberately no unbounded task list in this product — no screen
#: shows every task — and an arbitrarily large window would be one through the
#: back door, on a query that resolves every journal and contact it touches.
#: Ninety days is far beyond the week the dashboard asks for while still being a
#: bound; a caller who wants more is asking for a different feature.
MAX_UPCOMING_DAYS_AHEAD = 90


class DateWindowError(ValueError):
    """A window a caller asked for that is not a window.

    Deliberately *not* a domain validation error: this module is shared, and
    the domain a bad parameter belongs to is the caller's to name. The field and
    the reason are carried separately so a caller can rebuild its own error
    without parsing a sentence.

    Attributes:
        field: The parameter at fault, as a surface names it
        reason: What is wrong with the value, without the field name in it
    """

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


@dataclass(frozen=True)
class UpcomingWindow:
    """The span of days a listing covers, in the acting user's timezone.

    Both ends are **inclusive**, which is the word the specification uses and
    the one an off-by-one gets wrong.

    Attributes:
        first_day: Today, in the user's timezone
        last_day: ``days_ahead`` days after it
        days_ahead: What the caller asked for, kept so a surface can echo the
            window it was given rather than making the client subtract two dates
            to find out what it got
    """

    first_day: datetime.date
    last_day: datetime.date
    days_ahead: int

    def contains(self, day: datetime.date) -> bool:
        """Whether a date falls in the window, both ends included."""
        return self.first_day <= day <= self.last_day

    def days(self) -> tuple[datetime.date, ...]:
        """Every date in the window, in order, both ends included.

        Used by callers that must enumerate the window rather than test
        membership — the upcoming-dates query builds its candidate month/day
        pairs this way. Bounded by :data:`MAX_UPCOMING_DAYS_AHEAD`, so this is
        at most 91 dates.
        """
        return tuple(
            self.first_day + datetime.timedelta(days=offset)
            for offset in range(self.days_ahead + 1)
        )


def upcoming_window(
    today: datetime.date, days_ahead: int = DEFAULT_UPCOMING_DAYS_AHEAD
) -> UpcomingWindow:
    """The window running from ``today`` to ``days_ahead`` days after it.

    Args:
        today: Today's date **in the acting user's timezone**. Resolved by the
            caller, because a window anchored on UTC's today is wrong for
            everybody east of Greenwich for part of every day.
        days_ahead: How far to look. Zero is a legitimate request — today
            alone — rather than an empty window.

    Returns:
        The window, both ends inclusive.

    Raises:
        DateWindowError: ``days_ahead`` is negative or beyond
            :data:`MAX_UPCOMING_DAYS_AHEAD`. Raised here rather than left to
            each surface's parameter validation so every surface inherits one
            answer — the surfaces bound it as well, which is what turns it into
            a 400 before any query runs.
    """
    if days_ahead < 0:
        raise DateWindowError("days_ahead", f"must not be negative, got {days_ahead}")
    if days_ahead > MAX_UPCOMING_DAYS_AHEAD:
        raise DateWindowError(
            "days_ahead",
            f"must be at most {MAX_UPCOMING_DAYS_AHEAD} days, got {days_ahead}",
        )

    return UpcomingWindow(
        first_day=today,
        last_day=today + datetime.timedelta(days=days_ahead),
        days_ahead=days_ahead,
    )

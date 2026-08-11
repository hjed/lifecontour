"""The upcoming window: which tasks are "coming up", and in what order.

The specification's dashboard shows "not-done tasks whose due journal falls
between **today and seven days ahead**, inclusive", soonest first, with done,
cancelled and lapsed tasks absent. That is this module, and it is **pure**: the
window is arithmetic over a date the caller resolved, and the selection reads
only what a :class:`TaskReadModel` already carries.

**Today is in the window.** That is not the same rule as the future-dated
invariant on a due journal, which excludes today deliberately, and the two are
easy to conflate. They ask different questions: "may this become a deadline"
versus "is this deadline coming up". A task written yesterday for today is
exactly what the dashboard exists to surface.

**The lapse is read, never re-derived.** :func:`select_upcoming_tasks` consults
``TaskReadModel.lapsed``, which ``build_task_read_model`` derived from the due
journal the assembler resolved. Recomputing it from the dates here would be a
second definition that could drift from the first — and would need the cancelled
flag, which is the half a date comparison cannot see.

That last point is what makes the *cancelled due journal* the only exclusion
that genuinely bites: a date-passed lapse cannot fall inside a forward window by
construction, because the window starts today. So a rule that filtered on status
and dates alone would look correct against every fixture except that one.

**The window is dates, not instants.** Turning ``first_day``/``last_day`` into
the instants a query needs belongs to the caller that knows the user's timezone;
doing it here would mean this module took a ``ZoneInfo``, and the whole point of
a date-shaped window is that the timezone has already been applied.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exceptions import TaskValidationError
from .task_status import TaskStatus

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .read_model import TaskReadModel

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
        TaskValidationError: ``days_ahead`` is negative or beyond
            :data:`MAX_UPCOMING_DAYS_AHEAD`. Raised here rather than left to
            each surface's parameter validation so REST and MCP inherit one
            answer — the surfaces bound it as well, which is what turns it into
            a 400 before any query runs.
    """
    if days_ahead < 0:
        raise TaskValidationError(
            "days_ahead", f"must not be negative, got {days_ahead}"
        )
    if days_ahead > MAX_UPCOMING_DAYS_AHEAD:
        raise TaskValidationError(
            "days_ahead",
            f"must be at most {MAX_UPCOMING_DAYS_AHEAD} days, got {days_ahead}",
        )

    return UpcomingWindow(
        first_day=today,
        last_day=today + datetime.timedelta(days=days_ahead),
        days_ahead=days_ahead,
    )


def _sort_key(model: TaskReadModel) -> tuple[datetime.date, int]:
    """Soonest deadline first, ties broken by task id.

    The same key ``link_role`` orders a journal's groups by, so the two listings
    present the same tasks in the same order. The tie-break is load-bearing
    rather than defensive: a dashboard week routinely holds several tasks due on
    one day, and without it the same request could answer in a different order
    between runs.
    """
    return (model.due_journal.date, model.task.id or 0)


@dataclass(frozen=True)
class UpcomingTasks:
    """The answer to "what is coming up", carrying the question with it.

    The window travels beside the tasks for the same reason ``JournalTaskGroups``
    carries its ``journal_id``: a surface renders both — "the next seven days"
    is part of what the user is told — and a caller that had to re-derive the
    window from the rows could not describe an **empty** one at all.

    Attributes:
        window: The window these tasks were selected for
        tasks: The survivors, ordered by due-journal date then task id
    """

    window: UpcomingWindow
    tasks: tuple[TaskReadModel, ...]

    @property
    def total(self) -> int:
        """How many tasks fall in the window.

        The same as ``len(tasks)``, because the window is **not capped** —
        ITER18-004 settles that the whole window travels and the dashboard's
        five-item cap is applied by the UI, so a show-more costs no second
        request. It is named anyway because that is what the show-more renders,
        and naming it keeps a later reader from mistaking it for a pagination
        total that might exceed the rows returned.
        """
        return len(self.tasks)


def select_upcoming_tasks(
    models: Iterable[TaskReadModel] | Sequence[TaskReadModel],
    window: UpcomingWindow,
) -> UpcomingTasks:
    """The tasks a dashboard shows for this window, in display order.

    Pure: the models arrive assembled and the same objects are handed back, so
    the lapse verdict and the contacts the assembler decided cannot be
    contradicted here.

    Three exclusions, and they compose:

    - **not in the window** — the due journal's date is outside it;
    - **not outstanding** — the task is done or cancelled;
    - **lapsed** — read from the model, which in a forward window means its due
      journal was cancelled.

    The window check duplicates what a caller's query almost certainly filtered
    already. That is deliberate: it makes the boundary day assertable without a
    database, and a query that under-fetches still fails its own tests rather
    than being papered over here.

    Args:
        models: The assembled read models, in any order
        window: The window they should be judged against

    Returns:
        The window and its survivors, ordered by due-journal date then task id.
    """
    return UpcomingTasks(
        window=window,
        tasks=tuple(
            sorted(
                (
                    model
                    for model in models
                    if model.task.status is TaskStatus.NOT_DONE
                    and not model.lapsed
                    and window.contains(model.due_journal.date)
                ),
                key=_sort_key,
            )
        ),
    )

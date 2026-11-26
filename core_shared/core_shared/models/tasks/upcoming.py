"""The upcoming window: which tasks are "coming up", and in what order.

The dashboard's Tasks card shows the not-done tasks dated between **today and
seven days ahead**, inclusive, plus overdue list tasks for seven days after they
became late: overdue first, oldest first, then everything else soonest first,
with done, cancelled, lapsed, undated and archived-list tasks absent. That is
this module, and it is **pure**: the window is arithmetic over a date the caller
resolved, and the selection reads only what a :class:`TaskReadModel` already
carries.

**One rule for both kinds of task.** A journal-only task is dated by its due
journal; a list task by its due date or due journal. Either way a task due in a
journal is placed on the journal's *first* day and is late only once its *last*
day has ended — then a journal-only task lapses and a list task is overdue. In
between, while the journal is **under way**, the task is due *today*: a
multi-day trip's commitments stay on the card for the whole trip.

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

Overdue is read the same way, from ``TaskReadModel.overdue``. The only date
arithmetic here is the seven-day allowance, counted from the day the task
became late, and the placement of a task under way on today.

**The window itself is no longer defined here.** ``UpcomingWindow`` and its
bound moved to :mod:`core_shared.models.date_window` in ITER18-004 Phase 11,
when the dashboard's upcoming-dates section needed the *same* span — the
specification says it covers "the next seven days, matching the tasks window",
so the two must be one definition rather than two that agree today. What stays
here is the **translation**: a bad ``days_ahead`` on a task surface is a
``TaskValidationError``, and the shared module cannot know that.

**The window is dates, not instants.** Turning ``first_day``/``last_day`` into
the instants a query needs belongs to the caller that knows the user's timezone;
doing it there would mean the module took a ``ZoneInfo``, and the whole point of
a date-shaped window is that the timezone has already been applied.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ..date_window import (
    DEFAULT_UPCOMING_DAYS_AHEAD,
    MAX_UPCOMING_DAYS_AHEAD,
    DateWindowError,
    UpcomingWindow,
)
from ..date_window import upcoming_window as _shared_upcoming_window
from .exceptions import TaskValidationError
from .list_dates import list_task_due
from .task_status import TaskStatus

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .list_dates import ListTaskDue
    from .read_model import TaskReadModel

__all__ = [
    "DEFAULT_UPCOMING_DAYS_AHEAD",
    "MAX_UPCOMING_DAYS_AHEAD",
    "OVERDUE_DASHBOARD_DAYS",
    "UpcomingTasks",
    "UpcomingWindow",
    "select_upcoming_tasks",
    "upcoming_task_day",
    "upcoming_window",
]

OVERDUE_DASHBOARD_DAYS: Final = 7
"""How many days an overdue task stays on the dashboard after it became late.

Counted from the day its date passed — the due date, or the due journal's
**last** day — so a task overdue since yesterday has six more. After that it
leaves the dashboard while staying open and overdue on its list. When the
listing's query admits list tasks, it bounds its look back by this number, so
the two cannot disagree.
"""


def upcoming_window(
    today: datetime.date, days_ahead: int = DEFAULT_UPCOMING_DAYS_AHEAD
) -> UpcomingWindow:
    """The window running from ``today`` to ``days_ahead`` days after it.

    A thin translation over :func:`core_shared.models.date_window.upcoming_window`
    — the arithmetic and the bound are shared with the upcoming-dates section, so
    the two windows cannot disagree about which days "this week" means. The
    *error* is not shared: an ``except TaskValidationError`` in the tasks API
    layer would not catch a ``DateWindowError``, so it is converted here rather
    than left to leak a foreign exception out of a task call.

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
    try:
        return _shared_upcoming_window(today, days_ahead)
    except DateWindowError as error:
        raise TaskValidationError(error.field, error.reason) from error


def _due_of(model: TaskReadModel) -> ListTaskDue | None:
    """The task's date and the day it becomes late, or ``None`` when undated.

    One answer for both kinds of task, from the one date rule: a journal-only
    task is always dated by its due journal, and a list task by its due date or
    due journal. A cancelled due journal reads as undated — for a journal-only
    task that is also a lapse, which the selection has already excluded it for.
    """
    return list_task_due(
        due_date=model.task.due_date,
        due_journal=None if model.due_journal is None else model.due_journal.days(),
    )


def upcoming_task_day(model: TaskReadModel, today: datetime.date) -> datetime.date:
    """The day the dashboard places a task on.

    Its date — the due date, or the due journal's first day — except while it
    is **under way**: a task whose date has gone by but which is not yet late,
    because its due journal has started and not ended, is due *today*. An
    overdue task keeps its own date, which is what its overdue row reports.

    One helper for the order and for the row's ``days_away``, so the two cannot
    disagree about where a task sits.

    Args:
        model: A task the selection admits
        today: Today's date in the user's timezone — the window's first day

    Raises:
        ValueError: The task is undated, which the selection never admits.
    """
    due = _due_of(model)
    if due is None:
        raise ValueError(f"Task {model.task.id} is undated and has no day")
    if model.overdue:
        return due.day
    return max(due.day, today)


def _is_shown(model: TaskReadModel, window: UpcomingWindow) -> bool:
    """Whether the dashboard shows this task for this window.

    The same rule for both kinds of task. Not done, not lapsed, not on an
    archived list, and dated; then either **overdue** within the allowance —
    counted from the day it became late, so a long trip's leftover gets its
    full week — or placed on a day inside the window.
    """
    if model.task.status is not TaskStatus.NOT_DONE or model.lapsed:
        return False
    if model.task_list is not None and model.task_list.archived:
        return False
    due = _due_of(model)
    if due is None:
        return False
    today = window.first_day
    if model.overdue:
        return (today - due.overdue_after).days <= OVERDUE_DASHBOARD_DAYS
    return window.contains(max(due.day, today))


def _sort_key(
    model: TaskReadModel, today: datetime.date
) -> tuple[bool, datetime.date, int]:
    """Overdue first, oldest first; then everything else soonest first.

    ``False`` sorts before ``True``, so ``not overdue`` puts the overdue group
    ahead. Within each group the day is :func:`upcoming_task_day` — the task's
    date, or today for one under way — and the task id breaks ties across both
    kinds of task. The tie-break is load-bearing rather than defensive: a
    dashboard week routinely holds several tasks due on one day, and without
    it the same request could answer in a different order between runs.
    """
    return (not model.overdue, upcoming_task_day(model, today), model.task.id or 0)


@dataclass(frozen=True)
class UpcomingTasks:
    """The answer to "what is coming up", carrying the question with it.

    The window travels beside the tasks for the same reason ``JournalTaskGroups``
    carries its ``journal_id``: a surface renders both — "the next seven days"
    is part of what the user is told — and a caller that had to re-derive the
    window from the rows could not describe an **empty** one at all.

    Attributes:
        window: The window these tasks were selected for
        tasks: The survivors, overdue first and oldest first, then by the day
            each is placed on, ties broken by task id
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

    One rule for journal-only and list tasks. Excluded, and composing:

    - **not outstanding** — the task is done or cancelled;
    - **lapsed** — read from the model: its due journal has ended or was
      cancelled;
    - **on an archived list** — archiving hides a list's tasks from the
      dashboard, overdue ones included;
    - **undated** — a list task with no date, or whose due journal is
      cancelled;
    - **outside the window** — placed (see :func:`upcoming_task_day`) on a day
      the window does not hold, or overdue for longer than
      :data:`OVERDUE_DASHBOARD_DAYS`.

    The window's first day is today: the caller built the models' lapse and
    overdue verdicts from the same ``today`` it built the window from.

    The window check duplicates what a caller's query almost certainly filtered
    already. That is deliberate: it makes the boundary day assertable without a
    database, and a query that over-fetches is answered correctly here.

    Args:
        models: The assembled read models, in any order
        window: The window they should be judged against

    Returns:
        The window and its survivors: overdue first, oldest first, then the
        rest by the day each is placed on, ties broken by task id.
    """
    return UpcomingTasks(
        window=window,
        tasks=tuple(
            sorted(
                (model for model in models if _is_shown(model, window)),
                key=lambda model: _sort_key(model, window.first_day),
            )
        ),
    )

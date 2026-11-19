"""The date rules a task on a list follows: its due, overdue, and never lapsing.

A task on a list has a **due date**, a **due journal**, or no date at all
(spec *Core invariants* 4 and 5), and it follows rules of its own:

- **It never lapses** (invariant 7). Past its date it reads as **overdue** and
  stays open on its list until it is done, cancelled or re-dated. A
  journal-only task keeps the lapse rule in :mod:`.lapse`, unchanged.
- **A due journal dates it by the day the journal starts** — the journal's date
  for every task purpose — but it is only overdue once the journal's **last**
  day has ended, so a multi-day trip's packing list is not overdue on day two.
- **While its due journal is cancelled it is undated**: neither dated nor
  overdue. Un-cancelling restores the date, because nothing here is stored.
- **A due date, when set, must be today or later.** Today counts, unlike a due
  journal, which must be strictly in the future.

Like the lapse rule, everything here is **derived on read** and **pure**: it
takes dates already resolved in the acting user's timezone rather than journals
or a timezone, so a caller judging many tasks resolves the timezone once. The
resolution lives in ``app.core.journal.services.journal_date_resolver``:
``today_in`` for today, ``journal_date`` for a journal's first day and
``journal_last_day`` for its last.

:func:`derive_task_date_state` is the single answer to "is this task lapsed or
overdue?" for *any* task, so no reader has to branch on whether a task is on a
list and restate either rule.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exceptions import TaskDueDateInPastError
from .lapse import LapseReason, derive_lapse_reason
from .task_status import TaskStatus

if TYPE_CHECKING:
    from .entities import Task


def _require_day(name: str, value: object) -> None:
    """Refuse anything but a calendar date, ``datetime`` included.

    ``datetime`` subclasses ``date``, so it is refused by name, as
    ``Task._validate_due_date`` does: an instant here means a caller skipped
    converting into the user's timezone, and comparing it with a ``date`` would
    raise anyway — later, and further from the mistake.
    """
    if isinstance(value, datetime.datetime) or not isinstance(value, datetime.date):
        raise TypeError(f"{name} must be a calendar date, got {value!r}")


@dataclass(frozen=True, kw_only=True)
class DueJournalDays:
    """A due journal's days, resolved in the acting user's timezone.

    Attributes:
        first_day: The local date its event date range starts on — the
            journal's date for every task purpose
        last_day: The local date its event date range ends on; equal to
            ``first_day`` for a single-day or point-in-time journal
        cancelled: Whether the journal is a cancelled event
    """

    first_day: datetime.date
    last_day: datetime.date
    cancelled: bool

    def __post_init__(self) -> None:
        """Refuse instants, and a span that ends before it starts."""
        _require_day("first_day", self.first_day)
        _require_day("last_day", self.last_day)
        if self.last_day < self.first_day:
            raise ValueError(
                f"last_day {self.last_day} must not precede first_day {self.first_day}"
            )


@dataclass(frozen=True, kw_only=True)
class ListTaskDue:
    """When a dated list task is due, and the day after which it is overdue.

    Two days rather than one because they differ for a multi-day due journal:
    the task's **date** is the day the journal starts (the week it belongs in,
    what it reads as due on), while it only becomes overdue once the journal is
    **over**. For a due date and a single-day journal they are the same day.

    Attributes:
        day: The task's date
        overdue_after: The day whose end makes the task overdue
    """

    day: datetime.date
    overdue_after: datetime.date


@dataclass(frozen=True, kw_only=True)
class TaskDateState:
    """Whether a task is lapsed or overdue — never both.

    Attributes:
        lapse_reason: Why a journal-only task lapsed; always ``None`` for a
            task on a list
        overdue: Whether a list task is past its date; always ``False`` for a
            journal-only task
    """

    lapse_reason: LapseReason | None
    overdue: bool


def list_task_due(
    *, due_date: datetime.date | None, due_journal: DueJournalDays | None
) -> ListTaskDue | None:
    """When a list task is due, or ``None`` when it is undated.

    A cancelled due journal counts as undated: the task is not dated, not
    overdue, and not surfaced through that journal while it stays cancelled.

    Args:
        due_date: The task's own due date, if any
        due_journal: Its due journal's resolved days, if it has one

    Returns:
        The due, or ``None`` for an undated task or a cancelled due journal.

    Raises:
        ValueError: Both were given — invariant 4 allows one or the other.
    """
    if due_date is not None and due_journal is not None:
        raise ValueError("A task cannot have both a due date and a due journal")
    if due_date is not None:
        _require_day("due_date", due_date)
        return ListTaskDue(day=due_date, overdue_after=due_date)
    if due_journal is None or due_journal.cancelled:
        return None
    return ListTaskDue(day=due_journal.first_day, overdue_after=due_journal.last_day)


def is_list_task_overdue(
    *, status: TaskStatus, due: ListTaskDue | None, today: datetime.date
) -> bool:
    """Whether a list task is overdue: still not done, and its due day has ended.

    Strictly after, mirroring the lapse rule: a task due today is outstanding,
    not overdue. A done or cancelled task is never overdue — the marker lasts
    until the task is done, cancelled or re-dated.

    Args:
        status: The task's current status
        due: Its due, from :func:`list_task_due`; ``None`` when undated
        today: Today's date, in the user's timezone
    """
    return (
        status is TaskStatus.NOT_DONE and due is not None and due.overdue_after < today
    )


def is_due_date_allowed(due_date: datetime.date, today: datetime.date) -> bool:
    """Whether ``due_date`` may be set: today or later, in the user's timezone.

    Raises:
        TypeError: Either argument is not a calendar date.
    """
    _require_day("due_date", due_date)
    _require_day("today", today)
    return due_date >= today


def ensure_due_date_allowed(due_date: datetime.date, today: datetime.date) -> None:
    """Refuse a due date before today, for a service setting one.

    Raises:
        TaskDueDateInPastError: ``due_date`` is before ``today``.
        TypeError: Either argument is not a calendar date.
    """
    if not is_due_date_allowed(due_date, today):
        raise TaskDueDateInPastError(due_date, today)


def derive_task_date_state(
    *, task: Task, due_journal: DueJournalDays | None, today: datetime.date
) -> TaskDateState:
    """Whether any task — journal-only or on a list — is lapsed or overdue.

    A task on a list never lapses and may be overdue; a journal-only task may
    lapse, by the unchanged rule, and is never overdue. A journal-only task
    added to a list therefore stops lapsing from that moment on.

    Args:
        task: The task to judge
        due_journal: Its due journal's resolved days, given exactly when the
            task has a due journal
        today: Today's date, in the user's timezone

    Raises:
        ValueError: ``due_journal`` was given for a task with no due journal,
            or left out for a task with one — a caller's bug, not a refusal.
    """
    if (due_journal is None) != (task.due_journal_id is None):
        raise ValueError(
            f"due_journal must be given exactly when the task has one "
            f"(due_journal_id={task.due_journal_id})"
        )

    if task.task_list_id is not None:
        due = list_task_due(due_date=task.due_date, due_journal=due_journal)
        return TaskDateState(
            lapse_reason=None,
            overdue=is_list_task_overdue(status=task.status, due=due, today=today),
        )

    # A journal-only task always has a due journal (invariant 2), so the check
    # above has already guaranteed its days are here; this narrows the type.
    if due_journal is None:
        raise ValueError("A journal-only task must have a due journal")
    return TaskDateState(
        lapse_reason=derive_lapse_reason(
            status=task.status,
            due_journal_date=due_journal.first_day,
            due_journal_cancelled=due_journal.cancelled,
            today=today,
        ),
        overdue=False,
    )

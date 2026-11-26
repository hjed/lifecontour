"""The task read model: a task with its journals by role, its contacts and its lapse.

This is the shape every read surface hands out — the task detail read, a
journal's task list, and the home dashboard's tasks section — so it is defined
once here rather than three times in three controllers. The specification asks
each of those surfaces to show "the task text, its status, its linked contacts,
and — for lapsed tasks — a clear lapsed marker", which is exactly this.

**Nothing here reads anything.** :func:`build_task_read_model` is pure: it takes
pieces a caller has already fetched and arranges them. That is what lets a list
surface load *N* tasks' journals and contacts in one query per collection and
then call this once per task, rather than discovering an N+1 the first time a
journal has twenty tasks in it.

The two anchors arrive as arguments rather than as ids to look up in a map of
journals, so resolving an id to a journal — with whatever a missing one should
mean — stays with the service that did the fetching.

**Either anchor may be absent.** A task on a list may have no journal at all, or
only one of the two, so both refs are optional. A journal-only task always has
both, and the surfaces that only ever show journal-only tasks (the dashboard,
the daily summary) narrow through :meth:`TaskReadModel.require_journal` rather
than checking for ``None`` themselves.

**Lapsed or overdue is one answer.** Both come from
:func:`~.list_dates.derive_task_date_state`, the single rule for every task: a
list task never lapses and may be overdue — after its due date, or once its due
journal's *last* day has ended — while a journal-only task may lapse and is
never overdue. That is why a journal ref carries its last day as well as its
date.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exceptions import TaskAnchorMissingError
from .list_dates import DueJournalDays, derive_task_date_state

if TYPE_CHECKING:
    import datetime
    from collections.abc import Sequence

    from .entities import Task
    from .exceptions import TaskJournalAnchor
    from .lapse import LapseReason
    from .task_icon import TaskIcon


@dataclass(frozen=True)
class TaskJournalRef:
    """One of a task's journals, as a surface needs to show it.

    Enough to render a link, a title and a date without a second lookup, and
    nothing more: a read surface listing a task's journals is not a journal
    browser.

    Attributes:
        id: The journal's id
        title: Its title, so a link needs no follow-up read
        date: Its date **already resolved in the acting user's timezone**. A
            date rather than an instant, so no surface can re-derive it in the
            browser's zone and disagree with the rule that judged the task.
        last_day: The local date its event range ends on — ``date`` itself for
            a single-day journal. Only the due journal's is read, by the date
            rule — a task is lapsed or overdue only once its due journal's last
            day has ended — and by the dashboard placing a task under way on
            today; surfaces do not put it on the wire.
        cancelled: Whether this is a cancelled event journal. Only meaningful on
            the due journal, where it is a lapse cause, but carried on every ref
            because a surface marks a cancelled journal wherever it shows one.
    """

    id: int
    title: str
    date: datetime.date
    last_day: datetime.date
    cancelled: bool

    def days(self) -> DueJournalDays:
        """This journal's days, as the date rule reads a due journal."""
        return DueJournalDays(
            first_day=self.date, last_day=self.last_day, cancelled=self.cancelled
        )


@dataclass(frozen=True)
class TaskListRef:
    """The list a task is on, as a surface labels and links it.

    Attributes:
        id: The list's id
        name: Its name, so a label needs no follow-up read
        icon: Its icon key, or ``None``
        archived: Whether the list is archived — its tasks are then read-only,
            and a surface marks them so
    """

    id: int
    name: str
    icon: TaskIcon | None
    archived: bool


@dataclass(frozen=True)
class TaskContactRef:
    """One of a task's contacts, as a row shows them.

    A plain reference: task-contact links carry no relationship type, no role
    and no attendance, so neither does this.

    Attributes:
        id: The contact's id
        display_name: The name to show
        photo_url: Their avatar, when they have one
    """

    id: int
    display_name: str
    photo_url: str | None


@dataclass(frozen=True)
class TaskReadModel:
    """A task with everything a read surface needs to render and action it.

    Attributes:
        task: The task entity itself — text, status, both anchor ids, timestamps
        creating_journal: The journal the commitment arose in, or ``None`` for
            a list task that arose in none
        due_journal: The journal it is due in, or ``None`` for a list task with
            no due journal. The same object as ``creating_journal`` when a task
            was created in the journal it is due in, which invariant 6 permits.
        intermediate_journals: The journals it is merely *mentioned* in, oldest
            link first. May include the due journal, when a task was retargeted
            onto a journal it was already attached to.
        contacts: The contacts it references, in link order
        task_list: The list it is on, or ``None`` for a journal-only task
        lapse_reason: Why the task has lapsed, or ``None`` if it has not;
            always ``None`` for a task on a list
        overdue: Whether a task on a list is past its date; always ``False``
            for a journal-only task
    """

    task: Task
    creating_journal: TaskJournalRef | None
    due_journal: TaskJournalRef | None
    intermediate_journals: tuple[TaskJournalRef, ...]
    contacts: tuple[TaskContactRef, ...]
    task_list: TaskListRef | None
    lapse_reason: LapseReason | None
    overdue: bool

    @property
    def lapsed(self) -> bool:
        """Whether the task has lapsed.

        Defined as "there is a reason" rather than computed a second way, so the
        flag and the reason can never disagree about the same task.
        """
        return self.lapse_reason is not None

    def require_journal(self, anchor: TaskJournalAnchor) -> TaskJournalRef:
        """One of the task's anchor journals, which must be present.

        The twin of :meth:`Task.require_anchor`, for a surface that only ever
        shows journal-only tasks: those always have both journals, so a missing
        one there is a broken invariant, not a state to render.

        Args:
            anchor: Which of the two journals to read

        Returns:
            That journal's ref.

        Raises:
            TaskAnchorMissingError: The task has no journal in that role.
        """
        ref = self.creating_journal if anchor == "creating" else self.due_journal
        if ref is None:
            raise TaskAnchorMissingError(self.task.id, anchor)
        return ref


def build_task_read_model(
    *,
    task: Task,
    creating_journal: TaskJournalRef | None,
    due_journal: TaskJournalRef | None,
    intermediate_journals: Sequence[TaskJournalRef],
    contacts: Sequence[TaskContactRef],
    task_list: TaskListRef | None,
    today: datetime.date,
) -> TaskReadModel:
    """Assemble one task's read model from pieces already fetched.

    Args:
        task: The task entity
        creating_journal: Its creating anchor, or ``None`` when it has none
        due_journal: Its due anchor — the only journal the date rule
            consults — or ``None`` when it has none
        intermediate_journals: Its mentions, in the order they should be shown
        contacts: Its contacts, in the order they should be shown
        task_list: The list it is on, given exactly when the task is on one
        today: Today's date in the acting user's timezone

    Returns:
        The read model, with ``lapse_reason`` and ``overdue`` derived rather
        than supplied.

    Raises:
        ValueError: ``task_list`` does not name the task's own list (or is
            missing for a task on one, or given for a task on none) — a
            caller's bug, as a mismatched due journal is to the date rule.
    """
    if (None if task_list is None else task_list.id) != task.task_list_id:
        raise ValueError(
            f"task_list must be the task's own list (task_list_id={task.task_list_id})"
        )
    # Only the due journal decides lapse and overdue. The creating journal is
    # almost always in the past — that is what "the journal the commitment
    # arose in" means — so consulting it would lapse nearly every task the day
    # after it was written.
    date_state = derive_task_date_state(
        task=task,
        due_journal=None if due_journal is None else due_journal.days(),
        today=today,
    )
    return TaskReadModel(
        task=task,
        creating_journal=creating_journal,
        due_journal=due_journal,
        intermediate_journals=tuple(intermediate_journals),
        contacts=tuple(contacts),
        task_list=task_list,
        lapse_reason=date_state.lapse_reason,
        overdue=date_state.overdue,
    )

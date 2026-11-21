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
than checking for ``None`` themselves. Whether the task has lapsed is decided by
:func:`~.lapse.task_lapse_reason`, which never lapses a list task.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exceptions import TaskAnchorMissingError
from .lapse import task_lapse_reason

if TYPE_CHECKING:
    import datetime
    from collections.abc import Sequence

    from .entities import Task
    from .exceptions import TaskJournalAnchor
    from .lapse import LapseReason


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
        cancelled: Whether this is a cancelled event journal. Only meaningful on
            the due journal, where it is a lapse cause, but carried on every ref
            because a surface marks a cancelled journal wherever it shows one.
    """

    id: int
    title: str
    date: datetime.date
    cancelled: bool


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
        lapse_reason: Why the task has lapsed, or ``None`` if it has not
    """

    task: Task
    creating_journal: TaskJournalRef | None
    due_journal: TaskJournalRef | None
    intermediate_journals: tuple[TaskJournalRef, ...]
    contacts: tuple[TaskContactRef, ...]
    lapse_reason: LapseReason | None

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
    today: datetime.date,
) -> TaskReadModel:
    """Assemble one task's read model from pieces already fetched.

    Args:
        task: The task entity
        creating_journal: Its creating anchor, or ``None`` when it has none
        due_journal: Its due anchor — the only journal the lapse rule
            consults — or ``None`` when it has none
        intermediate_journals: Its mentions, in the order they should be shown
        contacts: Its contacts, in the order they should be shown
        today: Today's date in the acting user's timezone

    Returns:
        The read model, with ``lapse_reason`` derived rather than supplied.
    """
    return TaskReadModel(
        task=task,
        creating_journal=creating_journal,
        due_journal=due_journal,
        intermediate_journals=tuple(intermediate_journals),
        contacts=tuple(contacts),
        # Only the due journal decides this. The creating journal is almost
        # always in the past — that is what "the journal the commitment arose
        # in" means — so consulting it would lapse nearly every task the day
        # after it was written.
        lapse_reason=task_lapse_reason(task=task, due_journal=due_journal, today=today),
    )

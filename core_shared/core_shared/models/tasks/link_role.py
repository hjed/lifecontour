"""The role a link holds between a task and a journal, and the grouping over it.

A journal's detail view shows "the tasks it is linked to, grouped by the nature
of the link" — due here, created here, mentioned here. This is that rule, and it
is **pure**: every fact it needs is already on the read model, so it takes
assembled models and a journal id and reads nothing.

**A role is derived, never stored.** There is no role column and no fourth link
table. A task is *due* in a journal when that journal is its due anchor,
*created* there when it is its creating anchor, and *mentioned* there when the
journal is one of its intermediate links — all three of which the read model
already carries. Storing the role would be a second copy of the anchors that
could disagree with them.

**A task can hold two roles at once, and both are reported.** Invariant 6 lets
one journal be a task's creating *and* due anchor, and retargeting onto a journal
the task already mentioned leaves the intermediate row in place beside the new
due anchor. A grouping that assigned each task a single role would silently drop
a link the specification's three-group display exists to show.

**The ordering is a promise, and a total one.** Phase 10 recorded that
``created_at`` defaults to ``transaction_timestamp()``, so links written in one
request tie and "oldest first" is only a partial order. Groups here are ordered
by the due journal's **date**, then by task id — soonest first, with a tie-break
that cannot itself tie. In the *due* group every task shares the journal and
therefore its date, so that group is ordered by id alone; that is not a
degenerate case but the whole of its order, which is why the tie-break is
load-bearing rather than defensive.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime
    from collections.abc import Iterable, Sequence

    from .read_model import TaskReadModel


class TaskLinkRole(StrEnum):
    """How a task is linked to the journal being viewed.

    The three values are the specification's own words for the three groups, and
    both read surfaces put them on the wire, so renaming one is a breaking change
    to two APIs rather than a refactor.

    Values:
        DUE: The journal is the task's due anchor — it is due *here*
        CREATED: The journal is the task's creating anchor — it arose *here*
        MENTIONED: The journal is one of the task's intermediate links — the
            task was discussed, revisited or previously due here
    """

    DUE = "due"
    CREATED = "created"
    MENTIONED = "mentioned"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


@dataclass(frozen=True)
class JournalTaskGroups:
    """One journal's tasks, split by the role each link holds.

    The three groups are always present, empty included: a journal with no tasks
    and a listing narrowed to one role are both ordinary answers, and a surface
    that had to tell "no tasks" from "no group" would need two code paths for
    one question.

    Attributes:
        journal_id: The journal these groups are about
        due: Tasks due in this journal
        created: Tasks created in this journal
        mentioned: Tasks that merely mention it
    """

    journal_id: int
    due: tuple[TaskReadModel, ...]
    created: tuple[TaskReadModel, ...]
    mentioned: tuple[TaskReadModel, ...]

    def for_role(self, role: TaskLinkRole) -> tuple[TaskReadModel, ...]:
        """The group for one role.

        Args:
            role: The role to read

        Returns:
            That group, in its promised order.
        """
        if role is TaskLinkRole.DUE:
            return self.due
        if role is TaskLinkRole.CREATED:
            return self.created
        return self.mentioned

    @property
    def tasks(self) -> tuple[TaskReadModel, ...]:
        """Every task here **once**, in the same order the groups use.

        What a JSON:API ``data`` member needs: the specification forbids one
        resource appearing twice in it, and a task holding two of this journal's
        roles would otherwise do exactly that. The roles are then carried on each
        resource, with the grouping itself alongside in ``meta``.
        """
        seen: dict[int, TaskReadModel] = {}
        for model in (*self.due, *self.created, *self.mentioned):
            task_id = model.task.id
            if task_id is not None and task_id not in seen:
                seen[task_id] = model
        return tuple(_ordered(seen.values()))

    def roles_for(self, task_id: int) -> tuple[TaskLinkRole, ...]:
        """The roles one task holds **among these groups**, in a fixed order.

        Fixed so a response never reshuffles the same task's roles between
        requests — the order is the enum's, which is the order the groups are
        displayed in.

        **Read from the groups, so a filtered answer reports only the filtered
        role.** A task that is both due and created in the journal reports both
        normally, and only ``due`` when the caller asked for ``due``. That is
        deliberate: these groups *are* the answer, so roles read from them can
        never contradict them, and no client can be told a task belongs to a
        group this same response reports as empty. The unfiltered call is what
        answers "every role this task holds here", and it is the call a
        journal's detail view makes.

        Args:
            task_id: The task to ask about

        Returns:
            Its roles among these groups, or an empty tuple for a task not in
            them.
        """
        return tuple(
            role
            for role in TaskLinkRole
            if any(model.task.id == task_id for model in self.for_role(role))
        )


def _sort_key(model: TaskReadModel) -> tuple[datetime.date, int]:
    """Soonest deadline first, ties broken by task id.

    The id is not a tie-break of last resort here: every task in the *due* group
    shares the journal's own date, so it is the only thing separating them.
    """
    return (model.due_journal.date, model.task.id or 0)


def _ordered(models: Iterable[TaskReadModel]) -> list[TaskReadModel]:
    """The models in the order every group and the unique list promise."""
    return sorted(models, key=_sort_key)


def _holds_role(model: TaskReadModel, journal_id: int, role: TaskLinkRole) -> bool:
    """Whether this task is linked to the journal in this role."""
    if role is TaskLinkRole.DUE:
        return model.task.due_journal_id == journal_id
    if role is TaskLinkRole.CREATED:
        return model.task.creating_journal_id == journal_id
    return any(ref.id == journal_id for ref in model.intermediate_journals)


def group_tasks_by_link_role(
    journal_id: int,
    models: Sequence[TaskReadModel],
    *,
    role: TaskLinkRole | None = None,
) -> JournalTaskGroups:
    """Split a journal's tasks into the three groups a detail view shows.

    Pure: the models arrive already assembled, and nothing here reads, re-derives
    or rebuilds one. The same object handed in is handed back, so the lapse
    verdict and the contacts the assembler decided cannot be contradicted here.

    A task linked to the journal in no role at all is in none of the groups.
    That is unreachable through the repository, whose query returns only linked
    tasks, and is defined rather than left to chance because the function is
    pure and a caller may assemble models some other way.

    Args:
        journal_id: The journal being viewed
        models: Its tasks' read models, in any order
        role: Narrow the answer to one role. The other two groups come back
            **empty rather than absent**, so a client parses one shape whether
            or not it asked for a filter. Filtering happens here rather than in
            SQL because a role is derived from anchors and mentions the read
            model already carries; pushing it into the query would be a second
            definition of "mentioned here" that could drift from this one.

    Returns:
        The three groups, each in the order described in the module docstring.
    """

    def group(wanted: TaskLinkRole) -> tuple[TaskReadModel, ...]:
        if role is not None and role is not wanted:
            return ()
        return tuple(
            _ordered(
                model for model in models if _holds_role(model, journal_id, wanted)
            )
        )

    return JournalTaskGroups(
        journal_id=journal_id,
        due=group(TaskLinkRole.DUE),
        created=group(TaskLinkRole.CREATED),
        mentioned=group(TaskLinkRole.MENTIONED),
    )

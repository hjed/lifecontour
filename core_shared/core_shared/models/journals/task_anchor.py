"""What blocks a journal deletion, and where the user can go to clear it.

A task is anchored to exactly two journals — the *creating* journal where the
commitment arose and the *due* journal where it matters — and the specification
blocks deleting either of them. The refusal has to be **explanatory rather than
opaque**: it names each blocking task and links to a journal where that task can
be actioned. Tasks have no route of their own, so that link always targets a
journal detail view.

This module owns both halves of that rule as pure functions over one task's
anchors, so the choice can be tested without a database and the SQL adapter is
left with nothing but the query.

**Why this lives in the journal domain rather than the tasks domain.** It is the
vocabulary of a *journal* invariant — the payload of a journal-domain error
raised by a journal-domain service — and the tasks table is only where the
evidence happens to be stored. Keeping it here also keeps the dependency
one-way: ``core_shared.models.tasks`` never imports ``core_shared.models.journals``,
so the task read models still to come cannot close the loop into an import
cycle between two eagerly re-exporting packages.
"""

from dataclasses import dataclass
from typing import Any, Literal

from core_shared.models.tasks import TaskStatus

# Which anchor role makes a task block a journal's deletion. This is the two
# *anchor* roles only: an intermediate link never blocks, because deleting a
# journal a task merely mentions removes the link and leaves the task intact.
TaskAnchorRole = Literal["creating", "due"]


@dataclass(frozen=True)
class BlockingTask:
    """One task standing in the way of a journal deletion.

    Everything needed to explain the failure travels with it — the task's own
    text, so the user recognises the commitment; the roles it blocks in, so the
    reason is legible; and the id *and* title of the journal to open, so a
    caller can build a link without a second lookup.
    """

    task_id: int
    text: str
    status: TaskStatus
    # Sorted "creating" before "due", so a task anchored twice to the same
    # journal reads the same way every time.
    blocking_roles: tuple[TaskAnchorRole, ...]
    action_journal_id: int
    action_journal_title: str


def blocking_roles(
    *,
    deleted_journal_id: int,
    creating_journal_id: int,
    due_journal_id: int,
) -> tuple[TaskAnchorRole, ...]:
    """The anchor roles that tie this task to the journal being deleted.

    Empty when the task is not anchored to it at all — a task that only
    *mentions* the journal blocks nothing.
    """
    roles: list[TaskAnchorRole] = []
    if creating_journal_id == deleted_journal_id:
        roles.append("creating")
    if due_journal_id == deleted_journal_id:
        roles.append("due")
    return tuple(roles)


def action_anchor_for(
    *, deleted_journal_id: int, due_journal_id: int
) -> TaskAnchorRole:
    """Which of the task's two anchors surfaces it once this journal is gone.

    Normally the due journal: it is where the task is heading, and where the
    user most usefully cancels, completes or retargets it. When the due journal
    is the one being deleted, the creating journal is the remaining anchor.

    When *both* anchors are the journal being deleted — which the specification
    permits — this resolves to the creating journal, which is that same journal.
    That is the right answer rather than a degenerate one: the deletion was
    refused, so the journal is still there to be opened.
    """
    return "creating" if due_journal_id == deleted_journal_id else "due"


def blocking_task_from_anchors(
    *,
    deleted_journal_id: int,
    task_id: int,
    text: str,
    status: TaskStatus,
    creating_journal_id: int,
    creating_journal_title: str,
    due_journal_id: int,
    due_journal_title: str,
) -> BlockingTask | None:
    """Assemble one row of the blocking-task query, or ``None`` if it does not block.

    The status is carried and never consulted: a done task's link to the journal
    it was created in is part of the record, so the deletion is refused whatever
    the task's status.
    """
    roles = blocking_roles(
        deleted_journal_id=deleted_journal_id,
        creating_journal_id=creating_journal_id,
        due_journal_id=due_journal_id,
    )
    if not roles:
        return None

    action_anchor = action_anchor_for(
        deleted_journal_id=deleted_journal_id, due_journal_id=due_journal_id
    )
    action_journal_id, action_journal_title = (
        (creating_journal_id, creating_journal_title)
        if action_anchor == "creating"
        else (due_journal_id, due_journal_title)
    )

    return BlockingTask(
        task_id=task_id,
        text=text,
        status=status,
        blocking_roles=roles,
        action_journal_id=action_journal_id,
        action_journal_title=action_journal_title,
    )


def blocking_task_payload(task: BlockingTask) -> dict[str, Any]:
    """One blocker's wire shape, for a caller that needs more than the prose.

    The specification asks that the refusal reach the API **and** MCP naming
    "the blocking tasks and the journals that surface them, so an agent can
    resolve them without going through the UI". Prose alone cannot do that: an
    agent would have to parse English to find an id. So the same blockers travel
    as data alongside the message — and from **one** builder, because two
    surfaces describing the same failure differently is the failure mode worth
    designing out rather than testing for repeatedly.

    Everything here is a plain JSON type. The MCP surface hands its payload to
    ``json.dumps`` and the REST surface to ``JSONResponse``, neither of which
    has a rule for an enum or a tuple, so the conversion belongs here rather
    than being half-done and finished twice.
    """
    return {
        "task_id": task.task_id,
        "text": task.text,
        # ``.value`` rather than the member: ``TaskStatus`` is a ``StrEnum``, so
        # an encoder would accept it, but a caller reading the dict directly
        # should get a plain ``str`` rather than something that compares equal
        # to one.
        "status": task.status.value,
        "blocking_roles": list(task.blocking_roles),
        # Id *and* title, so the caller can render the link and follow it
        # without a second lookup.
        "action_journal_id": task.action_journal_id,
        "action_journal_title": task.action_journal_title,
    }


def describe_roles(roles: tuple[TaskAnchorRole, ...]) -> str:
    """Say, in prose, why a task blocks — for the error message.

    Every case is named rather than falling through to a default: a
    :class:`BlockingTask` cannot be built with no roles, and prose that quietly
    called an unroled task "due in this journal" would put a wrong reason in
    front of the user rather than failing where the mistake is.
    """
    if roles == ("creating", "due"):
        return "created in and due in this journal"
    if roles == ("creating",):
        return "created in this journal"
    if roles == ("due",):
        return "due in this journal"
    raise ValueError(f"A blocking task must block in at least one role, got {roles!r}")

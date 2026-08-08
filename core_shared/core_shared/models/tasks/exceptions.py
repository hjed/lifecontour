"""Exceptions for the tasks domain."""

from datetime import date
from typing import Literal

from core_shared.exceptions import DomainError

from .task_status import TaskStatus

# Which of a task's two journal anchors an error is about. A task is anchored to
# exactly two journals and the roles behave differently — the creating anchor is
# immutable, the due anchor is retargetable — so an error that names one has to
# say which. The wider *link role* vocabulary the read model needs (due, created,
# mentioned) belongs to the phase that ships that read, not here.
TaskJournalAnchor = Literal["creating", "due"]


class TaskDomainError(DomainError):
    """Base exception for task domain errors."""

    pass


class TaskValidationError(TaskDomainError):
    """Exception raised when task validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        # Store field separately for programmatic access (e.g. in error handlers)
        self.field = field


class TaskNotFoundError(TaskDomainError):
    """Exception raised when a task is not found.

    Every repository read and write is scoped to the acting user, so a task
    belonging to somebody else is indistinguishable from one that never
    existed — which is the point. The message deliberately says nothing about
    ownership.
    """

    def __init__(self, task_id: int):
        super().__init__(f"Task with ID {task_id} not found", 404)
        self.task_id = task_id


class TaskStatusTransitionError(TaskDomainError):
    """Exception raised when a status change is refused by the lifecycle rules.

    Only two transitions are refused, and they are the two that would leave
    *cancelled*. The specification gives a cancelled task exactly one way back:
    retargeting it onto a new future journal, which revalidates the future-dated
    rule and returns the task to *not done*. So the message does not merely
    refuse — it names the operation that does what the caller was asking for,
    which is what an AI client needs to recover without guessing.

    **409 rather than 400.** The request is well formed and the status it names
    is a real one; what it conflicts with is the state the task is in, which is
    exactly what Conflict means. A caller that re-sends it unchanged after
    retargeting will succeed.
    """

    def __init__(self, current_status: TaskStatus, target_status: TaskStatus):
        super().__init__(
            f"A task that is {current_status} cannot be moved to {target_status}. "
            f"Retarget it onto a new future journal to reopen it as not done.",
            409,
        )
        self.current_status = current_status
        self.target_status = target_status


class TaskReopenNotAcknowledgedError(TaskDomainError):
    """Exception raised when a *done* task would be reopened without being asked for.

    Retargeting always leaves a task **not done**, so moving the due journal of a
    completed task reopens it. The specification says the product must say so
    before that happens, because moving a date is rarely how a user means to undo
    a completion — an extension of a deadline they had forgotten was already met.
    The acknowledgement is the caller's way of saying the reopening is intended.

    **A cancelled task carries no such gate.** Retargeting is the documented — and
    only — way out of cancelled, and it is what ``TaskStatusTransitionError``
    tells a caller to do, so asking them to confirm it would be asking them to
    confirm the remedy they were just sent to.

    **409 rather than 400**, and its own type rather than a validation error. The
    request is well formed and the journal it names is a real, future, owned one;
    what it conflicts with is the state the task is in. A surface that can tell
    this apart from a validation failure can offer *"reopen it anyway"*; one that
    cannot has only *"invalid"* to show, which is not a choice the user can act
    on. It is deliberately **not** a ``TaskStatusTransitionError``, whose message
    tells a caller to retarget and would be circular here.
    """

    def __init__(self, task_id: int):
        super().__init__(
            f"Task {task_id} is done. Retargeting it onto a new due journal would "
            f"reopen it as not done. Acknowledge the reopen and re-send the "
            f"request if that is what you intend.",
            409,
        )
        self.task_id = task_id


class TaskAnchorJournalNotFoundError(TaskDomainError):
    """Exception raised when one of a task's journal anchors is unreachable.

    Covers both halves of the same rule: a task must be anchored to two journals
    that **exist** and that **belong to the acting user**. The two are
    deliberately one error, because the anchors are resolved by a single
    owner-scoped read.

    **The guarantee is indistinguishability, not silence.** The message states
    the constraint — a journal must exist *and* be yours — because a user who
    picked a journal they cannot use needs to know why. What it never reveals is
    *which* half failed: a journal belonging to somebody else and a journal that
    never existed produce a byte-identical message for the same id, so the error
    cannot be used to probe for another user's journals.
    """

    def __init__(self, anchor: TaskJournalAnchor, journal_id: int):
        super().__init__(
            f"The {anchor} journal (ID {journal_id}) was not found. A task must be "
            f"anchored to journals that exist and belong to you.",
            404,
        )
        self.anchor = anchor
        self.journal_id = journal_id


class TaskJournalIsAnchorError(TaskDomainError):
    """Exception raised when an anchor journal is treated as an intermediate link.

    A task's journals come in three roles and only one of them is a row in
    ``task_intermediate_journals``. The creating and due journals are **columns
    on the task**, so the intermediate-link surface can neither add them nor
    remove them, and both attempts are this one error:

    - **attaching** a journal that is already an anchor is refused because it is
      already linked, in a role an intermediate link cannot express — the
      specification's *"already linked in a stronger role"*;
    - **detaching** an anchor role is refused **when there is no link row to
      remove**. The repository would answer a bare ``False`` there, which a
      caller would read as *"it was not attached"* rather than *"that link
      cannot be removed at all"*. The condition matters: a journal can hold an
      anchor role *and* an intermediate link at once — retargeting a task onto a
      journal it already mentioned produces exactly that — and refusing there
      would make a link the user created permanently unremovable.

    One error rather than two, because the *remedy* is the same in both
    directions: whatever the caller wanted, an anchor role is not something this
    surface can add or remove. What they cannot know is **which anchor** it was
    and how that anchor is really changed, so the message carries both. The
    creating journal never changes, and the due journal is changed by
    *retargeting* the task — naming the operation is what lets an agent recover
    without guessing.

    **The two directions are not, however, the same condition**, and an earlier
    draft of this docstring said they were. Attaching is refused on the anchor
    role alone. Detaching is refused only when there is *also* no link row, so a
    journal holding both roles can be detached — see
    :meth:`~app.core.tasks.services.task_service.TaskService.detach_intermediate_journal`
    for why. One consequence is worth stating because nothing else would tell a
    reader: that both-roles state can be **destroyed through this surface but not
    recreated**, since re-attaching hits the attach rule. It is reachable only by
    attaching a journal and then retargeting onto it, and it is redundant by
    construction — the anchor already says more than the link does — so nothing
    is lost, but the asymmetry is deliberate rather than an oversight.

    **409 rather than 400**, for the reason ``TaskStatusTransitionError`` is one:
    the request is well formed and the journal it names is a real journal of the
    caller's. What it conflicts with is the role that journal already holds on
    this task.
    """

    def __init__(self, task_id: int, journal_id: int, anchor: TaskJournalAnchor):
        remedy = (
            "The creating journal is set when the task is created and never changes."
            if anchor == "creating"
            else "The due journal is changed by retargeting the task."
        )
        super().__init__(
            f"Journal {journal_id} is the {anchor} journal of task {task_id}, not "
            f"an intermediate one. {remedy}",
            409,
        )
        self.task_id = task_id
        self.journal_id = journal_id
        self.anchor = anchor


class TaskDueJournalNotFutureError(TaskDomainError):
    """Exception raised when a due journal is not dated in the future.

    Checked at the moment the due journal is **set** — on creation or on
    retargeting — and never again. A task whose due journal has since moved into
    the past is *lapsed*, not invalid, so this error can only ever come from a
    write.

    A journal's date is the date its event date range **starts**, read in the
    user's timezone, so a multi-day journal already under way is past however
    much of it remains. Both dates travel with the error because "not in the
    future" is only actionable when the user can see which day was chosen and
    which day the product thinks it is.
    """

    def __init__(self, journal_id: int, journal_date: date, today: date):
        super().__init__(
            f"The due journal (ID {journal_id}) is dated {journal_date}, which is not "
            f"after today ({today}) in your timezone. A task's due journal must be a "
            f"journal dated in the future.",
            400,
        )
        self.journal_id = journal_id
        self.journal_date = journal_date
        self.today = today

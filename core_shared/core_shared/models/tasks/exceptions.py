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

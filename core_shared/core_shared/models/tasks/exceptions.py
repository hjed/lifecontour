"""Exceptions for the tasks domain."""

from datetime import date
from typing import Literal

from core_shared.exceptions import DomainError

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


class TaskAnchorJournalNotFoundError(TaskDomainError):
    """Exception raised when one of a task's journal anchors is unreachable.

    Covers both halves of the same rule: a task must be anchored to two journals
    that **exist** and that **belong to the acting user**. The two are
    deliberately one error, because the anchors are resolved by a single
    owner-scoped read — a journal belonging to somebody else is indistinguishable
    from one that never existed, and the message says nothing about ownership so
    it cannot be used to probe for another user's journals.
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

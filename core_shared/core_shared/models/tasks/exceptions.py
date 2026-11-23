"""Exceptions for the tasks domain."""

from datetime import date
from typing import Any, Literal

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

    def error_meta(self) -> dict[str, Any]:
        """The field as data, so a surface need not read it out of the prose.

        The name is in the message as well — every refusal here reads
        ``"{field}: ..."`` — but a form deciding which input to mark from an
        English prefix breaks silently the first time the wording changes. This
        puts the same name on both surfaces at once: REST renders it as the
        JSON:API error object's ``meta`` and MCP as the failure payload's
        context, so a create form and an agent correcting the same refusal are
        told which field in the same way.

        Added *beside* the message rather than instead of it, so every caller
        that reads only the prose sees exactly what it saw before.
        """
        return {"field": self.field}


class TaskListValidationError(TaskValidationError):
    """Exception raised when task list validation fails.

    A subclass of :class:`TaskValidationError` because lists are part of the
    tasks domain: a list refusal reaches REST and MCP exactly as a task refusal
    does — a 400 with the field as data. MCP matches by ``isinstance``; the
    REST code map matches by exact type, so it lists this class beside its
    parent.
    """


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


class TaskListNotFoundError(TaskDomainError):
    """Exception raised when a task list is not found.

    Like :class:`TaskNotFoundError`, every list read and write is scoped to the
    acting user, so another user's list is reported exactly as a missing one
    and the message says nothing about ownership.
    """

    def __init__(self, task_list_id: int):
        super().__init__(f"Task list with ID {task_list_id} not found", 404)
        self.task_list_id = task_list_id


class TaskListArchivedError(TaskDomainError):
    """Exception raised when an archived task list is written to.

    An archived list is read-only until it is unarchived. It exists and it is
    the caller's, so this is neither a 404 nor a 400 but a 409: the request is
    well formed, and what it conflicts with is the list's archived state. The
    message names the way out, so an agent unarchives rather than retries.
    """

    def __init__(self, task_list_id: int):
        super().__init__(
            f"Task list with ID {task_list_id} is archived and read-only; "
            "unarchive it to change it",
            409,
        )
        self.task_list_id = task_list_id


class TaskListChangedConcurrentlyError(TaskDomainError):
    """A list membership write found the list changed while it waited.

    A reorder names a task and the neighbour it should follow, but a plain edit
    — closing a task, say — locks only that task and never its list. So between
    the request and the moment the write holds the list's lock, either task can
    be closed, or move to another list. The write then refuses rather than
    guessing where the task should go.

    **409, like** :class:`TaskStatusTransitionError`: the request was well
    formed and conflicts with the list's current state. Re-reading the list and
    retrying against what it now holds succeeds.
    """

    def __init__(self, task_id: int):
        super().__init__(
            f"Task {task_id} is no longer an open task on this list. "
            "Read the list again and retry.",
            409,
        )
        self.task_id = task_id


class TaskStatusTransitionError(TaskDomainError):
    """Exception raised when a status change is refused by the lifecycle rules.

    Only two transitions are refused, they are the two that would leave
    *cancelled*, and only a **journal-only** task is refused them — a task on a
    list is reopened directly by a status change, so it never raises this. The
    specification gives a cancelled journal-only task exactly one way back:
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

    **A cancelled task carries no such gate.** Retargeting is the documented — and,
    for a journal-only task, the only — way out of cancelled, and it is what
    ``TaskStatusTransitionError`` tells a caller to do, so asking them to confirm
    it would be asking them to confirm the remedy they were just sent to.

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


class TaskListTaskClosedError(TaskDomainError):
    """Exception raised when a closed task on a list is retargeted.

    Retargeting applies the journal-only rules: it leaves a task *not done*, so
    a done task needs the reopen acknowledgement and a cancelled one is revived.
    A task on a list follows other rules — changing its date is a plain edit
    that never changes its status — and the operation that will apply them is a
    due-journal change of a list task's own, which does not exist yet. Until it
    does, a done or cancelled list task is refused here rather than reopened by
    a date move.
    A not-done one is retargeted as before: the date moves, the old journal is
    kept as a mention and the status is untouched, which already obeys the list
    rules.

    **Temporary.** The list-task due-journal change keeps a closed list task
    closed when its date moves; when it lands, this error and its REST code go.

    **409 rather than 400**, as :class:`TaskReopenNotAcknowledgedError` is: the
    request is well formed and what it conflicts with is the task's state.
    """

    def __init__(self, task_id: int, status: TaskStatus):
        # A done task can be set back to not done today; a cancelled one cannot
        # be reopened at all yet, so only the first is told how.
        way_out = (
            "Set it back to not done first, then change its due journal."
            if status is TaskStatus.DONE
            else "A cancelled task on a list cannot have its date changed yet."
        )
        super().__init__(
            f"Task {task_id} is on a list and {status}, so its due journal cannot "
            f"be changed while it is closed: changing a list task's date never "
            f"reopens it. {way_out}",
            409,
        )
        self.task_id = task_id
        self.status = status


class TaskListTaskNotDueInJournalError(TaskDomainError):
    """Exception raised when a task on a list with no due journal is retargeted.

    Retargeting moves a task from the journal it is due in to another one, and
    keeps the one it left as a mention. A list task that is undated, or due on
    a date, has no due journal to leave; giving it one is a due-journal change
    of a list task's own, which does not exist yet. It is refused here rather
    than failing on the anchor it lacks.

    That includes the race: a journal delete that commits while a retarget
    waits on the journal's lock detaches the task, so the retarget's locked
    read finds it undated and gets this refusal.

    **Temporary**, alongside :class:`TaskListTaskClosedError`: when a list
    task's due journal can be set, this error and its REST code go.

    **409**: the request is well formed, and what it conflicts with is the
    task's state.
    """

    def __init__(self, task_id: int):
        super().__init__(
            f"Task {task_id} is on a list and not due in a journal, so there is "
            f"no due journal to retarget it from. A task on a list cannot be "
            f"given a due journal yet.",
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

    def error_meta(self) -> dict[str, Any]:
        """Which anchor was refused, so a form need not read it from the prose.

        A surface letting the user pick both journals — the New dialog's
        creating-journal search beside its due-journal picker — has two fields
        the refusal could belong to. The role is the same whether the journal
        is absent or somebody else's, so carrying it keeps the guarantee above;
        the id is deliberately left out of it for the same reason.
        """
        return {"anchor": self.anchor}


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


class TaskDueDateInPastError(TaskDomainError):
    """Exception raised when a list task's due date is before today.

    The due-date counterpart of :class:`TaskDueJournalNotFutureError`, with one
    deliberate difference: **today is allowed**. A due date names a day of its
    own, and "do it today" is the commonest date there is; a due journal must be
    strictly future because a journal earlier today has already begun.

    Like the journal rule it is checked only when the date is **set**. A task
    whose due date has since passed is *overdue*, not invalid. Both dates travel
    with the error so the refusal is actionable: the day chosen and the day the
    product thinks it is, in the user's timezone.
    """

    def __init__(self, due_date: date, today: date):
        super().__init__(
            f"The due date {due_date} is before today ({today}) in your timezone. "
            f"A task's due date must be today or later.",
            400,
        )
        self.due_date = due_date
        self.today = today


class TaskAnchorMissingError(RuntimeError):
    """A task reached code that needs a journal anchor it does not have.

    Deliberately **not** a :class:`TaskDomainError`. Since a task may live on a
    list, both anchors are optional on the entity, but some existing contracts
    (retargeting, and the journal create's own check of the row it saved) still
    expect an ``int``. They narrow through :meth:`Task.require_anchor`, and the journal-only read
    surfaces (the dashboard row, the daily summary) narrow a read model through
    :meth:`TaskReadModel.require_journal`. Reaching this error from either means
    a list task got somewhere no list task can yet go — a broken invariant, not
    a request a client could correct — so it surfaces as the ordinary 500 rather
    than as a refusal with its own code. Each of those call sites is replaced by
    the phase that teaches it about list tasks.

    A ``RuntimeError`` rather than an ``assert``: asserts vanish under ``-O``.
    """

    def __init__(self, task_id: int | None, anchor: TaskJournalAnchor):
        super().__init__(f"Task {task_id} has no {anchor} journal")
        self.task_id = task_id
        self.anchor = anchor

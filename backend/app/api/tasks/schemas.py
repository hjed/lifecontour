"""JSON:API schemas for the tasks domain.

Two shapes of the create request are load-bearing rather than incidental.

**Unknown fields are rejected at every level of the request.**
``TaskService.create_task`` takes a ``now`` parameter that exists so a test can
stand either side of a local midnight; a request able to set it would make the
future-dated invariant opt-out for every client. Absence alone does not enforce
that — a model that ignored unknown keys would start honouring ``now`` the moment
somebody wired the attributes through with ``**model_dump()`` — so
``extra="forbid"`` makes the omission a contract. It is set on all three models
(the envelope, the data member and the attributes) rather than only the
innermost, because a guard with a gap is the same as no guard to whoever finds
the gap: review caught ``now`` beside ``data`` being silently dropped while the
same key inside ``attributes`` was refused.

**There is no date field.** A task is due *in a journal*, not on a day, so the
only way to say when is to name a journal that already exists. Offering a date
would invite the surface to create one implicitly, which the tasks model does
not do. For the same reason the creating journal is absent here: it comes from
the request path, so a client cannot anchor a task to a journal it did not come
from.

**A contact link is a resource identifier and nothing else.** Its request model
carries a type and an id, with no attributes at all, because the specification
gives task-contact links no relationship type, no role and no attendance
status. Those are refused rather than ignored, on the same reasoning as ``now``:
a field silently dropped is a field a client believes was stored.
"""

from datetime import date as date_type
from datetime import datetime
from typing import Any, Literal

from core_shared.models.tasks import (
    JournalTaskGroups,
    LapseReason,
    Task,
    TaskContactRef,
    TaskJournalRef,
    TaskLinkRole,
    TaskReadModel,
    TaskStatus,
    UpcomingTasks,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from app.api.common.identifiers import INT32_MAX, DatabaseId
from app.api.common.schemas import (
    JsonApiCreateRequest,
    JsonApiLinks,
    JsonApiResponse,
    JsonApiUpdateRequest,
)

RESOURCE_TYPE_DESC = "Resource type"
TASK_RESOURCE_TYPE: Literal["tasks"] = "tasks"
CONTACT_RESOURCE_TYPE: Literal["contacts"] = "contacts"
# An operation rather than a resource, named the way ``journal-merge`` is: the
# retarget body is an instruction with its own preconditions, not a task's
# attributes.
TASK_RETARGET_RESOURCE_TYPE: Literal["task-retarget"] = "task-retarget"
JOURNAL_RESOURCE_TYPE: Literal["journals"] = "journals"


class TaskAttributes(BaseModel):
    """Attributes of a task resource."""

    text: str = Field(..., description="The commitment, as plain text")
    status: TaskStatus = Field(..., description="Not done, done, or cancelled")
    creating_journal_id: int = Field(
        ..., description="The journal the commitment arose in; never changes"
    )
    due_journal_id: int = Field(
        ..., description="The journal the commitment is due in; may be retargeted"
    )
    intermediate_journal_ids: list[int] = Field(
        default_factory=list,
        description=(
            "The journals this task has passed through — discussed, revisited, "
            "or previously due — oldest link first. Neither anchor appears here, "
            "though a journal may be both an anchor and an intermediate link."
        ),
    )
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update")


class TaskResource(BaseModel):
    """Task resource following the JSON:API specification."""

    type: str = Field(default=TASK_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Task ID")
    attributes: TaskAttributes = Field(..., description="Task attributes")
    links: JsonApiLinks | None = Field(default=None, description="Resource links")


class TaskCreateAttributes(BaseModel):
    """Attributes a client may send to create a task.

    ``extra="forbid"`` is deliberate — see the module docstring. Text and journal
    ids are validated by the domain rather than here, so there is one definition
    of an acceptable task rather than two that can drift apart.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="The commitment, as plain text")
    due_journal_id: DatabaseId = Field(
        ...,
        description=(
            "The future-dated journal this task is due in. Must be an existing "
            "journal of yours, dated after today in your timezone."
        ),
    )
    contact_ids: list[DatabaseId] | None = Field(
        default=None,
        description="Optional contacts this task references; duplicates are ignored",
    )


class TaskCreateData(BaseModel):
    """Data for creating a task.

    The resource type is pinned rather than merely defaulted. A generic JSON:API
    client chooses its request shape from the type it declares, so accepting
    ``"contacts"`` here and answering with a task would mean that client
    performed a mutation on a resource type it never asked for. Raised in review.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["tasks"] = Field(
        default=TASK_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC
    )
    attributes: TaskCreateAttributes = Field(
        ..., description="Task attributes to create"
    )


class TaskCreateRequest(JsonApiCreateRequest[TaskCreateData]):
    """Request model for creating a task.

    Forbids extras in its own right rather than inheriting the shared base's
    tolerance. Raised in review: guarding the attributes and the data member
    while leaving the *envelope* permissive meant a ``now`` beside ``data`` was
    silently dropped rather than refused — harmless while nothing reads it, and
    precisely the omission the other two guards exist to prevent. All three
    levels are now closed.
    """

    model_config = ConfigDict(extra="forbid")


class TaskUpdateAttributes(BaseModel):
    """Attributes a client may send to update a task.

    The text and the status, and **both are optional individually**: JSON:API
    sends the attributes that changed, so a client rewording a task sends no
    status and one completing it sends no text. Sending both is a single change
    to a single resource, which is why the service applies them under one read
    and one write rather than as two calls that could half-succeed.

    What is refused is a body naming *neither*. Down in the service that is
    simply nothing to do; out here it is a client that built a request wrong,
    and answering 200 would tell it the edit it thinks it made was applied.

    The due journal (Phase 8) and contact links (Phase 11) are edited through
    their own surfaces, and ``extra="forbid"`` is what keeps their absence a
    contract rather than an omission — a field arriving early is refused rather
    than silently dropped.
    """

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(
        default=None,
        description=(
            "The task's new text, replacing the existing text entirely. "
            "Editable in any status, including cancelled. Omit to leave it "
            "unchanged."
        ),
    )
    status: TaskStatus | None = Field(
        default=None,
        description=(
            "The status to move the task to: not_done, done, or cancelled. A "
            "cancelled task cannot be moved back here — retarget it onto a new "
            "future journal to reopen it as not done. Omit to leave it "
            "unchanged."
        ),
    )

    @model_validator(mode="after")
    def _must_name_a_change(self) -> TaskUpdateAttributes:
        """Refuse an update that updates nothing.

        Note this also settles what an explicit ``null`` means: text is required
        on a task, so ``{"text": null}`` cannot mean "remove it", and reading it
        as "not sent" is the only interpretation that does not invent a fourth
        state. A body carrying nothing but nulls therefore names no change and
        is refused here like any other.
        """
        if self.text is None and self.status is None:
            raise ValueError("An update must name at least one of 'text' or 'status'.")
        return self


class TaskUpdateData(BaseModel):
    """Data for updating a task.

    The resource type is pinned for the reason the create data pins it, and the
    id is required because JSON:API identifies the resource in the body as well
    as in the path. The controller refuses a body whose id disagrees with the
    path rather than quietly preferring one of them.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["tasks"] = Field(
        default=TASK_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC
    )
    id: str = Field(..., description="Task ID to update; must match the path")
    attributes: TaskUpdateAttributes = Field(
        ..., description="Task attributes to update"
    )


class TaskUpdateRequest(JsonApiUpdateRequest[TaskUpdateData]):
    """Request model for updating a task.

    Forbids extras in its own right, closing the envelope level the shared base
    leaves open — the same three-level guard the create request ended up with.
    """

    model_config = ConfigDict(extra="forbid")


class TaskRetargetAttributes(BaseModel):
    """What a client may send to move a task onto a new due journal.

    Two fields, and the reasoning for what is *not* here is the same reasoning
    that keeps this off the status ``PATCH`` altogether. A retarget is not a
    field assignment: it forces the status to *not done* and writes an
    intermediate link, so a ``status`` alongside a ``due_journal_id`` would be a
    second answer to a question the operation has already settled. There is no
    ``creating_journal_id`` for the reason the create attributes have none —
    *"set once and never changes"* is enforced by there being nothing to send —
    and no date, because a task is due in a journal that already exists.
    """

    model_config = ConfigDict(extra="forbid")

    due_journal_id: DatabaseId = Field(
        ...,
        description=(
            "The future-dated journal this task should now be due in. Must be an "
            "existing journal of yours, dated after today in your timezone — the "
            "rule is re-checked here, whatever the task's current status."
        ),
    )
    acknowledge_reopen: StrictBool = Field(
        default=False,
        description=(
            "Confirms that reopening a *done* task is intended. Retargeting "
            "always leaves a task not done, so moving a completed task's due "
            "journal reopens it; without this the request is refused with "
            "TASK_REOPEN_NOT_ACKNOWLEDGED. Ignored for any other status — "
            "retargeting is the documented way out of cancelled and needs no "
            'confirmation. Must be a JSON boolean: 1, "true" and "yes" are '
            "refused rather than coerced."
        ),
    )
    """``StrictBool``, not ``bool``, and the difference is the whole gate.

    Pydantic's ordinary ``bool`` parsing is lax: ``1``, ``"true"``, ``"yes"``
    and ``"on"`` all arrive as ``True``. For most fields that is a convenience;
    here it means a client that sent the wrong *type* has reopened a completed
    task, which is precisely the outcome this field exists to make deliberate.
    An explicit confirmation that can be produced by accident is not one, so the
    schema refuses anything that is not already a boolean. Raised in review on
    the pull request, against a test whose stated intent — non-booleans are
    refused — only held for values Pydantic could not coerce at all.
    """


class TaskRetargetData(BaseModel):
    """Data for retargeting a task.

    The type names the **operation**, as ``journal-merge`` does, rather than the
    ``tasks`` resource: the body is an instruction with its own preconditions,
    not the task's own attributes. There is no ``id`` member for the same
    reason — the request does not describe a task, so there is nothing here for
    a task id to identify, and the path already says which one.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["task-retarget"] = Field(
        default=TASK_RETARGET_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC
    )
    attributes: TaskRetargetAttributes = Field(
        ...,
        description="Where the task should now be due, and whether a reopen "
        "is intended",
    )


class TaskRetargetRequest(BaseModel):
    """Request model for retargeting a task's due journal.

    Forbids extras at all three levels, as the create and update requests
    ended up doing. It matters more here than anywhere else on this surface: a
    misspelled ``acknowledge_reopen`` that was silently dropped would leave a
    caller believing it had confirmed a reopen, and the request would be refused
    for a reason the caller thought it had already answered.
    """

    model_config = ConfigDict(extra="forbid")

    data: TaskRetargetData = Field(..., description="The retarget to perform")


class TaskContactLinkData(BaseModel):
    """The contact a link request names, as a JSON:API resource identifier.

    A resource identifier object is a *type and an id* — there are no
    attributes, because a task-contact link has nothing to carry. The
    specification is explicit that these links hold no relationship type, no
    role and no attendance status, which is a claim about what the surface
    **refuses**, not merely about what it omits: dropping a ``role`` silently
    would leave a client believing it had recorded one. ``extra="forbid"`` is
    what turns the omission into a contract.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["contacts"] = Field(
        default=CONTACT_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC
    )
    id: str = Field(..., description="The id of the contact to link")

    @field_validator("id")
    @classmethod
    def _must_name_a_row(cls, value: str) -> str:
        """JSON:API carries ids as strings; this system's contact ids are integers.

        Checked here rather than in the controller so a malformed id is a 400
        from the schema like every other bad field, instead of a ``ValueError``
        escaping a cast as a 500.

        **The range matters as much as the type**, which review caught. Python's
        ``int`` is unbounded and ``contacts.id`` is a PostgreSQL ``INTEGER``, so
        ``2147483648`` parsed cleanly, reached the repository and died in the
        driver — asyncpg refuses to *bind* an out-of-range value, so the caller
        got a 500 for what is plainly a bad request. See
        :mod:`app.api.common.identifiers`.
        """
        try:
            contact_id = int(value)
        except ValueError as error:
            raise ValueError("The contact id must be an integer") from error
        if not 1 <= contact_id <= INT32_MAX:
            raise ValueError(
                f"The contact id must be between 1 and {INT32_MAX}; no row can "
                f"have the id {contact_id}"
            )
        return value

    @property
    def contact_id(self) -> int:
        """The id as the domain wants it, having been validated above."""
        return int(self.id)


class TaskContactLinkRequest(BaseModel):
    """Request model for linking a contact to a task.

    Forbids extras at the envelope as well as inside ``data``, for the reason
    the create request ended up doing so: a guard with a gap is no guard to
    whoever finds the gap, and a JSON:API envelope has more than one nesting
    depth.

    A single identifier rather than JSON:API's to-many array is a deliberate
    narrowing. One link per call keeps "was anything created" unambiguous, and
    it matches the shape the contact-tag surface already uses.
    """

    model_config = ConfigDict(extra="forbid")

    data: TaskContactLinkData = Field(..., description="The contact to link")


class TaskIntermediateJournalLinkData(BaseModel):
    """The journal an attach request names, as a JSON:API resource identifier.

    Structurally the contact link's twin, and deliberately so — the two are the
    same kind of statement, *this task is connected to that row* — but the
    resource ``type`` is what tells them apart for a client that posts to the
    wrong route.

    **There is no role field, and its absence is a contract.** A task's journals
    come in three roles, and only *intermediate* is a row in this table: the
    creating and due journals are columns on the task, set when it is created and
    when it is retargeted. A ``role`` accepted here and dropped would leave a
    client believing it had attached a due journal.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["journals"] = Field(
        default=JOURNAL_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC
    )
    id: str = Field(..., description="The id of the journal to attach")

    @field_validator("id")
    @classmethod
    def _must_name_a_row(cls, value: str) -> str:
        """JSON:API carries ids as strings; this system's journal ids are integers.

        Checked here rather than in the controller for the reason the contact
        link checks it here: a malformed id is then a 400 from the schema like
        every other bad field, instead of a ``ValueError`` escaping a cast as a
        500. The range matters as much as the type — ``journals.id`` is a
        PostgreSQL ``INTEGER`` and Python's ``int`` is not, so an id past
        ``INT32_MAX`` would reach the driver and die in parameter binding. See
        :mod:`app.api.common.identifiers`.
        """
        try:
            journal_id = int(value)
        except ValueError as error:
            raise ValueError("The journal id must be an integer") from error
        if not 1 <= journal_id <= INT32_MAX:
            raise ValueError(
                f"The journal id must be between 1 and {INT32_MAX}; no row can "
                f"have the id {journal_id}"
            )
        return value

    @property
    def journal_id(self) -> int:
        """The id as the domain wants it, having been validated above."""
        return int(self.id)


class TaskIntermediateJournalLinkRequest(BaseModel):
    """Request model for attaching an intermediate journal to a task.

    Forbids extras at the envelope as well as inside ``data``, for the reason the
    create request ended up doing so: a guard with a gap is no guard to whoever
    finds the gap, and a JSON:API envelope has more than one nesting depth.

    One journal per call rather than JSON:API's to-many array, matching the
    contact link and the contact-tag surface before it. Recorded as a knowing
    narrowing of the relationship semantics rather than an oversight.
    """

    model_config = ConfigDict(extra="forbid")

    data: TaskIntermediateJournalLinkData = Field(
        ..., description="The journal to attach"
    )


class TaskResponse(JsonApiResponse[TaskResource]):
    """Response model for a single task."""

    pass


def persisted_task_id(task: Task) -> int:
    """The task's id, refusing to render one that has none.

    ``task.id or 0`` was the first version and is worse than it looks: a task
    without an id would render ``id="None"`` beside a ``self`` link pointing at
    ``/api/tasks/0`` — a resource identifying itself two ways, neither of them a
    task that exists. Unreachable through the service, which only ever renders
    what a repository handed back, so this fails loudly rather than being papered
    over, matching ``ContactConverter._validate_entity_id``.
    """
    if task.id is None:
        raise ValueError(
            "Cannot serialize task without ID - task must be persisted first"
        )
    return task.id


def task_self_link(task_id: int, base_url: str = "") -> str:
    """The canonical URL of a task resource.

    Built here rather than in a controller so the write responses and the read
    both emit the same string. Until this phase no route could serve it, and a
    ``self`` link that 404s is worse than an absent one, which is why the write
    responses carried none until now.

    ``base_url`` is a parameter with an empty default rather than something read
    from a request, which is the shape ``ContactConverter.to_resource`` and
    ``JournalConverter`` already use: the renderer stays a pure function of its
    arguments — and so stays unit-testable without a request — while the
    controller passes ``get_request_base_url(request)`` so the emitted link is
    **absolute**, like every other ``links.self`` in this API. A client that
    resolves ``self`` uniformly across resource types must not get two shapes.
    """
    return f"{base_url}/api/tasks/{task_id}"


class TaskJournalRefSchema(BaseModel):
    """One of a task's journals, as a read surface shows it.

    Enough to render a link without a second request, and nothing more: a task
    row is not a journal browser.
    """

    id: int = Field(..., description="The journal's id")
    title: str = Field(..., description="Its title, so a link needs no follow-up")
    date: date_type = Field(
        ...,
        description=(
            "Its date, already resolved in your timezone. A date rather than an "
            "instant, so a client cannot re-derive it in the browser's zone and "
            "disagree with the rule that judged whether the task lapsed."
        ),
    )
    cancelled: bool = Field(
        ...,
        description=(
            "Whether this is a cancelled event journal. Only the due journal's "
            "value lapses a task, but the flag is carried on every journal so a "
            "surface can mark one wherever it shows it."
        ),
    )


class TaskContactRefSchema(BaseModel):
    """One of a task's contacts, as a row shows them.

    A plain reference: task-contact links carry no relationship type, no role
    and no attendance status, so neither does this.
    """

    id: int = Field(..., description="The contact's id")
    display_name: str = Field(..., description="The name to show")
    photo_url: str | None = Field(
        default=None, description="Their avatar, when they have one"
    )


class TaskReadAttributes(TaskAttributes):
    """A task as a read surface returns it.

    **A superset of the written task, not a different shape.** Every attribute
    create, ``PATCH`` and retarget answer with is inherited, ``intermediate_journal_ids``
    included, and the resolved journals, the contacts and the lapse are added on
    top. A client that already renders a written task therefore renders a read
    one, which is the "one renderer for the resource" rule the write responses
    were built around.
    """

    creating_journal: TaskJournalRefSchema = Field(
        ..., description="The journal the commitment arose in"
    )
    due_journal: TaskJournalRefSchema = Field(
        ..., description="The journal it is due in — the only one that can lapse it"
    )
    intermediate_journals: list[TaskJournalRefSchema] = Field(
        default_factory=list,
        description=(
            "The journals it has passed through, resolved. Same order and same "
            "membership as intermediate_journal_ids, which is kept beside this "
            "so a client written against the write responses still works."
        ),
    )
    contacts: list[TaskContactRefSchema] = Field(
        default_factory=list, description="The contacts it references, in link order"
    )
    lapsed: bool = Field(
        ...,
        description=(
            "Whether the commitment has been let slide: still not done, and its "
            "due journal has either passed or been cancelled. Derived on every "
            "read and never stored."
        ),
    )
    lapse_reason: LapseReason | None = Field(
        default=None,
        description=(
            "Why it lapsed, or null. Structured rather than pre-worded, because "
            "'the day went by' and 'the meeting was called off' ask the user for "
            "different things and a surface words them differently."
        ),
    )


class JournalTaskAttributes(TaskReadAttributes):
    """A task as a *journal's* listing returns it: the read shape, plus its roles.

    ``link_roles`` exists only here. On the single-task read there is no journal
    in question, so an always-empty field would be a question the payload could
    not answer rather than one whose answer happened to be nothing.
    """

    link_roles: list[TaskLinkRole] = Field(
        default_factory=list,
        description=(
            "How this task is linked to the journal being listed, among the "
            "groups this response returns. More than one when the journal is "
            "both anchors, or is the due journal of a task that already "
            "mentioned it. Under a role filter this narrows with the groups, so "
            "it never names a group meta.groups reports as empty; ask without a "
            "filter for every role the task holds here."
        ),
    )


class TaskReadResource(BaseModel):
    """A task resource carrying the full read shape."""

    type: str = Field(default=TASK_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Task ID")
    attributes: TaskReadAttributes = Field(..., description="Task attributes")
    links: JsonApiLinks | None = Field(default=None, description="Resource links")


class JournalTaskResource(BaseModel):
    """A task resource inside a journal's listing."""

    type: str = Field(default=TASK_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Task ID")
    attributes: JournalTaskAttributes = Field(..., description="Task attributes")
    links: JsonApiLinks | None = Field(default=None, description="Resource links")


class JournalTaskGroupIds(BaseModel):
    """The journal's tasks by role, as ordered id lists.

    The grouping itself, stated rather than left to be reassembled from
    ``link_roles``. All three keys are always present — empty groups included —
    so a client parses one shape whether the journal has tasks, has none, or was
    asked for a single role.
    """

    due: list[int] = Field(
        default_factory=list, description="Tasks due in this journal"
    )
    created: list[int] = Field(
        default_factory=list, description="Tasks created in this journal"
    )
    mentioned: list[int] = Field(
        default_factory=list, description="Tasks that merely mention it"
    )


class JournalTasksMeta(BaseModel):
    """The listing's metadata: the grouping.

    A model of its own rather than the shared ``JsonApiMeta``, whose fields are
    the pagination ones. This collection is not paginated — a journal's tasks
    are bounded by the journal — so borrowing that model would advertise page
    controls that do not exist.
    """

    groups: JournalTaskGroupIds = Field(
        ..., description="The journal's tasks by link role, in display order"
    )


class TaskReadResponse(JsonApiResponse[TaskReadResource]):
    """Response model for reading a single task."""

    pass


class JournalTasksResponse(BaseModel):
    """Response model for a journal's tasks.

    Each task appears **once** in ``data`` however many of the journal's roles
    it holds, because JSON:API forbids the same resource twice there — so the
    roles ride on each resource and the grouping lives in ``meta``. The matching
    MCP tool, which has no such rule, nests the tasks under the roles instead.
    """

    data: list[JournalTaskResource] = Field(
        ..., description="The journal's tasks, each once, in due-date order"
    )
    meta: JournalTasksMeta = Field(..., description="The grouping by link role")


def _journal_ref(ref: TaskJournalRef) -> TaskJournalRefSchema:
    """Render one journal ref."""
    return TaskJournalRefSchema(
        id=ref.id, title=ref.title, date=ref.date, cancelled=ref.cancelled
    )


def _contact_ref(ref: TaskContactRef) -> TaskContactRefSchema:
    """Render one contact ref."""
    return TaskContactRefSchema(
        id=ref.id, display_name=ref.display_name, photo_url=ref.photo_url
    )


def _read_attributes(model: TaskReadModel) -> dict[str, Any]:
    """The read attributes shared by the single read and a journal's listing."""
    return {
        "text": model.task.text,
        "status": model.task.status,
        "creating_journal_id": model.task.creating_journal_id,
        "due_journal_id": model.task.due_journal_id,
        "intermediate_journal_ids": [ref.id for ref in model.intermediate_journals],
        "created_at": model.task.created_at,
        "updated_at": model.task.updated_at,
        "creating_journal": _journal_ref(model.creating_journal),
        "due_journal": _journal_ref(model.due_journal),
        "intermediate_journals": [
            _journal_ref(ref) for ref in model.intermediate_journals
        ],
        "contacts": [_contact_ref(ref) for ref in model.contacts],
        # Taken from the model rather than recomputed from the reason, so the
        # flag and the reason can never disagree about the same task.
        "lapsed": model.lapsed,
        "lapse_reason": model.lapse_reason,
    }


def to_task_read_resource(model: TaskReadModel, base_url: str = "") -> TaskReadResource:
    """Render an assembled read model as a JSON:API resource.

    Pure — no request, no connection, no service — which is why it lives here
    beside the models it produces rather than inside a controller, and why it
    can be asserted directly by a unit test.

    Args:
        model: The assembled read model
        base_url: Prefix for the ``self`` link, so it is absolute like every
            other resource's. The controller supplies it from the request.

    Returns:
        The resource, carrying the ``self`` link this phase makes reachable.
    """
    task_id = persisted_task_id(model.task)
    return TaskReadResource(
        id=str(task_id),
        attributes=TaskReadAttributes(**_read_attributes(model)),
        links=JsonApiLinks(self=task_self_link(task_id, base_url)),
    )


def _journal_task_resource(
    model: TaskReadModel, groups: JournalTaskGroups, base_url: str
) -> JournalTaskResource:
    """One row of a journal's listing, with the roles it holds here."""
    task_id = persisted_task_id(model.task)
    return JournalTaskResource(
        id=str(task_id),
        attributes=JournalTaskAttributes(
            **_read_attributes(model),
            link_roles=list(groups.roles_for(task_id)),
        ),
        links=JsonApiLinks(self=task_self_link(task_id, base_url)),
    )


class UpcomingWindowSchema(BaseModel):
    """The span a listing covers, in the acting user's timezone.

    Dates rather than instants, for the reason a journal ref carries one: the
    window was decided in the user's zone, and a client that re-derived it in
    the browser's could disagree with the rows it was sent.
    """

    start_date: date_type = Field(
        ..., description="Today in your timezone — the window includes it"
    )
    end_date: date_type = Field(
        ..., description="The last day in the window, which is also included"
    )
    days_ahead: int = Field(
        ...,
        description=(
            "How far ahead this answer looked. Echoed rather than left to be "
            "derived by subtracting the two dates, so a surface can label "
            "itself without doing calendar arithmetic."
        ),
    )


class UpcomingTasksMeta(BaseModel):
    """The listing's metadata: the window it covers and how much is in it.

    A model of its own rather than the shared ``JsonApiMeta``, whose fields are
    the pagination ones — this collection is bounded by its window rather than
    paged, so borrowing that model would advertise controls that do not exist.
    """

    window: UpcomingWindowSchema = Field(
        ..., description="The span these tasks are due in"
    )
    total: int = Field(
        ...,
        description=(
            "How many tasks fall in the window. Equal to the length of data, "
            "because the whole window is returned rather than a page of it: a "
            "surface showing the first few can name the full count without a "
            "second request, and revealing the rest costs nothing."
        ),
    )


class UpcomingTasksResponse(BaseModel):
    """Response model for the upcoming-window listing.

    ``data`` holds the same ``TaskReadResource`` the single read returns, so a
    client renders a dashboard row with the renderer it already has. There is
    no ``link_roles`` here and deliberately so: that field answers "how is this
    task linked to the journal being listed", and this listing is about a
    window, in which the question has no meaning.
    """

    data: list[TaskReadResource] = Field(
        ..., description="The tasks due in the window, soonest first"
    )
    meta: UpcomingTasksMeta = Field(..., description="The window and its total")


def to_upcoming_tasks_response(
    upcoming: UpcomingTasks, base_url: str = ""
) -> UpcomingTasksResponse:
    """Render the upcoming-window answer as its listing response.

    Pure, like the other two renderers, and for the same reason: no request, no
    connection, no service, so it can be asserted directly.

    Args:
        upcoming: The selected tasks and the window they were selected for
        base_url: Prefix for each row's ``self`` link, so it is absolute like
            every other resource's

    Returns:
        The response: the rows in the read shape, with the window and the total
        in ``meta``.
    """
    return UpcomingTasksResponse(
        data=[to_task_read_resource(model, base_url) for model in upcoming.tasks],
        meta=UpcomingTasksMeta(
            window=UpcomingWindowSchema(
                start_date=upcoming.window.first_day,
                end_date=upcoming.window.last_day,
                days_ahead=upcoming.window.days_ahead,
            ),
            total=upcoming.total,
        ),
    )


def to_journal_tasks_response(
    groups: JournalTaskGroups, base_url: str = ""
) -> JournalTasksResponse:
    """Render a journal's grouped tasks as the listing response.

    Args:
        groups: The grouped read models
        base_url: Prefix for each row's ``self`` link, as above

    Returns:
        The response: each task once in ``data`` with the roles it holds, and
        the ordered id lists per role in ``meta``.
    """
    # Validated across all three groups rather than only over ``groups.tasks``,
    # which de-duplicates by id and therefore *skips* a model that has none —
    # so an unpersisted task would silently vanish from the listing instead of
    # failing. A row missing from a journal's tasks is worse than an error:
    # the caller cannot tell it was dropped.
    for group in (groups.due, groups.created, groups.mentioned):
        for model in group:
            persisted_task_id(model.task)

    return JournalTasksResponse(
        data=[
            _journal_task_resource(model, groups, base_url) for model in groups.tasks
        ],
        meta=JournalTasksMeta(
            groups=JournalTaskGroupIds(
                due=[model.task.id for model in groups.due if model.task.id],
                created=[model.task.id for model in groups.created if model.task.id],
                mentioned=[
                    model.task.id for model in groups.mentioned if model.task.id
                ],
            )
        ),
    )

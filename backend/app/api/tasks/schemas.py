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

from datetime import datetime
from typing import Literal

from core_shared.models.tasks import TaskStatus
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

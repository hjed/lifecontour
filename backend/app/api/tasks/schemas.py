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
from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    Only the status, for now. Text is editable in any status and the due journal
    is retargetable, but each has its own rules and its own phase; carrying
    either field here before those rules exist would accept an edit and silently
    do nothing with it. ``extra="forbid"`` is what makes that a contract rather
    than an omission, so a field arriving early is refused rather than dropped.
    """

    model_config = ConfigDict(extra="forbid")

    status: TaskStatus = Field(
        ...,
        description=(
            "The status to move the task to: not_done, done, or cancelled. A "
            "cancelled task cannot be moved back here — retarget it onto a new "
            "future journal to reopen it as not done."
        ),
    )


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
    acknowledge_reopen: bool = Field(
        default=False,
        description=(
            "Confirms that reopening a *done* task is intended. Retargeting "
            "always leaves a task not done, so moving a completed task's due "
            "journal reopens it; without this the request is refused with "
            "TASK_REOPEN_NOT_ACKNOWLEDGED. Ignored for any other status — "
            "retargeting is the documented way out of cancelled and needs no "
            "confirmation."
        ),
    )


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


class TaskResponse(JsonApiResponse[TaskResource]):
    """Response model for a single task."""

    pass

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
"""

from datetime import datetime
from typing import Literal

from core_shared.models.tasks import TaskStatus
from pydantic import BaseModel, ConfigDict, Field

from app.api.common.schemas import (
    JsonApiCreateRequest,
    JsonApiLinks,
    JsonApiResponse,
    JsonApiUpdateRequest,
)

RESOURCE_TYPE_DESC = "Resource type"
TASK_RESOURCE_TYPE: Literal["tasks"] = "tasks"


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
    due_journal_id: int = Field(
        ...,
        description=(
            "The future-dated journal this task is due in. Must be an existing "
            "journal of yours, dated after today in your timezone."
        ),
    )
    contact_ids: list[int] | None = Field(
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


class TaskResponse(JsonApiResponse[TaskResource]):
    """Response model for a single task."""

    pass

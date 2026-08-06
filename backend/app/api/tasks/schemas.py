"""JSON:API schemas for the tasks domain.

Two shapes of the create request are load-bearing rather than incidental.

**Unknown attributes are rejected.** ``TaskService.create_task`` takes a ``now``
parameter that exists so a test can stand either side of a local midnight; a
request able to set it would make the future-dated invariant opt-out for every
client. Absence alone does not enforce that — a model that ignored unknown keys
would start honouring ``now`` the moment somebody wired the attributes through
with ``**model_dump()`` — so ``extra="forbid"`` makes the omission a contract.

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

from app.api.common.schemas import JsonApiCreateRequest, JsonApiLinks, JsonApiResponse

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
    """Request model for creating a task."""

    pass


class TaskResponse(JsonApiResponse[TaskResource]):
    """Response model for a single task."""

    pass

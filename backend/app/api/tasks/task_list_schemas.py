"""JSON:API schemas for task lists.

Every level of the create request forbids extras — envelope, data member and
attributes — as the task create request does, so a client sending ``position``
or ``archived_at`` is told no rather than silently ignored: the bottom of the
list is the only place a new list can go, and a new list is never archived.

``icon`` is typed :class:`TaskIcon` on both the request and the response, so
the fixed key set is published in the OpenAPI document as a named enum. The
frontend icon picker takes the keys from there rather than a hand copy.
"""

from datetime import datetime
from typing import Literal

from core_shared.models.tasks import TaskIcon, TaskList
from pydantic import BaseModel, ConfigDict, Field

from app.api.common.schemas import (
    JsonApiCollectionResponse,
    JsonApiCreateRequest,
    JsonApiLinks,
    JsonApiResponse,
)

TASK_LIST_RESOURCE_TYPE: Literal["task-lists"] = "task-lists"


class TaskListAttributes(BaseModel):
    """A task list as the API shows it."""

    name: str = Field(..., description="The list's name")
    icon: TaskIcon | None = Field(
        default=None, description="Icon key from the fixed set, or null"
    )
    position: int = Field(
        ..., description="Place among your lists, 0 at the top; lists may share one"
    )
    archived: bool = Field(
        ..., description="Whether the list is archived (read-only until unarchived)"
    )
    archived_at: datetime | None = Field(
        default=None, description="When the list was archived, or null"
    )
    created_at: datetime | None = Field(default=None, description="Creation time")
    updated_at: datetime | None = Field(default=None, description="Last update time")


class TaskListResource(BaseModel):
    """Task list resource following the JSON:API specification."""

    type: Literal["task-lists"] = Field(
        default=TASK_LIST_RESOURCE_TYPE, description="Resource type"
    )
    id: str = Field(..., description="Task list ID")
    attributes: TaskListAttributes = Field(..., description="Task list attributes")
    links: JsonApiLinks | None = Field(default=None, description="Resource links")


class TaskListResponse(JsonApiResponse[TaskListResource]):
    """Response holding one task list."""


class TaskListCollectionResponse(JsonApiCollectionResponse[TaskListResource]):
    """Response holding the user's task lists for one archived filter.

    Unpaginated: the lists a user keeps are a sidebar-sized set. Paging arrives
    with the archived lists page, which is the listing that can grow.
    """


class TaskListCreateAttributes(BaseModel):
    """Attributes a client may send to create a task list.

    The name is validated by the domain (non-blank, bounded) rather than here,
    so there is one definition of an acceptable name.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="The list's name. Required and non-blank.")
    icon: TaskIcon | None = Field(
        default=None, description="Optional icon key from the fixed set"
    )


class TaskListCreateData(BaseModel):
    """Data for creating a task list; the resource type is pinned."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["task-lists"] = Field(
        default=TASK_LIST_RESOURCE_TYPE, description="Resource type"
    )
    attributes: TaskListCreateAttributes = Field(
        ..., description="Task list attributes to create"
    )


class TaskListCreateRequest(JsonApiCreateRequest[TaskListCreateData]):
    """Request model for creating a task list."""

    model_config = ConfigDict(extra="forbid")


def task_list_self_link(task_list_id: int, base_url: str = "") -> str:
    """The canonical URL of a task list resource."""
    return f"{base_url}/api/task-lists/{task_list_id}"


def to_task_list_resource(task_list: TaskList, base_url: str = "") -> TaskListResource:
    """Render a persisted task list as a JSON:API resource."""
    # Unreachable through the services, which only render what a repository
    # handed back — so it fails loudly rather than rendering ``id="None"``.
    if task_list.id is None or task_list.position is None:
        raise ValueError(
            "Cannot serialize task list without ID and position - "
            "task list must be persisted first"
        )
    return TaskListResource(
        id=str(task_list.id),
        attributes=TaskListAttributes(
            name=task_list.name,
            icon=task_list.icon,
            position=task_list.position,
            archived=task_list.is_archived,
            archived_at=task_list.archived_at,
            created_at=task_list.created_at,
            updated_at=task_list.updated_at,
        ),
        links=JsonApiLinks(self=task_list_self_link(task_list.id, base_url)),
    )

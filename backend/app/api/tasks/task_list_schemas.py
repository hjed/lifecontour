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
from typing import Literal, Self

from core_shared.models.tasks import TaskIcon, TaskList
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.common.schemas import (
    JsonApiCollectionResponse,
    JsonApiCreateRequest,
    JsonApiLinks,
    JsonApiResponse,
    JsonApiUpdateRequest,
)
from app.core.tasks.services.task_list_patch import TaskListPatch
from app.shared.patch import UNSET

TASK_LIST_RESOURCE_TYPE: Literal["task-lists"] = "task-lists"
RESOURCE_TYPE_DESC = "Resource type"


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
        default=TASK_LIST_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC
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
        default=TASK_LIST_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC
    )
    attributes: TaskListCreateAttributes = Field(
        ..., description="Task list attributes to create"
    )


class TaskListCreateRequest(JsonApiCreateRequest[TaskListCreateData]):
    """Request model for creating a task list."""

    model_config = ConfigDict(extra="forbid")


class TaskListUpdateAttributes(BaseModel):
    """Attributes a client may send to update a task list: its name, its icon.

    JSON:API sends the attributes that changed, so both are optional — but the
    two differ on ``null``. ``"icon": null`` **clears** the icon, while leaving
    ``icon`` out leaves it alone; the controller tells them apart with
    ``model_fields_set``. A list must have a name, so ``"name": null`` is
    refused rather than read as "not sent".

    A body naming neither is refused: down in the service it is simply nothing
    to do, but out here it is a client that built a request wrong, and a 200
    would tell it an edit it thinks it made was applied. ``extra="forbid"``
    refuses ``position`` and the archive state, which are their own operations.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        description="The list's new name, non-blank. Omit to leave it unchanged.",
    )
    icon: TaskIcon | None = Field(
        default=None,
        description=(
            "Icon key from the fixed set, or null to clear the icon. Omit to "
            "leave it unchanged."
        ),
    )

    @model_validator(mode="after")
    def _must_name_a_change(self) -> Self:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("'name' cannot be null: a task list must have a name.")
        if not self.model_fields_set:
            raise ValueError("An update must name at least one of 'name' or 'icon'.")
        return self

    def to_patch(self) -> TaskListPatch:
        """The fields this body names, as the service takes them."""
        return TaskListPatch(
            name=self.name if self.name is not None else UNSET,
            icon=self.icon if "icon" in self.model_fields_set else UNSET,
        )


class TaskListUpdateData(BaseModel):
    """Data for updating a task list; the type is pinned and the id required.

    JSON:API identifies the resource in the body as well as in the path, and
    the controller refuses a body whose id disagrees with the path rather than
    quietly preferring one of them.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["task-lists"] = Field(
        default=TASK_LIST_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC
    )
    id: str = Field(..., description="Task list ID to update; must match the path")
    attributes: TaskListUpdateAttributes = Field(
        ..., description="Task list attributes to update"
    )


class TaskListUpdateRequest(JsonApiUpdateRequest[TaskListUpdateData]):
    """Request model for updating a task list."""

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

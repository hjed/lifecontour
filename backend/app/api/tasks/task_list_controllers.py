"""Task list API endpoints: create a list, read one, list yours.

Thin by design, like the task controller: every rule lives in
``TaskListService`` (the ``@transactional`` create and its event) and
``TaskListReadService`` (owner-scoped reads). This module opens no transaction
and catches no domain error — the registered ``DomainError`` handler renders
``TaskListValidationError`` as 400 ``TASK_VALIDATION_ERROR`` with the field, and
``TaskListNotFoundError`` as 404 ``TASK_LIST_NOT_FOUND``, so the MCP tools
inherit the same answers.

Another user's list is answered exactly as a missing one, and every
``{list_id}`` route is held to that by ``test_task_list_ownership.py``.
"""

from typing import Annotated

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskListArchiveFilter
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import DatabaseIdPath
from app.api.common.schemas import get_request_base_url
from app.api.tasks.task_list_schemas import (
    TaskListCollectionResponse,
    TaskListCreateRequest,
    TaskListResponse,
    to_task_list_resource,
)
from app.core.tasks.services.task_list_read_service import TaskListReadService
from app.core.tasks.services.task_list_service import TaskListService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(tags=["tasks"])


@router.post("/task-lists", status_code=status.HTTP_201_CREATED)
@inject
async def create_task_list(
    task_list_request: TaskListCreateRequest,
    request: Request,
    task_list_service: FromDishka[TaskListService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskListResponse:
    """Create a task list at the bottom of your lists.

    Raises:
        400: A blank or too-long name, an icon outside the fixed set, an unknown
             attribute, or another resource type.
    """
    attributes = task_list_request.data.attributes
    # Provenance is explicit because the service defaults to ``SYSTEM``: a list a
    # person made in the browser must not read as an internal one in history.
    created = await task_list_service.create_task_list(
        user_id=user.id,
        name=attributes.name,
        icon=attributes.icon,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskListResponse(
        data=to_task_list_resource(created, get_request_base_url(request))
    )


@router.get("/task-lists")
@inject
async def list_task_lists(
    request: Request,
    task_list_read_service: FromDishka[TaskListReadService],
    user: FromDishka[SessionUser],  # Require authentication
    archived: Annotated[
        TaskListArchiveFilter,
        Query(
            description=(
                "Which lists by archived state: 'active' (default) and 'all' in "
                "your order, 'archived' most recently archived first"
            )
        ),
    ] = TaskListArchiveFilter.ACTIVE,
) -> TaskListCollectionResponse:
    """List your task lists, filtered by archived state.

    Raises:
        400: An unknown ``archived`` value.
    """
    task_lists = await task_list_read_service.list_task_lists(
        user_id=user.id, archived=archived
    )
    base_url = get_request_base_url(request)
    return TaskListCollectionResponse(
        data=[to_task_list_resource(task_list, base_url) for task_list in task_lists]
    )


@router.get("/task-lists/{list_id}")
@inject
async def get_task_list(
    list_id: DatabaseIdPath,
    request: Request,
    task_list_read_service: FromDishka[TaskListReadService],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskListResponse:
    """Read one of your task lists.

    Raises:
        400: An out-of-range id.
        404: No such list, or it is not yours — indistinguishably.
    """
    task_list = await task_list_read_service.get_task_list(
        user_id=user.id, task_list_id=list_id
    )
    return TaskListResponse(
        data=to_task_list_resource(task_list, get_request_base_url(request))
    )

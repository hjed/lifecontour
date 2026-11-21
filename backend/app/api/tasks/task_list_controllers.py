"""Task list API endpoints: create, read, list, update, move, archive and unarchive.

Thin by design, like the task controller: every rule lives in
``TaskListService`` (the ``@transactional`` writes and their events; the move
publishes none) and ``TaskListReadService`` (owner-scoped reads). This module
opens no transaction and catches no domain error — the registered ``DomainError``
handler renders ``TaskListValidationError`` as 400 ``TASK_VALIDATION_ERROR`` with
the field, ``TaskListNotFoundError`` as 404 ``TASK_LIST_NOT_FOUND`` and
``TaskListArchivedError`` as 409 ``TASK_LIST_ARCHIVED``, so the MCP tools inherit
the same answers.

Another user's list is answered exactly as a missing one, and every
``{list_id}`` route is held to that by ``test_task_list_ownership.py``.
"""

from typing import Annotated

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskListArchiveFilter, TaskListValidationError
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import DatabaseIdPath
from app.api.common.schemas import get_request_base_url
from app.api.tasks.task_list_schemas import (
    TaskListCollectionResponse,
    TaskListCreateRequest,
    TaskListMoveRequest,
    TaskListResponse,
    TaskListUpdateRequest,
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


@router.patch("/task-lists/{list_id}")
@inject
async def update_task_list(
    list_id: DatabaseIdPath,
    task_list_request: TaskListUpdateRequest,
    request: Request,
    task_list_service: FromDishka[TaskListService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskListResponse:
    """Rename one of your task lists, set or clear its icon, or both at once.

    ``"icon": null`` clears the icon; an absent ``icon`` leaves it alone. Both
    attributes arriving are one change, applied under one locked read and one
    write. Values the list already has change nothing and record nothing.

    Raises:
        400: A blank, too-long or null name, an icon outside the fixed set, an
             unknown attribute, a body naming no change, another resource type,
             or a body id that disagrees with the path.
        404: No such list, or it is not yours — indistinguishably.
        409: The list is archived, and read-only until unarchived.
    """
    # A transport concern — which of two places names the resource — so it
    # lives here, as on the task PATCH, and has no MCP counterpart.
    if task_list_request.data.id != str(list_id):
        raise TaskListValidationError(
            "id",
            f"The body's task list id ({task_list_request.data.id}) must match "
            f"the path ({list_id})",
        )

    updated = await task_list_service.update_task_list(
        user_id=user.id,
        task_list_id=list_id,
        patch=task_list_request.data.attributes.to_patch(),
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskListResponse(
        data=to_task_list_resource(updated, get_request_base_url(request))
    )


@router.post("/task-lists/{list_id}/move")
@inject
async def move_task_list(
    list_id: DatabaseIdPath,
    move_request: TaskListMoveRequest,
    request: Request,
    task_list_service: FromDishka[TaskListService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskListCollectionResponse:
    """Move one of your lists to a new place among your active lists.

    ``index`` counts active lists only, 0 at the top; an index past the end
    moves the list to the bottom. Archived lists keep their place among the
    others. A move changes other lists' positions too, so the answer is your
    active lists in their new order. Reordering records no history.

    Raises:
        400: An out-of-range id, a negative or non-integer index, an unknown
             attribute, or another resource type.
        404: No such list, or it is not yours — indistinguishably.
        409: The list is archived, and read-only until unarchived.
    """
    task_lists = await task_list_service.move_task_list(
        user_id=user.id,
        task_list_id=list_id,
        index=move_request.data.attributes.index,
        transaction=connection,
    )
    base_url = get_request_base_url(request)
    return TaskListCollectionResponse(
        data=[to_task_list_resource(task_list, base_url) for task_list in task_lists]
    )


@router.post("/task-lists/{list_id}/archive")
@inject
async def archive_task_list(
    list_id: DatabaseIdPath,
    request: Request,
    task_list_service: FromDishka[TaskListService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskListResponse:
    """Archive one of your lists: read-only until unarchived.

    Takes no body. Its tasks are left exactly as they are, open ones included,
    and the list keeps its place for when it is unarchived. Archiving a list
    that is already archived answers it unchanged and records nothing.

    Raises:
        400: An out-of-range id.
        404: No such list, or it is not yours — indistinguishably.
    """
    archived = await task_list_service.archive_task_list(
        user_id=user.id,
        task_list_id=list_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskListResponse(
        data=to_task_list_resource(archived, get_request_base_url(request))
    )


@router.post("/task-lists/{list_id}/unarchive")
@inject
async def unarchive_task_list(
    list_id: DatabaseIdPath,
    request: Request,
    task_list_service: FromDishka[TaskListService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TaskListResponse:
    """Unarchive one of your lists, back in its old place and writable again.

    Takes no body. Unarchiving a list that is not archived answers it unchanged
    and records nothing.

    Raises:
        400: An out-of-range id.
        404: No such list, or it is not yours — indistinguishably.
    """
    unarchived = await task_list_service.unarchive_task_list(
        user_id=user.id,
        task_list_id=list_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
    )
    return TaskListResponse(
        data=to_task_list_resource(unarchived, get_request_base_url(request))
    )

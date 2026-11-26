"""Task list API endpoints: create, read, list, update, move, archive, unarchive,
the list's history, and reading the tasks on a list.

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
from app.api.history import HistoryListResponse
from app.api.history.pages import (
    HistoryLimitQuery,
    HistoryPageQuery,
    history_offset,
    history_page_response,
)
from app.api.tasks.schemas import (
    CompletedListTasksResponse,
    ListTasksResponse,
    to_completed_list_tasks_response,
    to_list_tasks_response,
)
from app.api.tasks.task_list_schemas import (
    TaskListCollectionResponse,
    TaskListCreateRequest,
    TaskListMoveRequest,
    TaskListResponse,
    TaskListSummaryCollectionResponse,
    TaskListUpdateRequest,
    to_task_list_resource,
    to_task_list_summary_resource,
)
from app.core.history.services.task_list_history_service import (
    TaskListHistoryService,
)
from app.core.tasks.services.task_list_read_service import TaskListReadService
from app.core.tasks.services.task_list_service import TaskListService
from app.core.tasks.services.task_read_service import TaskReadService
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
) -> TaskListSummaryCollectionResponse:
    """List your task lists, filtered by archived state.

    Each list carries ``open_task_count``: how many of its tasks are not done.

    Raises:
        400: An unknown ``archived`` value.
    """
    summaries = await task_list_read_service.list_task_lists(
        user_id=user.id, archived=archived
    )
    base_url = get_request_base_url(request)
    return TaskListSummaryCollectionResponse(
        data=[to_task_list_summary_resource(each, base_url) for each in summaries]
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


@router.get("/task-lists/{list_id}/history")
@inject
async def get_task_list_history(
    list_id: DatabaseIdPath,
    request: Request,
    history_service: FromDishka[TaskListHistoryService],
    user: FromDishka[SessionUser],  # Require authentication
    page: HistoryPageQuery = 1,
    limit: HistoryLimitQuery = 20,
) -> HistoryListResponse:
    """Get a task list's field-level change history, most recent first.

    Each entry names the field that changed and its value on both sides:
    ``__created__`` (the list's name), ``name`` (a rename), ``icon`` (set,
    changed or cleared), ``archived_at`` — an archive moves it from null to
    the instant, an unarchive from the instant back to null — and
    ``associated_journal_id``, the associated journal's id (null when
    unassociated, as a journal delete leaves the list). Each carries its
    provenance and actor, in the shape the task and journal feeds use. Wording
    belongs to the client; these field names are the contract.

    History is produced asynchronously by the projection consumer, so a
    just-made change may take a moment to appear, and a list whose events have
    not been projected yet answers an **empty list rather than a 404** — "not
    projected yet" is not "does not exist". An archived list's history is
    readable: archiving refuses writes, and this is a read.

    Ownership is resolved by ``TaskListHistoryService`` from the history rows
    themselves, with the live list row only as a fallback, so the history stays
    readable by its owner once a list can be deleted, and this endpoint and the
    ``get_task_list_history`` MCP tool cannot answer it differently.

    No transaction is opened on this path. A page past the end is an ordinary
    empty answer; ``meta`` still carries the total.

    Raises:
        400: An out-of-range id, a ``limit`` outside 1–100, or a ``page``
             outside the ``INTEGER`` range.
        404: The list does not exist or is not yours. Another user's list is
             the same answer as an unknown one, so a refusal cannot be used to
             probe for other users' lists.
    """
    entries = await history_service.get_task_list_history(
        task_list_id=list_id,
        user_id=user.id,
        limit=limit,
        offset=history_offset(page, limit),
    )
    total_count = await history_service.get_task_list_history_count(
        task_list_id=list_id, user_id=user.id
    )
    return history_page_response(
        entries,
        total_count=total_count,
        resource_type="task_list_history",
        self_url=f"{get_request_base_url(request)}/api/task-lists/{list_id}/history",
        page=page,
        limit=limit,
    )


@router.get("/task-lists/{list_id}/tasks")
@inject
async def list_task_list_tasks(
    list_id: DatabaseIdPath,
    request: Request,
    task_read_service: FromDishka[TaskReadService],
    user: FromDishka[SessionUser],  # Require authentication
) -> ListTasksResponse:
    """List the open tasks on one of your lists, in your manual order.

    Every task that is not done is returned, and the collection is
    not paginated: a list's open tasks are its working set. Done and cancelled
    tasks are read separately, a page at a time, from
    `GET /api/task-lists/{list_id}/tasks/completed`. Each row is the task read
    shape `GET /api/tasks/{task_id}` answers — its list, due date or due
    journal, flag, icon, contacts and `overdue`. A task on a list never lapses.

    An archived list's tasks are readable; `task_list.archived` on each row
    says they are read-only until the list is unarchived.

    No transaction is opened on this path.

    Raises:
        400: An out-of-range id.
        404: No such list, or it is not yours — indistinguishably, so a refusal
             cannot be used to probe for other users' lists.
    """
    page = await task_read_service.read_models_on_list(user.id, list_id)
    return to_list_tasks_response(page, get_request_base_url(request))


@router.get("/task-lists/{list_id}/tasks/completed")
@inject
async def list_completed_task_list_tasks(
    list_id: DatabaseIdPath,
    request: Request,
    task_read_service: FromDishka[TaskReadService],
    user: FromDishka[SessionUser],  # Require authentication
    page: HistoryPageQuery = 1,
    limit: HistoryLimitQuery = 20,
) -> CompletedListTasksResponse:
    """List one page of the done and cancelled tasks on one of your lists.

    The list page's Completed group: most recently closed first, by when each
    task was done or cancelled — editing a closed task does not move it, and
    reopening one removes it. A cancelled task is marked by its `status`.
    Paginated with `page` and `limit` (1–100, default 20); `meta` carries the
    total and `links` the neighbouring pages. A page past the end is an
    ordinary empty answer and still reports the total.

    An archived list's completed tasks are readable. No transaction is opened
    on this path.

    Raises:
        400: An out-of-range id, a `limit` outside 1–100, or a `page` outside
             the `INTEGER` range.
        404: No such list, or it is not yours — indistinguishably.
    """
    result = await task_read_service.read_closed_models_on_list(
        user.id, list_id, limit=limit, offset=history_offset(page, limit)
    )
    base_url = get_request_base_url(request)
    return to_completed_list_tasks_response(
        result,
        self_url=f"{base_url}/api/task-lists/{list_id}/tasks/completed",
        page=page,
        limit=limit,
        base_url=base_url,
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


@router.delete("/task-lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_task_list(
    list_id: DatabaseIdPath,
    task_list_service: FromDishka[TaskListService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """Delete one of your lists permanently, and its tasks with it.

    **For mistakes.** Archiving is the ordinary way to retire a list; this is
    the destructive one, and the surface should confirm it first.

    Every task on the list goes with it — open or completed — except a task
    holding both a creating and a due journal: that one stays as a journal-only
    task, off any list, and reads as lapsed if its journal has ended. The
    list's history stays readable by you at
    `GET /api/task-lists/{list_id}/history`, ending in a deletion entry.

    An archived list is read-only, so it must be unarchived before it can be
    deleted. Answers 204 with no body: there is no resource left to return.

    Raises:
        400: An out-of-range id.
        404: No such list, or it is not yours — indistinguishably.
        409: `TASK_LIST_ARCHIVED` — the list is archived; unarchive it first.
            `TASK_LIST_CHANGED` — another request was changing the list at the
            same moment; read it again and retry.
    """
    await task_list_service.delete_task_list(
        user_id=user.id,
        task_list_id=list_id,
        transaction=connection,
        source=Provenance.UI,
        changed_by="ui",
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

"""Task list MCP tools: create a list, read one, list the user's lists.

Controller-equivalents, like the task tools: they open no transaction and catch
no domain error. ``create_task_list`` calls the ``@transactional``
``TaskListService``, which commits the list and its event together; the reads
go through ``TaskListReadService``, which can change nothing. A refused name
comes back as a "Task error" naming the field, and another user's list as "Not
found", exactly as a missing one.
"""

from typing import Annotated

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskIcon, TaskList, TaskListArchiveFilter
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from app.core.tasks.services.task_list_read_service import TaskListReadService
from app.core.tasks.services.task_list_service import TaskListService
from app.mcp.domains.tasks.task_list_schemas import TaskListMCP, TaskListsMCP
from app.mcp.shared.annotations import ADDITIVE_WRITE, READ_ONLY
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_task_list_read_service,
    get_task_list_service,
    mcp_depends,
)


def _task_list_fields(task_list: TaskList) -> TaskListMCP:
    """The answer every list-returning tool gives."""
    if task_list.id is None or task_list.position is None:
        raise ValueError("A task list answer needs a persisted task list")
    return TaskListMCP(
        id=task_list.id,
        name=task_list.name,
        icon=task_list.icon,
        position=task_list.position,
        archived=task_list.is_archived,
        archived_at=(
            task_list.archived_at.isoformat() if task_list.archived_at else None
        ),
        created_at=task_list.created_at.isoformat() if task_list.created_at else None,
        updated_at=task_list.updated_at.isoformat() if task_list.updated_at else None,
    )


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_task_list", "task list")
async def create_task_list(
    name: Annotated[
        str,
        Field(description="The list's name, as plain text. Required and non-blank."),
    ],
    icon: Annotated[
        TaskIcon | None,
        Field(description="Optional icon for the list, from the fixed set of keys."),
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_list_service: TaskListService = mcp_depends(get_task_list_service),
) -> TaskListMCP:
    """
    Create a task list: a named home for tasks, added below the user's lists.

    Lists can be created, read and listed; tasks cannot be placed on a list yet,
    so a new list is empty. A blank or overlong name is refused naming the field.
    """
    user_id = await get_current_user_id()

    # Attributed to the assistant: the service defaults to ``SYSTEM``, and an
    # agent's list must not read as an internal one in the user's history.
    created = await task_list_service.create_task_list(
        user_id=user_id,
        name=name,
        icon=icon,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return _task_list_fields(created)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_task_list", "task list")
async def get_task_list(
    task_list_id: Annotated[
        int,
        Field(ge=1, le=INT32_MAX, description="The id of the task list to read."),
    ],
    task_list_read_service: TaskListReadService = mcp_depends(
        get_task_list_read_service
    ),
) -> TaskListMCP:
    """
    Read one of the user's task lists: its name, icon, position and whether it
    is archived. An archived list is read-only until it is unarchived.

    A list that does not exist and one belonging to someone else are both
    reported as not found.
    """
    user_id = await get_current_user_id()
    task_list = await task_list_read_service.get_task_list(
        user_id=user_id, task_list_id=task_list_id
    )
    return _task_list_fields(task_list)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_task_lists", "task list")
async def list_task_lists(
    archived: Annotated[
        TaskListArchiveFilter,
        Field(
            description=(
                "Which lists to return by archived state: 'active' (the default) "
                "and 'all' come in the user's own order; 'archived' comes most "
                "recently archived first."
            )
        ),
    ] = TaskListArchiveFilter.ACTIVE,
    task_list_read_service: TaskListReadService = mcp_depends(
        get_task_list_read_service
    ),
) -> TaskListsMCP:
    """
    List the user's task lists, filtered by archived state.

    Use this to find a list's id by its name before reading it. With no
    argument it returns the lists the user is working with, in their order.
    """
    user_id = await get_current_user_id()
    task_lists = await task_list_read_service.list_task_lists(
        user_id=user_id, archived=archived
    )
    return TaskListsMCP(lists=[_task_list_fields(each) for each in task_lists])

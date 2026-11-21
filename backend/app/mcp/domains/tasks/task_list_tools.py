"""Task list MCP tools: create, update, read, list, move, archive, unarchive and
read a list's history.

Controller-equivalents, like the task tools: they open no transaction and catch
no domain error. The writes (``create_task_list``, ``update_task_list``,
``move_task_list``, ``archive_task_list`` and ``unarchive_task_list``) call the
``@transactional`` ``TaskListService``, which
commits each list and its event together (a move publishes none); the reads go
through ``TaskListReadService``, which can change nothing, and the history
through ``TaskListHistoryService``, which authorises the read itself. A refused name
comes back as a "Task error" naming the field, and another user's list as "Not
found", exactly as a missing one. A write to an archived list comes back as a
"Task error" naming unarchiving as the way out. Every integer argument takes
only a JSON integer (``JsonIntOnly``), as REST does.
"""

from typing import Annotated

from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    TaskIcon,
    TaskList,
    TaskListArchiveFilter,
    TaskListValidationError,
)
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from app.core.history.services.task_list_history_service import (
    TaskListHistoryService,
)
from app.core.tasks.services.task_list_patch import TaskListPatch
from app.core.tasks.services.task_list_read_service import TaskListReadService
from app.core.tasks.services.task_list_service import TaskListService
from app.mcp.domains.tasks.schemas import TaskHistoryEntryMCP
from app.mcp.domains.tasks.task_list_schemas import (
    TaskListHistoryResponse,
    TaskListMCP,
    TaskListsMCP,
    TaskListSummariesMCP,
    TaskListSummaryMCP,
)
from app.mcp.shared.annotations import ADDITIVE_WRITE, IDEMPOTENT_WRITE, READ_ONLY
from app.mcp.shared.arguments import JsonBool, JsonIntOnly
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_task_list_history_service,
    get_task_list_read_service,
    get_task_list_service,
    mcp_depends,
)
from app.shared.patch import UNSET, Unset


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

    Lists can be created, renamed, given or cleared an icon, read, listed,
    reordered, archived and unarchived; tasks cannot be placed on a list yet,
    so a new list is empty. A blank or overlong name is refused naming the
    field.
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


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_task_list", "task list")
async def update_task_list(
    task_list_id: Annotated[
        int,
        Field(ge=1, le=INT32_MAX, description="The id of the task list to change."),
        JsonIntOnly,
    ],
    name: Annotated[
        str | None,
        Field(description="The list's new name, as plain text. Omit to keep it."),
    ] = None,
    icon: Annotated[
        TaskIcon | None,
        Field(description="A new icon from the fixed set of keys. Omit to keep it."),
    ] = None,
    clear_icon: Annotated[
        JsonBool,
        Field(description="Remove the list's icon. Cannot be combined with icon."),
    ] = False,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_list_service: TaskListService = mcp_depends(get_task_list_service),
) -> TaskListMCP:
    """
    Rename one of the user's task lists, change its icon, or remove its icon.

    Only the arguments you supply are changed. To remove the icon pass
    clear_icon=true rather than a null icon, since an omitted icon means "keep
    it". Name at least one change; values the list already has change nothing.
    A blank or overlong name is refused naming the field, and a list that does
    not exist or belongs to someone else is reported as not found. An archived
    list is read-only: unarchive it first.
    """
    # Argument shape, not a domain rule: the clear flag exists only because a
    # tool cannot tell a null argument from an omitted one.
    if clear_icon and icon is not None:
        raise TaskListValidationError(
            "icon", "Pass either an icon or clear_icon=true, not both"
        )
    if name is None and icon is None and not clear_icon:
        raise TaskListValidationError(
            "name", "Name a change: a new name, a new icon, or clear_icon=true"
        )

    user_id = await get_current_user_id()
    icon_change: TaskIcon | None | Unset = UNSET
    if clear_icon:
        icon_change = None
    elif icon is not None:
        icon_change = icon
    patch = TaskListPatch(
        name=name if name is not None else UNSET,
        icon=icon_change,
    )
    updated = await task_list_service.update_task_list(
        user_id=user_id,
        task_list_id=task_list_id,
        patch=patch,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return _task_list_fields(updated)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_task_list", "task list")
async def get_task_list(
    task_list_id: Annotated[
        int,
        Field(ge=1, le=INT32_MAX, description="The id of the task list to read."),
        JsonIntOnly,
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
) -> TaskListSummariesMCP:
    """
    List the user's task lists, filtered by archived state.

    Use this to find a list's id by its name before reading it. With no
    argument it returns the lists the user is working with, in their order.
    Each list carries open_task_count: how many of its tasks are not done.
    """
    user_id = await get_current_user_id()
    summaries = await task_list_read_service.list_task_lists(
        user_id=user_id, archived=archived
    )
    return TaskListSummariesMCP(
        lists=[
            TaskListSummaryMCP(
                **_task_list_fields(each.task_list).model_dump(),
                open_task_count=each.open_task_count,
            )
            for each in summaries
        ]
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("move_task_list", "task list")
async def move_task_list(
    task_list_id: Annotated[
        int,
        Field(ge=1, le=INT32_MAX, description="The id of the task list to move."),
        JsonIntOnly,
    ],
    index: Annotated[
        int,
        Field(
            ge=0,
            le=INT32_MAX,
            description=(
                "Its new place among the user's active lists, 0 at the top — "
                "the order list_task_lists returns. An index past the end moves "
                "it to the bottom."
            ),
        ),
        JsonIntOnly,
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_list_service: TaskListService = mcp_depends(get_task_list_service),
) -> TaskListsMCP:
    """
    Move one of the user's task lists to a new place in their order, and answer
    with all their active lists in the new order.

    Archived lists are not counted by the index and keep their place; an
    archived list cannot be moved until it is unarchived. Reordering is not
    recorded in history.
    """
    user_id = await get_current_user_id()
    task_lists = await task_list_service.move_task_list(
        user_id=user_id,
        task_list_id=task_list_id,
        index=index,
        transaction=db_connection,
    )
    return TaskListsMCP(lists=[_task_list_fields(each) for each in task_lists])


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("archive_task_list", "task list")
async def archive_task_list(
    task_list_id: Annotated[
        int,
        Field(ge=1, le=INT32_MAX, description="The id of the task list to archive."),
        JsonIntOnly,
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_list_service: TaskListService = mcp_depends(get_task_list_service),
) -> TaskListMCP:
    """
    Archive one of the user's task lists: the way to put away a finished list
    rather than delete it.

    An archived list leaves the active listing and is read-only until it is
    unarchived — it cannot be renamed, re-iconed or moved. Its tasks are left
    exactly as they are, open ones included. Archiving a list that is already
    archived changes nothing. A list that does not exist or belongs to someone
    else is reported as not found.
    """
    user_id = await get_current_user_id()
    archived = await task_list_service.archive_task_list(
        user_id=user_id,
        task_list_id=task_list_id,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return _task_list_fields(archived)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("unarchive_task_list", "task list")
async def unarchive_task_list(
    task_list_id: Annotated[
        int,
        Field(ge=1, le=INT32_MAX, description="The id of the task list to unarchive."),
        JsonIntOnly,
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_list_service: TaskListService = mcp_depends(get_task_list_service),
) -> TaskListMCP:
    """
    Unarchive one of the user's task lists, restoring it.

    The list returns to the active listing in the place it had before it was
    archived, and can be changed again. Use list_task_lists with
    archived='archived' to find an archived list's id. Unarchiving a list that
    is not archived changes nothing. A list that does not exist or belongs to
    someone else is reported as not found.
    """
    user_id = await get_current_user_id()
    unarchived = await task_list_service.unarchive_task_list(
        user_id=user_id,
        task_list_id=task_list_id,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return _task_list_fields(unarchived)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_task_list_history", "task list")
async def get_task_list_history(
    task_list_id: Annotated[
        int,
        Field(
            ge=1,
            le=INT32_MAX,
            description="The id of the task list to read the history of.",
        ),
        JsonIntOnly,
    ],
    page: Annotated[
        int,
        Field(description="Page number (1-based)", ge=1, le=INT32_MAX),
        JsonIntOnly,
    ] = 1,
    limit: Annotated[
        int, Field(description="Entries per page", ge=1, le=100), JsonIntOnly
    ] = 20,
    history_service: TaskListHistoryService = mcp_depends(
        get_task_list_history_service
    ),
) -> TaskListHistoryResponse:
    """
    Read a task list's change history: what changed, when, and where it came from.

    Entries are **most recent first** and paginated. Each names the field that
    changed, its value on both sides, when, who acted (``changed_by``) and the
    provenance (``source`` — ``ui``, ``mcp`` for an assistant like you, or
    ``system``). It is the same history the user sees.

    **The field names are the vocabulary.** ``__created__`` opens the history
    and carries the list's name; ``name`` is a rename; ``icon`` is an icon set,
    changed or cleared (an empty side is no icon). ``archived_at`` records
    archiving and unarchiving: ``old_value`` empty and ``new_value`` an ISO
    instant is an **archive**; the instant moving to empty is an **unarchive**.
    Reordering lists is not recorded. Changes to the tasks on a list are in each
    task's own history (``get_task_history``), not here.

    **History is written asynchronously**, a moment behind the change. If you
    change a list and read its history straight back, your change may not be
    there yet; a list whose events have not been projected answers an empty
    history rather than an error. An archived list's history is readable.

    This is a **record of the past, not a way to browse lists** — use
    ``get_task_list`` or ``list_task_lists`` for that. Another user's list is
    reported as not found, exactly as a missing one. A page past the end is an
    ordinary empty answer, and ``total_count`` still says how many entries
    there are.
    """
    user_id = await get_current_user_id()

    entries = await history_service.get_task_list_history(
        task_list_id=task_list_id,
        user_id=user_id,
        limit=limit,
        offset=(page - 1) * limit,
    )
    total_count = await history_service.get_task_list_history_count(
        task_list_id=task_list_id, user_id=user_id
    )
    return TaskListHistoryResponse(
        task_list_id=task_list_id,
        total_count=total_count,
        page=page,
        limit=limit,
        entries=[TaskHistoryEntryMCP.from_entry(entry) for entry in entries],
    )

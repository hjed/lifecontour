"""Tasks domain MCP tools.

A task is a short commitment anchored to two of the user's journals: the one it
arose in, and the future-dated one where it matters. Both anchors are the tool's
arguments because an AI client has no path to take the first from, unlike the
REST surface.

The tools are controller-equivalent and stay that way: they open **no**
transaction and enforce **no** invariant of their own. Every rule — both anchors
exist and are the acting user's, the due journal is future-dated at the moment
it is set, referenced contacts exist, and the status transition is one the
lifecycle permits — belongs to ``TaskService``, which owns the commit. That is
what makes the answers here identical to the endpoint's rather than merely
similar.

**No parameter sets "now".** The service takes one so a test can stand either
side of a local midnight; exposing it would make the future-dated rule opt-out
for any caller, so it is absent here and the transport rejects it as an unknown
argument.
"""

import json
from typing import Annotated, Any

from core_shared.models.tasks import Task, TaskStatus
from fastmcp import FastMCP
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.services.task_service import TaskService
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_task_service,
    mcp_depends,
)


def _task_to_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "text": task.text,
        "status": str(task.status),
        "creating_journal_id": task.creating_journal_id,
        "due_journal_id": task.due_journal_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@mcp_unified_error_handler("create_task", "task")
async def create_task(
    creating_journal_id: Annotated[
        int,
        Field(
            description=(
                "The journal the commitment arose in — the entry you were "
                "reading or writing when it came up. Never changes."
            )
        ),
    ],
    due_journal_id: Annotated[
        int,
        Field(
            description=(
                "The journal the task is due in. Must be an existing journal of "
                "yours dated in the future: today is not the future, and a "
                "multi-day journal already under way is dated by the day it "
                "started. Create the journal first if the day you want has none."
            )
        ),
    ],
    text: Annotated[
        str, Field(description="The commitment, as plain text. Required and non-empty.")
    ],
    contact_ids: Annotated[
        list[int] | None,
        Field(
            description=(
                "Optional ids of contacts this task involves. Duplicates are "
                "ignored; every id must be an existing contact."
            )
        ),
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Create a task: something to do, anchored to the journal it is due in.

    Tasks are always attached to journals — there is no separate task list and
    no due *date*. To make a task due on a particular day, that day's journal
    must already exist; name it as due_journal_id. The creating and due journal
    may be the same one.

    Rejections are actionable rather than generic: a journal that does not exist
    or is not yours is reported as not found naming which anchor it was, and a
    due journal that is not future-dated comes back with both its date and
    today's so a later journal can be chosen.

    Returns:
        JSON string with the created task: id, text, status (always "not_done"
        on creation), both journal anchors, and timestamps.
    """
    user_id = await get_current_user_id()

    created = await task_service.create_task(
        user_id=user_id,
        creating_journal_id=creating_journal_id,
        due_journal_id=due_journal_id,
        text=text,
        transaction=db_connection,
        contact_ids=contact_ids,
    )
    return json.dumps(_task_to_dict(created), indent=2)


@mcp_unified_error_handler("set_task_status", "task")
async def set_task_status(
    task_id: Annotated[int, Field(description="The id of the task to change.")],
    status: Annotated[
        TaskStatus,
        Field(
            description=(
                "The status to move the task to. 'not_done' is outstanding, "
                "'done' is met, 'cancelled' is no longer relevant."
            )
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Mark a task done, not done, or cancelled.

    No journal is involved: marking a task done or cancelled needs no journal
    and creates no journal link, so a task whose due journal has already passed
    can still be completed or cancelled where it stands.

    Done is reversible — a task marked done can be moved back to not done.
    Cancelled is not left this way: a cancelled task is reopened by
    **retargeting** it onto a new future journal, which returns it to not done,
    so asking here for not_done or done on a cancelled task is refused and the
    message says what to do instead. Setting the status a task already has
    changes nothing.

    Returns:
        JSON string with the task: id, text, status, both journal anchors, and
        timestamps.
    """
    user_id = await get_current_user_id()

    updated = await task_service.set_status(
        user_id=user_id,
        task_id=task_id,
        status=status,
        transaction=db_connection,
    )
    return json.dumps(_task_to_dict(updated), indent=2)


@mcp_unified_error_handler("update_task_text", "task")
async def update_task_text(
    task_id: Annotated[int, Field(description="The id of the task to reword.")],
    text: Annotated[
        str,
        Field(
            description=(
                "The task's new text. Replaces the existing text entirely — "
                "send the whole commitment, not an addition to it. Required "
                "and non-empty."
            )
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Reword a task, in any status.

    Text is editable at any time and in any status, including on a task that is
    done or cancelled and on one whose due journal has already passed — nothing
    about a task's state makes its wording unfixable.

    No journal is involved and none is linked: rewording a task does not attach
    it to whatever journal the conversation happens to be about. Use the journal
    link tools for that.

    Returns:
        JSON string with the task: id, text, status, both journal anchors, and
        timestamps.
    """
    user_id = await get_current_user_id()

    updated = await task_service.update_task(
        user_id=user_id,
        task_id=task_id,
        text=text,
        transaction=db_connection,
    )
    return json.dumps(_task_to_dict(updated), indent=2)


@mcp_unified_error_handler("delete_task", "task")
async def delete_task(
    task_id: Annotated[
        int, Field(description="The id of the task to delete permanently.")
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    task_service: TaskService = mcp_depends(get_task_service),
) -> str:
    """
    Delete a task permanently. Prefer cancelling it instead.

    Cancelling is the ordinary way to retire a task: call set_task_status with
    'cancelled'. A cancelled task stays part of the record of what the user
    committed to, and can be reopened later by retargeting it onto a new future
    journal. Deleting is the exception, for genuine mistakes — a duplicate, or
    something recorded against the wrong thing — and it cannot be undone.

    The task's journal and contact links go with it. The journals and contacts
    themselves are untouched, including the journals it was created in and due
    in.

    Deleting a task that does not exist, or is not yours, reports not found —
    including a second delete of a task already deleted.

    Returns:
        JSON string confirming the deletion: deleted (true) and task_id.
    """
    user_id = await get_current_user_id()

    await task_service.delete_task(
        user_id=user_id, task_id=task_id, transaction=db_connection
    )
    return json.dumps({"deleted": True, "task_id": task_id}, indent=2)


def register_task_tools(mcp: FastMCP[None]) -> None:
    """Register task MCP tools with the FastMCP server."""
    mcp.add_tool(create_task)
    mcp.add_tool(set_task_status)
    mcp.add_tool(update_task_text)
    mcp.add_tool(delete_task)

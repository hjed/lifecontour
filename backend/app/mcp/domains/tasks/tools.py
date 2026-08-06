"""Tasks domain MCP tools.

A task is a short commitment anchored to two of the user's journals: the one it
arose in, and the future-dated one where it matters. Both anchors are the tool's
arguments because an AI client has no path to take the first from, unlike the
REST surface.

The tool is controller-equivalent and stays that way: it opens **no**
transaction and enforces **no** invariant of its own. Every rule — both anchors
exist and are the acting user's, the due journal is future-dated at the moment
it is set, referenced contacts exist — belongs to ``TaskService.create_task``,
which owns the commit. That is what makes the answers here identical to the
endpoint's rather than merely similar.

**No parameter sets "now".** The service takes one so a test can stand either
side of a local midnight; exposing it would make the future-dated rule opt-out
for any caller, so it is absent here and the transport rejects it as an unknown
argument.
"""

import json
from typing import Annotated, Any

from core_shared.models.tasks import Task
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


def register_task_tools(mcp: FastMCP[None]) -> None:
    """Register task MCP tools with the FastMCP server."""
    mcp.add_tool(create_task)

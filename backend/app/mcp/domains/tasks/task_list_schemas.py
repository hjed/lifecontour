"""Task list MCP response schemas.

Each tool returns one of these, which fastmcp publishes as the tool's
``outputSchema``. ``icon`` is typed :class:`TaskIcon`, so the fixed key set is in
the schema an agent reads rather than only in prose.
"""

from typing import Literal

from core_shared.models.tasks import TaskIcon
from pydantic import BaseModel, Field

from app.mcp.domains.tasks.schemas import TaskHistoryEntryMCP, TaskReadMCP


class TaskListMCP(BaseModel):
    """A task list, as every list-returning tool answers."""

    id: int
    name: str
    icon: TaskIcon | None = Field(description="Icon key from the fixed set, or null")
    position: int = Field(
        description="Place among the user's lists, 0 at the top; lists may share one"
    )
    archived: bool = Field(
        description="Whether the list is archived (read-only until unarchived)"
    )
    archived_at: str | None = Field(
        description="ISO 8601 instant the list was archived, or null"
    )
    associated_journal_id: int | None = Field(
        description="The journal the list is associated with, or null"
    )
    created_at: str | None = Field(description="ISO 8601 instant")
    updated_at: str | None = Field(description="ISO 8601 instant")


class TaskListDeletedResponse(BaseModel):
    """A deleted list, and what became of its tasks."""

    deleted: Literal[True]
    task_list_id: int
    deleted_task_ids: list[int] = Field(
        description="Tasks deleted with the list, open and completed alike"
    )
    kept_task_ids: list[int] = Field(
        description=(
            "Tasks that held both a creating and a due journal and so were kept, "
            "now journal-only and on no list"
        )
    )


class TaskListsMCP(BaseModel):
    """The user's active lists in their new order, after a move."""

    lists: list[TaskListMCP]


class TaskListHistoryResponse(BaseModel):
    """A page of a task list's change history, newest first."""

    task_list_id: int
    total_count: int
    page: int
    limit: int
    entries: list[TaskHistoryEntryMCP]


class TaskListSummaryMCP(TaskListMCP):
    """A task list as the listing answers it, with its open-task count."""

    open_task_count: int = Field(
        description="How many of the list's tasks are not done; 0 for none"
    )


class TaskListSummariesMCP(BaseModel):
    """The user's task lists for one listing, each with its count."""

    lists: list[TaskListSummaryMCP]
    total_count: int = Field(
        description="How many lists the listing matches, across every page"
    )
    paged: bool = Field(
        description=(
            "Whether lists was cut to page and limit. When false every "
            "matching list is here."
        )
    )


class OpenTaskListTasksMCP(BaseModel):
    """A list's open tasks, in the user's manual order."""

    total_count: int = Field(description="How many open tasks the list holds")
    paged: bool = Field(
        description=(
            "Whether this section was cut to page and limit (page_open_tasks). "
            "When false every open task is here."
        )
    )
    tasks: list[TaskReadMCP]


class CompletedTaskListTasksMCP(BaseModel):
    """One page of a list's done and cancelled tasks, most recently closed first."""

    total_count: int = Field(
        description="How many done and cancelled tasks the list holds, across pages"
    )
    tasks: list[TaskReadMCP]


class TaskListTasksMCP(BaseModel):
    """A task list with its tasks."""

    task_list: TaskListMCP
    page: int = Field(description="The 1-based page every paged section is on")
    limit: int = Field(description="The page size every paged section uses")
    open_tasks: OpenTaskListTasksMCP
    completed: CompletedTaskListTasksMCP | None = Field(
        description="The completed page, or null when include_completed was false"
    )

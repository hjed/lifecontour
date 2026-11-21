"""Task list MCP response schemas.

Each tool returns one of these, which fastmcp publishes as the tool's
``outputSchema``. ``icon`` is typed :class:`TaskIcon`, so the fixed key set is in
the schema an agent reads rather than only in prose.
"""

from core_shared.models.tasks import TaskIcon
from pydantic import BaseModel, Field

from app.mcp.domains.tasks.schemas import TaskHistoryEntryMCP


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
    created_at: str | None = Field(description="ISO 8601 instant")
    updated_at: str | None = Field(description="ISO 8601 instant")


class TaskListsMCP(BaseModel):
    """The user's task lists in their order: one archived filter's, or the
    active lists after a move."""

    lists: list[TaskListMCP]


class TaskListHistoryResponse(BaseModel):
    """A page of a task list's change history, newest first."""

    task_list_id: int
    total_count: int
    page: int
    limit: int
    entries: list[TaskHistoryEntryMCP]

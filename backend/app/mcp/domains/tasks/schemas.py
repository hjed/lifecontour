"""
Tasks domain MCP response schemas.

Each tool returns one of these, which fastmcp publishes as the tool's
``outputSchema`` and sends as ``structuredContent``. The read shapes are a
superset of the write shape (``TaskMCP``), so an agent that learned a task from
``create_task`` reads it back with the same fields.
"""

import datetime
from typing import Literal

from core_shared.models.tasks import LapseReason, TaskLinkRole, TaskStatus
from pydantic import BaseModel, Field


class TaskMCP(BaseModel):
    """A task, as every task-returning write tool answers."""

    id: int
    text: str
    status: TaskStatus
    creating_journal_id: int = Field(description="The journal the task arose in")
    due_journal_id: int = Field(description="The journal the task is due in")
    intermediate_journal_ids: list[int] = Field(
        description="Journals the task has passed through since it was created"
    )
    created_at: str | None = Field(description="ISO 8601 instant")
    updated_at: str | None = Field(description="ISO 8601 instant")


class TaskContactLinkResponse(BaseModel):
    """The outcome of linking or unlinking a task and a contact."""

    task_id: int
    contact_id: int
    linked: bool = Field(description="Whether the two are linked now")
    changed: bool = Field(
        description="Whether this call changed anything (false for a no-op)"
    )


class TaskJournalLinkResponse(BaseModel):
    """The outcome of attaching or detaching an intermediate journal."""

    task_id: int
    journal_id: int
    attached: bool = Field(description="Whether the journal is attached now")
    changed: bool = Field(
        description="Whether this call changed anything (false for a no-op)"
    )


class TaskDeletedResponse(BaseModel):
    """A deleted task."""

    deleted: Literal[True]
    task_id: int


class TaskJournalRefMCP(BaseModel):
    """One of a task's journals."""

    id: int
    title: str
    date: datetime.date = Field(description="The journal's date in the user's timezone")
    cancelled: bool = Field(description="Whether the journal is a cancelled event")


class TaskContactMCP(BaseModel):
    """A contact linked to a task."""

    id: int
    display_name: str
    photo_url: str | None


class TaskReadMCP(TaskMCP):
    """A task as the read tools answer: its journals, contacts and lapse."""

    creating_journal: TaskJournalRefMCP = Field(
        description="The creating journal: the one the task arose in"
    )
    due_journal: TaskJournalRefMCP = Field(
        description="The due journal: the one the task is due in"
    )
    intermediate_journals: list[TaskJournalRefMCP] = Field(
        description="Journals the task has passed through"
    )
    contacts: list[TaskContactMCP]
    lapsed: bool = Field(
        description="Still not done, and its due journal has passed or was cancelled"
    )
    lapse_reason: LapseReason | None = Field(
        description="Why the task lapsed, or null when it has not"
    )


class GroupedTaskMCP(TaskReadMCP):
    """A task under one of a journal's role groups."""

    link_roles: list[TaskLinkRole] = Field(
        description="Every group this task appears in"
    )


class TaskGroupsMCP(BaseModel):
    """A journal's tasks by the role each link holds."""

    due: list[GroupedTaskMCP] = Field(description="Tasks due in this journal")
    created: list[GroupedTaskMCP] = Field(description="Tasks that arose here")
    mentioned: list[GroupedTaskMCP] = Field(
        description="Tasks this journal is an intermediate link of"
    )


class JournalTasksResponse(BaseModel):
    """One journal's tasks, nested under the role each link holds."""

    journal_id: int
    groups: TaskGroupsMCP


class UpcomingWindowMCP(BaseModel):
    """The days an upcoming-tasks answer covers, in the user's timezone."""

    start_date: datetime.date
    end_date: datetime.date
    days_ahead: int


class UpcomingTasksResponse(BaseModel):
    """Not-done tasks due within the window."""

    window: UpcomingWindowMCP
    total: int
    tasks: list[TaskReadMCP]


class TaskHistoryEntryMCP(BaseModel):
    """One recorded change to a task."""

    field_name: str
    old_value: str | None
    new_value: str | None
    changed_by: str | None
    source: str = Field(description="Where the change came from, e.g. 'mcp'")
    created_at: str | None = Field(description="ISO 8601 instant")


class TaskHistoryResponse(BaseModel):
    """A page of a task's change history, newest first."""

    task_id: int
    total_count: int
    page: int
    limit: int
    entries: list[TaskHistoryEntryMCP]

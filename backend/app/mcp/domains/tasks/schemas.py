"""
Tasks domain MCP response schemas.

Each tool returns one of these, which fastmcp publishes as the tool's
``outputSchema`` and sends as ``structuredContent``. The read shapes are a
superset of the write shape (``TaskMCP``), so an agent that learned a task from
``create_task`` reads it back with the same fields.
"""

import datetime
from typing import Literal

from core_shared.models.tasks import LapseReason, TaskIcon, TaskLinkRole, TaskStatus
from pydantic import BaseModel, Field

from app.core.history.models import FieldHistoryEntry


class TaskMCP(BaseModel):
    """A task, as every task-returning write tool answers."""

    id: int
    text: str
    status: TaskStatus
    creating_journal_id: int | None = Field(
        description=(
            "The journal the task arose in. Null for a task on a list that arose "
            "in no journal; a task with no list always has one."
        )
    )
    due_journal_id: int | None = Field(
        description=(
            "The journal the task is due in. Null for a task on a list with no "
            "due journal; a task with no list always has one."
        )
    )
    intermediate_journal_ids: list[int] = Field(
        description="Journals the task has passed through since it was created"
    )
    task_list_id: int | None = Field(
        description=(
            "The list the task is on, or null for a journal-only task. A task on "
            "a list never lapses; past its date it is overdue instead, which the "
            "read tools' overdue field reports."
        )
    )
    due_date: datetime.date | None = Field(
        description=(
            "A plain due date in the user's timezone, or null. Only a task on a "
            "list has one, and never beside a due journal."
        )
    )
    flagged: bool = Field(description="Whether the task is flagged as one that matters")
    icon: TaskIcon | None = Field(description="Icon key from the fixed set, or null")
    created_at: str | None = Field(description="ISO 8601 instant")
    updated_at: str | None = Field(description="ISO 8601 instant")


class TaskListOrderMCP(BaseModel):
    """A list's open tasks in their manual order, after a reorder."""

    task_list_id: int
    open_tasks: list[TaskMCP] = Field(
        description="Every open task on the list, top first; closed tasks are left out"
    )


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


class TaskListRefMCP(BaseModel):
    """The list a task is on."""

    id: int
    name: str
    icon: TaskIcon | None = Field(description="Icon key from the fixed set, or null")
    archived: bool = Field(
        description="Whether the list is archived; its tasks are then read-only"
    )


class TaskContactMCP(BaseModel):
    """A contact linked to a task."""

    id: int
    display_name: str
    photo_url: str | None


class TaskReadMCP(TaskMCP):
    """A task as the read tools answer: its journals, contacts and lapse."""

    creating_journal: TaskJournalRefMCP | None = Field(
        description=(
            "The creating journal: the one the task arose in. Null exactly when "
            "creating_journal_id is."
        )
    )
    due_journal: TaskJournalRefMCP | None = Field(
        description=(
            "The due journal: the one the task is due in. Null exactly when "
            "due_journal_id is."
        )
    )
    intermediate_journals: list[TaskJournalRefMCP] = Field(
        description="Journals the task has passed through"
    )
    contacts: list[TaskContactMCP]
    lapsed: bool = Field(
        description=(
            "Still not done, and its due journal has ended (its last day is "
            "behind the user) or was cancelled. "
            "Only a task with no list lapses; a task on a list never does."
        )
    )
    lapse_reason: LapseReason | None = Field(
        description="Why the task lapsed, or null when it has not"
    )
    task_list: TaskListRefMCP | None = Field(
        description="The list the task is on; null exactly when task_list_id is"
    )
    overdue: bool = Field(
        description=(
            "A task on a list that is still not done and past its date: after "
            "its due date, or once its due journal's last day has ended. A "
            "cancelled due journal leaves it undated. Always false for a task "
            "with no list, which lapses instead."
        )
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

    @classmethod
    def from_entry(cls, entry: FieldHistoryEntry) -> TaskHistoryEntryMCP:
        """One change, as the task and task-list history tools hand it over.

        ``source`` is the ``Provenance`` value rather than the enum, and
        ``created_at`` an ISO instant — the repository already returns one, so
        this only has to cope with the ``datetime`` a caller constructing an
        entry by hand would pass. Both are the shape the REST endpoints send.
        """
        created_at = entry.created_at
        return cls(
            field_name=entry.field_name,
            old_value=entry.old_value,
            new_value=entry.new_value,
            changed_by=entry.changed_by,
            source=entry.source.value,
            created_at=(
                created_at.isoformat()
                if isinstance(created_at, datetime.datetime)
                else created_at
            ),
        )


class TaskHistoryResponse(BaseModel):
    """A page of a task's change history, newest first."""

    task_id: int
    total_count: int
    page: int
    limit: int
    entries: list[TaskHistoryEntryMCP]

"""Rendering tasks for the MCP tools: the write answer and the read answer.

Shared by the task tools and the task-list tools, which both hand back tasks.
It lives in its own module because ``tools.py`` imports ``task_list_tools.py``
to register its tools, so the list tools cannot import from ``tools.py`` back.
"""

from core_shared.models.tasks import Task, TaskJournalRef, TaskListRef, TaskReadModel

from app.mcp.domains.tasks.schemas import (
    TaskContactMCP,
    TaskJournalRefMCP,
    TaskListRefMCP,
    TaskMCP,
    TaskReadMCP,
)


def task_mcp_fields(task: Task, intermediate_journal_ids: list[int]) -> TaskMCP:
    """The answer every task-returning tool gives.

    ``intermediate_journal_ids`` is passed in rather than read here, and every
    caller supplies one, so a task looks the same whichever tool produced it —
    ``get_task`` included, which builds on these fields rather than beside them.
    Before that tool existed a trail left out of a write's answer was
    *unreachable* rather than merely inconvenient; it is now readable directly,
    and the field stays on every answer so an agent needs one shape, not two.
    """
    if task.id is None:
        raise ValueError("A task answer needs a persisted task")
    return TaskMCP(
        id=task.id,
        text=task.text,
        status=task.status,
        # Null for an anchor a list task does not have.
        creating_journal_id=task.creating_journal_id,
        due_journal_id=task.due_journal_id,
        intermediate_journal_ids=intermediate_journal_ids,
        task_list_id=task.task_list_id,
        due_date=task.due_date,
        flagged=task.flagged,
        icon=task.icon,
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
    )


def _journal_ref(ref: TaskJournalRef) -> TaskJournalRefMCP:
    """One of a task's journals, as a read tool hands it over.

    The date is a **date**, already resolved in the user's timezone — the same
    one the lapse rule judged the task against. Sending an instant would invite
    an agent to re-derive the day in UTC and disagree with the verdict beside it.
    """
    return TaskJournalRefMCP(
        id=ref.id, title=ref.title, date=ref.date, cancelled=ref.cancelled
    )


def _optional_journal_ref(ref: TaskJournalRef | None) -> TaskJournalRefMCP | None:
    """An anchor's journal, or null for an anchor a list task does not have."""
    return None if ref is None else _journal_ref(ref)


def _list_ref(ref: TaskListRef | None) -> TaskListRefMCP | None:
    """The task's list, or null for a journal-only task."""
    if ref is None:
        return None
    return TaskListRefMCP(
        id=ref.id, name=ref.name, icon=ref.icon, archived=ref.archived
    )


def task_read_mcp(model: TaskReadModel) -> TaskReadMCP:
    """A task as the read tools return it.

    A **superset** of what the write tools return: every field ``task_mcp_fields``
    carries is here, including ``intermediate_journal_ids``, with the resolved
    journals, the contacts and the lapse added. An agent that learned the shape
    from ``create_task`` does not have to learn a second one to read the task
    back.
    """
    return TaskReadMCP(
        **task_mcp_fields(
            model.task, [ref.id for ref in model.intermediate_journals]
        ).model_dump(),
        creating_journal=_optional_journal_ref(model.creating_journal),
        due_journal=_optional_journal_ref(model.due_journal),
        intermediate_journals=[
            _journal_ref(ref) for ref in model.intermediate_journals
        ],
        contacts=[
            TaskContactMCP(
                id=contact.id,
                display_name=contact.display_name,
                photo_url=contact.photo_url,
            )
            for contact in model.contacts
        ],
        # Taken from the model rather than recomputed from the reason, so the
        # flag and the reason can never disagree about the same task.
        lapsed=model.lapsed,
        lapse_reason=model.lapse_reason,
        task_list=_list_ref(model.task_list),
        overdue=model.overdue,
    )

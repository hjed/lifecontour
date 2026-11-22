"""Where ``create_task`` puts a task, decided from the arguments it was given.

One tool creates a task either **in journals** — the journal it arose in and the
future journal it is due in, as it always has — or **on a list**, optionally
with a due date or a due journal, never both. A JSON schema cannot say "these
two, or that one", so this decides, and refuses any other mix by naming the
argument at fault. It reads
nothing and writes nothing, so a refusal costs no query.

The two results are separate types so the tool hands each service method only
ids it knows are present: mypy rejects a branch that passes an optional journal
id on.
"""

import datetime
from dataclasses import dataclass

from core_shared.models.tasks import TaskValidationError


@dataclass(frozen=True, kw_only=True)
class InJournals:
    """A task anchored to the journal it arose in and the one it is due in."""

    creating_journal_id: int
    due_journal_id: int


@dataclass(frozen=True, kw_only=True)
class OnList:
    """A task on a list, with no creating journal.

    Undated, due on ``due_date``, or due in ``due_journal_id`` — at most one of
    the two, which :func:`resolve_create_placement` has already made sure of.
    """

    task_list_id: int
    due_date: datetime.date | None
    due_journal_id: int | None


def resolve_create_placement(
    *,
    creating_journal_id: int | None,
    due_journal_id: int | None,
    task_list_id: int | None,
    due_date: datetime.date | None,
) -> InJournals | OnList:
    """The placement the arguments describe, or a refusal naming the field.

    Raises:
        TaskValidationError: The arguments describe neither placement. Its
            ``field`` is the argument to remove or supply.
    """
    if task_list_id is not None:
        if creating_journal_id is not None:
            raise TaskValidationError(
                "creating_journal_id",
                "a task on a list has no creating journal; omit it",
            )
        if due_date is not None and due_journal_id is not None:
            # Named ``due_date``, as the task entity names it on every other
            # surface, so REST and MCP refuse the pair in the same words.
            raise TaskValidationError(
                "due_date",
                "a task on a list is due on a date or in a journal, never both; "
                "omit due_date or due_journal_id",
            )
        return OnList(
            task_list_id=task_list_id,
            due_date=due_date,
            due_journal_id=due_journal_id,
        )

    if due_date is not None:
        raise TaskValidationError(
            "due_date",
            "a due date is only for a task on a list; name the list as "
            "task_list_id, or make a task in journals due in a journal instead",
        )
    if creating_journal_id is None and due_journal_id is None:
        raise TaskValidationError(
            "task_list_id",
            "say where the task goes: a task_list_id, or both "
            "creating_journal_id and due_journal_id",
        )
    if creating_journal_id is None:
        raise TaskValidationError(
            "creating_journal_id",
            "a task in journals needs the journal it arose in as well as the one "
            "it is due in; or name a task_list_id instead",
        )
    if due_journal_id is None:
        raise TaskValidationError(
            "due_journal_id",
            "a task in journals needs the journal it is due in as well as the one "
            "it arose in; or name a task_list_id instead",
        )
    return InJournals(
        creating_journal_id=creating_journal_id, due_journal_id=due_journal_id
    )

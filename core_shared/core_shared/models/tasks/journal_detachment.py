"""What a journal delete did to one list task's links.

A journal delete is refused while a journal-only task is anchored to it, but a
task on a list never blocks it: the specification has the list task lose its
link to the journal instead — creating, due or intermediate — and become
undated if it was due there. That is three set-based statements over two tables
(a locked read, a delete of the mentions, an update of the anchors), performed
from the journal domain, and this type is how the tasks domain learns
what they did to each task so the task's own history can say so.

The counterpart of :class:`~core_shared.models.tasks.TaskJournalRepointing`,
and simpler: a delete moves nothing *to* anything, so each fact is one link
the task held on the deleted journal and no longer does.

Lives beside the ``Task`` entity for the reason that one does: it is a value
object a repository port returns, so the port and its callers both need it
without either importing the other's module.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class TaskJournalDetachment:
    """One list task's share of a journal delete.

    Keyword-only because three booleans in a row are exactly the arguments a
    caller swaps without anything noticing.

    Args:
        task_id: The task that lost its links.
        user_id: Its owner. Carried because the event needs it and the delete —
            which reached this task through a journal — never read the task row.
        creating_anchor_removed: The deleted journal was the task's creating
            journal; the task now has none.
        due_anchor_removed: The deleted journal was the task's due journal; the
            task is now undated (a list task with a due journal has no due date,
            by invariant 4).
        link_removed: The task held an intermediate link to the deleted journal.

    Raises:
        ValueError: The summary records no change, which means a ``RETURNING``
            set was misread; an event built from it would publish an empty
            ``changed_fields`` that projects no history at all.
    """

    task_id: int
    user_id: str
    creating_anchor_removed: bool = False
    due_anchor_removed: bool = False
    link_removed: bool = False

    def __post_init__(self) -> None:
        if not (
            self.creating_anchor_removed or self.due_anchor_removed or self.link_removed
        ):
            raise ValueError(
                f"Detachment for task {self.task_id} records no change; a journal "
                "delete only reports a list task it actually detached."
            )

"""What a journal merge did to one task's links.

A merge re-points every link a task holds on the journal being absorbed — the
creating anchor, the due anchor and intermediate links — onto the survivor, and
deletes the ones the move made duplicate or redundant. That is four set-based
statements over two tables, performed from the journal domain, and until this
type existed the tasks domain had no way to know any of it happened.

**The facts are per journal, not per statement.** The repository runs four
statements, but "collapsed as a duplicate" and "moved and then dropped as
redundant" leave the task in the same place — no link to either journal — and a
history that distinguished them would be describing the SQL rather than the
task. What a reader needs is where the task's links are now compared with where
they were, so the fields name the two journals and the direction:
:attr:`source_link_removed`, :attr:`target_link_added`,
:attr:`target_link_removed`.

Lives beside :class:`~core_shared.models.tasks.entities.Task` for the same
reason ``BlockingTask`` lives beside ``Journal``: it is a value object a
repository port returns, so both the port and its callers need it without either
importing the other's module.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskJournalRepointing:
    """One task's share of a journal merge.

    Args:
        task_id: The task whose links moved.
        user_id: Its owner. Carried because the event needs it and the merge —
            which reached this task through a journal — never read the task row.
        creating_anchor_moved: The absorbed journal was the task's creating
            journal and the survivor now is. The specification calls this field
            set once and never changed; a merge is its one legitimate exception.
        due_anchor_moved: The absorbed journal was the task's due journal and the
            survivor now is.
        source_link_removed: The task held an intermediate link to the absorbed
            journal and no longer does — because the link moved, or because the
            task was already linked to the survivor and the duplicate was
            collapsed. Always true of a task that had one, since the absorbed
            journal is about to be deleted.
        target_link_added: The task now holds an intermediate link to the
            survivor that it did not hold before.
        target_link_removed: The task held an intermediate link to the survivor
            before the merge and no longer does, because an anchor moved onto
            that journal and the anchor role says the same thing more strongly.

    Raises:
        ValueError: The summary records no change, or records the survivor's
            link as both gained and lost. Both mean the assembly step read its
            statements wrongly, and both would otherwise reach a user's history
            as a quiet fiction rather than as a failure.
    """

    task_id: int
    user_id: str
    creating_anchor_moved: bool = False
    due_anchor_moved: bool = False
    source_link_removed: bool = False
    target_link_added: bool = False
    target_link_removed: bool = False

    def __post_init__(self) -> None:
        if not any(
            (
                self.creating_anchor_moved,
                self.due_anchor_moved,
                self.source_link_removed,
                self.target_link_added,
                self.target_link_removed,
            )
        ):
            raise ValueError(
                f"Repointing for task {self.task_id} records no change; a merge "
                "only reports a task it actually moved."
            )
        if self.target_link_added and self.target_link_removed:
            raise ValueError(
                f"Repointing for task {self.task_id} has the surviving journal's "
                "link both gained and lost; a task can only gain that link by "
                "having had none there to lose."
            )

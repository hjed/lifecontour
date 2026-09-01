"""What a contact merge did to one task's people.

A merge moves every link a task holds on the contact being absorbed onto the
survivor, and collapses the link that move would duplicate. That is two
set-based statements over one table, performed from the contacts domain, and
until this type existed the tasks domain had no way to know any of it happened —
in fact nothing happened at all: ``task_contacts.contact_id`` is
``ON DELETE CASCADE``, so the merge's final delete destroyed the links instead
of moving them.

**The pair of facts is asymmetric**, unlike :class:`TaskJournalRepointing`'s
five. Every task the repository reports lost its link to the absorbed contact —
that is what being reported means, since the only reason a task is reported is
that it held one. What varies is whether it *gained* a link on the survivor, and
it did not when it was already linked to both and the duplicate was collapsed.
So the departure is implicit and the arrival is the field.

Lives beside :class:`TaskJournalRepointing` for the same reason that one lives
beside ``Task``: it is a value object a repository port returns, so both the
port and its callers need it without either importing the other's module.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskContactRepointing:
    """One task's share of a contact merge.

    Args:
        task_id: The task whose links moved.
        user_id: Its owner. Carried because the event needs it and the merge —
            which reached this task through a contact — never read the task row.
            It could not have supplied it in any case: ``contacts`` has no owner
            column, so the contacts domain has no acting user to pass down.
        survivor_link_added: The task now references the survivor and did not
            before. ``False`` means it already did, and the absorbed contact's
            link was collapsed into it rather than moved onto it — the task lost
            a link and gained nothing.

    Raises:
        ValueError: The summary names no owner. Unlike the journal repointing
            there is no "records no change" case to refuse — the departure is
            unconditional — so this is the one way the assembly step can hand
            over a summary that reaches a user's history as a quiet fiction: an
            empty owner is not a failure downstream, it is a task filed under
            nobody.
    """

    task_id: int
    user_id: str
    survivor_link_added: bool

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError(
                f"Repointing for task {self.task_id} names no owner; a task's "
                "owner has to travel on the event because a task-scoped history "
                "read has no row left to join back to."
            )

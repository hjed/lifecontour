"""SQL implementation of :class:`TaskContactRepository`.

Two statements, and the order is the design — the same shape the journal merge's
re-point uses over its two tables, for the same reason: ``ON CONFLICT`` is
unavailable on an ``UPDATE``, so a duplicate has to be *gone* before the
re-point runs rather than resolved while it does. That lesson is recorded in
``JournalTagRepository.merge_into`` and again in ``SqlTaskAnchorRepository``;
this is its third appearance and the cheapest, because ``task_contacts`` has one
composite key and no roles.

**No pre-read.** The anchor repository needs one because a journal's *role* on a
task is unreadable once both anchor columns hold the survivor's id. Nothing here
is lost that way: which statement touched a task is exactly the fact the summary
carries, and both statements can say so with ``RETURNING``. So the two
``RETURNING`` sets **are** the answer rather than a check on a snapshot, and the
concurrency caveat ``_summarise`` carries there does not arise.

The join back to ``tasks`` is for the owner id, which the merge never read
because it reached these tasks through a contact — and could not have supplied,
since ``contacts`` has no owner column at all.
"""

from core_shared.models.tasks import TaskContactRepointing
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.repositories import TaskContactRepository

# Held for the rest of the transaction, both of them, in ascending id order. See
# ``_lock_contacts`` for why the weaker modes are not enough, and why the sort
# is worthless unless the caller runs this before its other re-points.
_LOCK_CONTACT = text("SELECT 1 FROM contacts WHERE id = :contact_id FOR UPDATE")

# 1. Collapse the duplicate *before* the re-point. A task referencing both
#    contacts would otherwise make statement 2 write a second
#    ``(task_id, survivor)`` row and violate the composite primary key.
_COLLAPSE_DUPLICATE_LINKS = text("""
    DELETE FROM task_contacts AS tc
    USING tasks AS t
    WHERE tc.contact_id = :source_id
      AND t.id = tc.task_id
      AND EXISTS (
          SELECT 1
          FROM task_contacts AS held
          WHERE held.task_id = tc.task_id
            AND held.contact_id = :survivor_id
      )
    RETURNING tc.task_id, t.user_id
""")

# 2. Re-point what is left. These rows cascade on contact delete, so without
#    this they are destroyed silently rather than moved — the defect this
#    repository exists to close.
_REPOINT_CONTACT_LINKS = text("""
    UPDATE task_contacts AS tc
    SET contact_id = :survivor_id
    FROM tasks AS t
    WHERE tc.contact_id = :source_id
      AND t.id = tc.task_id
    RETURNING tc.task_id, t.user_id
""")


class SqlTaskContactRepository(TaskContactRepository):
    """Moves task contact links through a merge, over a request connection."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    async def repoint_contact_links(
        self, *, source_contact_id: int, survivor_contact_id: int
    ) -> list[TaskContactRepointing]:
        """Move every task link off the absorbed contact and onto the survivor.

        Both statements are set operations over every affected task, so a merge
        costs the same whether the person is on one task or a hundred.

        **What each statement did is reported, not inferred.** The collapse is a
        delete, whose effect is invisible once it has run; the re-point's rows
        are indistinguishable afterwards from links the task already held. Both
        therefore carry ``RETURNING``, and the two sets are disjoint by
        construction — the composite primary key means a task holds at most one
        link to the absorbed contact, so it is either collapsed or moved.
        """
        if source_contact_id == survivor_contact_id:
            # Nothing to move, and the statements below would read the rows they
            # are about to write: the collapse's EXISTS would match every link
            # against itself and delete the lot.
            return []

        await self._lock_contacts(source_contact_id, survivor_contact_id)

        params = {"source_id": source_contact_id, "survivor_id": survivor_contact_id}
        collapsed = await self._owners_by_task(_COLLAPSE_DUPLICATE_LINKS, params)
        moved = await self._owners_by_task(_REPOINT_CONTACT_LINKS, params)

        summaries = [
            TaskContactRepointing(
                task_id=task_id, user_id=user_id, survivor_link_added=False
            )
            for task_id, user_id in collapsed.items()
        ] + [
            TaskContactRepointing(
                task_id=task_id, user_id=user_id, survivor_link_added=True
            )
            for task_id, user_id in moved.items()
        ]
        # Task-id order, because the caller publishes one event per summary and
        # the outbox is read back in ``(occurred_at, id)`` order: an unordered
        # report would make one merge's history differ between runs. Nothing
        # about two ``RETURNING`` clauses promises sorted rows.
        return sorted(summaries, key=lambda summary: summary.task_id)

    async def _lock_contacts(self, source_id: int, survivor_id: int) -> None:
        """Hold both contacts for the rest of the transaction, in id order.

        **Ascending id, not source-then-survivor**, so two merges of the same
        pair in opposite directions — each choosing the other's survivor — queue
        rather than deadlock.

        **That guarantee is conditional on the caller, and the condition is
        easy to break.** A lock order only prevents a deadlock if nothing in the
        transaction has already claimed one of the pair, and *every* other
        re-point in ``merge_contacts`` writes ``contact_id = survivor_id`` into a
        table with a foreign key to ``contacts`` — which makes PostgreSQL take
        ``FOR KEY SHARE`` on the survivor's row to validate it. Two merges into
        the same survivor that had each run those first would both hold
        ``KEY SHARE`` and both then ask for ``FOR UPDATE``: a deadlock, not a
        queue. So this is called as the merge's **first** write, the same
        placement and the same reasoning as ``_lock_journals``' — and the
        placement is the load-bearing half, not the sort.

        ``FOR UPDATE`` rather than a weaker mode because inserting a task link
        takes ``FOR KEY SHARE`` on the contact row to hold its own foreign key,
        and ``FOR UPDATE`` is the weakest mode that conflicts with it. Without
        it, a concurrent ``link_contact`` could attach to the absorbed contact
        after the re-point and before the merge's delete, and the
        ``ON DELETE CASCADE`` would destroy that link — the original defect,
        reached by a narrower window.

        **A contact that does not exist is not locked**, because there is no row
        to lock; the statement matches nothing and says nothing about it. Every
        caller on the merge path has already loaded both contacts, so this is
        only worth knowing for a caller that has not.
        """
        for contact_id in sorted((source_id, survivor_id)):
            await self.conn.execute(_LOCK_CONTACT, {"contact_id": contact_id})

    async def _owners_by_task(
        self, statement: TextClause, params: dict[str, int]
    ) -> dict[int, str]:
        """Run a statement and read its ``RETURNING`` as ``{task_id: user_id}``."""
        result = await self.conn.execute(statement, params)
        return {int(row.task_id): str(row.user_id) for row in result.fetchall()}

"""SQL implementation of :class:`TaskAnchorRepository`.

**The delete guard's read.** One statement answers the whole question. Both
anchors are matched in a single ``WHERE`` — each is indexed — and both are joined
back to ``journals`` under their own alias, because the journal a blocking task
can be actioned from is whichever anchor is *not* being deleted, and the query
cannot know which that is until the rule has run. Fetching both titles up front
is what makes the guard one query rather than one per task.

The adapter deliberately decides nothing there: which roles block, which anchor
supplies the action journal, and whether a row blocks at all are the journal
domain's rule (:mod:`core_shared.models.journals.task_anchor`), applied to each
row here.

**The merge re-point** is the other side of the same coin: where a delete is
refused because task rows point at the journal, a merge moves them instead. That
one *does* decide, because the rules are relational — a composite primary key
that must not be violated, an anchor pair that may legally collapse onto one
journal, a link that a stronger role makes redundant — and they are expressed as
set operations over the two link-bearing tables rather than as a rule applied
per row.
"""

from typing import Any

from core_shared.models.journals import BlockingTask, blocking_task_from_anchors
from core_shared.models.tasks import TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.repositories import TaskAnchorRepository

# ORDER BY t.id keeps the enumeration in the failure message stable: without it
# PostgreSQL is free to return the rows in whatever order the plan produces.
_FIND_ANCHORED = text("""
    SELECT
        t.id,
        t.text,
        t.status,
        t.creating_journal_id,
        creating.title AS creating_journal_title,
        t.due_journal_id,
        due.title AS due_journal_title
    FROM tasks t
    JOIN journals creating ON creating.id = t.creating_journal_id
    JOIN journals due ON due.id = t.due_journal_id
    WHERE t.creating_journal_id = :journal_id OR t.due_journal_id = :journal_id
    ORDER BY t.id
""")

# The merge re-point, in the order it has to run. See ``repoint_journal_links``
# and ``_lock_journals`` for why each exists and why the order is not free.
_LOCK_JOURNAL = text("SELECT 1 FROM journals WHERE id = :journal_id FOR UPDATE")

_TASK_IDS_REFERENCING = text("""
    SELECT id FROM tasks
    WHERE creating_journal_id = :journal_id OR due_journal_id = :journal_id
    UNION
    SELECT task_id FROM task_intermediate_journals
    WHERE journal_id = :journal_id
""")

_COLLAPSE_DUPLICATE_LINKS = text("""
    DELETE FROM task_intermediate_journals src
    WHERE src.journal_id = :source_id
    AND EXISTS (
        SELECT 1 FROM task_intermediate_journals tgt
        WHERE tgt.task_id = src.task_id
        AND tgt.journal_id = :target_id
    )
""")

_REPOINT_INTERMEDIATE_LINKS = text("""
    UPDATE task_intermediate_journals
    SET journal_id = :target_id
    WHERE journal_id = :source_id
""")

_REPOINT_ANCHORS = text("""
    UPDATE tasks
    SET creating_journal_id = CASE
            WHEN creating_journal_id = :source_id THEN :target_id
            ELSE creating_journal_id END,
        due_journal_id = CASE
            WHEN due_journal_id = :source_id THEN :target_id
            ELSE due_journal_id END,
        updated_at = now()
    WHERE creating_journal_id = :source_id
       OR due_journal_id = :source_id
""")

_DROP_REDUNDANT_LINKS = text("""
    DELETE FROM task_intermediate_journals tij
    USING tasks t
    WHERE tij.task_id = t.id
    AND tij.task_id = ANY(:affected_task_ids)
    AND tij.journal_id = :target_id
    AND (t.creating_journal_id = :target_id
         OR t.due_journal_id = :target_id)
""")


class SqlTaskAnchorRepository(TaskAnchorRepository):
    """SQL implementation of the task anchor repository."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    async def find_tasks_anchored_to_journal(
        self, journal_id: int
    ) -> list[BlockingTask]:
        """Find every task this journal is the creating or due journal of."""
        result = await self.conn.execute(_FIND_ANCHORED, {"journal_id": journal_id})
        blockers = (
            self._to_blocking_task(row, journal_id) for row in result.fetchall()
        )
        return [blocker for blocker in blockers if blocker is not None]

    @staticmethod
    def _to_blocking_task(row: Any, journal_id: int) -> BlockingTask | None:
        """Apply the journal domain's rule to one row."""
        return blocking_task_from_anchors(
            deleted_journal_id=journal_id,
            task_id=row.id,
            text=row.text,
            status=TaskStatus(row.status),
            creating_journal_id=row.creating_journal_id,
            creating_journal_title=row.creating_journal_title,
            due_journal_id=row.due_journal_id,
            due_journal_title=row.due_journal_title,
        )

    async def repoint_journal_links(
        self, *, source_journal_id: int, target_journal_id: int
    ) -> None:
        """Move every task link off the absorbed journal and onto the survivor.

        Four statements, and the order is the design. Each one is a set
        operation over every affected task, so a merge costs the same whether
        one task is anchored to the source or a hundred.

        The affected tasks are read *first*, before anything moves, because the
        last statement needs to know which tasks this merge touched and by then
        every reference to the source is gone. That read is taken under locks on
        both journals, for the reasons ``_lock_journals`` explains.
        """
        if source_journal_id == target_journal_id:
            # Nothing to move, and every statement below would read the rows it
            # is about to write: statement 1's EXISTS would match each
            # intermediate link against itself and delete the lot.
            return

        params = {"source_id": source_journal_id, "target_id": target_journal_id}

        await self._lock_journals(source_journal_id, target_journal_id)

        affected_task_ids = await self._task_ids_referencing(source_journal_id)
        if not affected_task_ids:
            return

        # 1. Collapse duplicates *before* the re-point. A task linked to both
        #    journals as an intermediate would otherwise make statement 2 write a
        #    second (task_id, target_id) row and violate the composite primary
        #    key. ON CONFLICT cannot rescue an UPDATE, so the duplicate has to be
        #    gone before the UPDATE runs — the ITER17-001 Phase 4 lesson, and the
        #    same shape as JournalTagRepository.merge_into.
        await self.conn.execute(_COLLAPSE_DUPLICATE_LINKS, params)

        # 2. Re-point what is left. These rows cascade on journal delete, so
        #    without this they would be destroyed silently rather than refused.
        await self.conn.execute(_REPOINT_INTERMEDIATE_LINKS, params)

        # 3. Re-point both anchors at once. A task anchored to the source in
        #    both roles ends up with the survivor in both, which the
        #    specification permits. status and text are absent from the SET list
        #    because a merge is not allowed to change either.
        await self.conn.execute(_REPOINT_ANCHORS, params)

        # 4. Drop the intermediate link that has become redundant with one of
        #    the task's own anchors — "the task was mentioned here" said in a
        #    weaker form than the anchor already says it. Runs last because it
        #    reads the anchors statement 3 has just moved, and it covers both
        #    directions: an intermediate link absorbed into an anchor, and an
        #    anchor absorbed into a journal already linked as intermediate.
        #
        #    Restricted to the tasks this merge actually touched. A task can
        #    hold an intermediate link to one of its own anchors without a merge
        #    being involved — retargeting keeps the previous due journal as an
        #    intermediate link, so retargeting *back* onto it produces exactly
        #    that shape — and destroying a bystander's record of where it has
        #    been is not this operation's business.
        await self.conn.execute(
            _DROP_REDUNDANT_LINKS, params | {"affected_task_ids": affected_task_ids}
        )

    async def _lock_journals(
        self, source_journal_id: int, target_journal_id: int
    ) -> None:
        """Hold both journals for the rest of the transaction.

        Two different races, one lock each, and both end the same way — a merge
        failing because of task rows, which the specification says can never
        happen.

        **The source, against a new anchor.** Re-pointing is a read followed by
        writes followed, in the caller, by a journal delete. Without the lock a
        concurrent ``create_task`` can anchor a task to the absorbed journal
        inside that window: it is absent from the snapshot, so nothing moves it,
        and the delete then fails on the ``RESTRICT`` foreign key.

        **The target, against a second merge.** Two merges absorbing *different*
        journals into the *same* survivor can both clear statement 1 before
        either has written its ``(task_id, target)`` link, and the second
        ``UPDATE`` then violates the composite primary key. Today the merge
        service happens to serialise them anyway — it writes the target journal
        row before it gets here — but that is a property of one caller, not of
        this method, and a caller that stopped writing the target would silently
        reopen the race.

        ``FOR UPDATE`` is the weakest mode that closes the first: inserting a
        task row takes ``FOR KEY SHARE`` on each anchor journal to hold its own
        foreign key, and ``FOR UPDATE`` is the weakest mode conflicting with
        that. So a concurrent creation waits for the merge and then fails its
        own anchor check against a journal that is genuinely gone — the right
        answer, and the same shape as the ``FOR KEY SHARE`` in
        ``SqlTaskRepository._require_task_owned``.

        **Locked in ascending id order**, one statement each rather than one
        ordered statement, because ``FOR UPDATE`` does not promise to lock in
        the order a query returns. Two merges therefore queue instead of
        deadlocking — but only because the caller re-points *before* it writes
        either journal row. A merge that took its target's lock first, as
        ``journal_repo.save(target)`` does, and only then came here would have
        acquired the pair out of order, and two merges in opposite directions
        (A into B, B into A) would deadlock on each other. That is why the call
        is the first write in ``merge_journals`` rather than the last.

        **A deadlock against task *creation* remains possible, and no lock order
        can close it.** Inserting a task takes its ``FOR KEY SHARE`` locks in
        foreign-key declaration order — creating anchor, then due anchor — which
        is the task's own pairing and not an ordering of ids. A task created
        with its creating anchor on the survivor and its due anchor on the
        absorbed journal therefore grabs the higher id first, against this
        method's lower-id-first. PostgreSQL aborts one side. That is a strictly
        smaller window than the one the lock closes — before it, *any*
        concurrent creation anchoring to the absorbed journal made the merge
        fail — but it is not zero, and calling it impossible would be wrong.

        As with the deleted-task cases in the task repository's own tests, none
        of the concurrent forms can be staged against the integration fixture —
        one savepoint-bound transaction means a second connection cannot see the
        journals involved — so this is reasoned about rather than pinned by a
        test.
        """
        for journal_id in sorted((source_journal_id, target_journal_id)):
            await self.conn.execute(_LOCK_JOURNAL, {"journal_id": journal_id})

    async def _task_ids_referencing(self, journal_id: int) -> list[int]:
        """The ids of every task that names this journal in any of the three roles.

        Read before a re-point moves anything, because afterwards there is
        nothing left pointing at the journal to identify them by.
        """
        result = await self.conn.execute(
            _TASK_IDS_REFERENCING, {"journal_id": journal_id}
        )
        return [int(row[0]) for row in result.fetchall()]

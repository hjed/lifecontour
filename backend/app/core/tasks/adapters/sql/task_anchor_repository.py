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

from dataclasses import dataclass
from typing import Any

from core_shared.models.journals import BlockingTask, blocking_task_from_anchors
from core_shared.models.tasks import TaskJournalRepointing, TaskStatus
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.repositories import TaskAnchorRepository


@dataclass(frozen=True)
class _AffectedTask:
    """A row of the pre-read: one task the merge is about to move.

    Distinct from :class:`~core_shared.models.tasks.TaskJournalRepointing`
    because it is only half the answer — what the *anchors* did — recorded
    before the three link statements have run and said what they did.
    """

    task_id: int
    user_id: str
    creating_anchor_moved: bool
    due_anchor_moved: bool


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

# The affected tasks, with the anchor roles the source journal holds on each.
#
# The roles have to be read *here* rather than returned by the update: both
# anchors end up holding the survivor's id, so afterwards nothing in the row says
# which of them moved. The union finds every task that names the journal in any
# of the three roles — including one that only mentions it, which has no anchor
# role at all — and the join back to ``tasks`` supplies the owner, which the
# merge never read because it reached these tasks through a journal.
_TASKS_REFERENCING = text("""
    WITH referencing AS (
        SELECT id AS task_id FROM tasks
        WHERE creating_journal_id = :journal_id OR due_journal_id = :journal_id
        UNION
        SELECT task_id FROM task_intermediate_journals
        WHERE journal_id = :journal_id
    )
    SELECT
        t.id,
        t.user_id,
        (t.creating_journal_id = :journal_id) AS creating_anchor_moved,
        (t.due_journal_id = :journal_id) AS due_anchor_moved
    FROM tasks t
    JOIN referencing r ON r.task_id = t.id
    ORDER BY t.id
""")

# ``RETURNING`` on the three link statements, because what each one did is only
# knowable while it runs: two of them are deletes, and afterwards the rows they
# are about are gone.
_COLLAPSE_DUPLICATE_LINKS = text("""
    DELETE FROM task_intermediate_journals src
    WHERE src.journal_id = :source_id
    AND EXISTS (
        SELECT 1 FROM task_intermediate_journals tgt
        WHERE tgt.task_id = src.task_id
        AND tgt.journal_id = :target_id
    )
    RETURNING src.task_id
""")

_REPOINT_INTERMEDIATE_LINKS = text("""
    UPDATE task_intermediate_journals
    SET journal_id = :target_id
    WHERE journal_id = :source_id
    RETURNING task_id
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
    RETURNING tij.task_id
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
    ) -> list[TaskJournalRepointing]:
        """Move every task link off the absorbed journal and onto the survivor.

        Four statements, and the order is the design. Each one is a set
        operation over every affected task, so a merge costs the same whether
        one task is anchored to the source or a hundred.

        The affected tasks are read *first*, before anything moves, for two
        reasons that happen to want the same read: the last statement needs to
        know which tasks this merge touched, and by then every reference to the
        source is gone; and the anchor **roles** are only legible before the
        update, since afterwards both columns hold the survivor's id. That read
        is taken under locks on both journals, for the reasons ``_lock_journals``
        explains.

        **What each statement did is reported, not inferred.** Three of them
        carry ``RETURNING``, because two are deletes whose effect is invisible
        once they have run and the third's rows are indistinguishable from links
        the task already held. The per-task summary is assembled from those
        three sets and the pre-read's roles; see :meth:`_summarise` for how the
        two link deletions are told apart.
        """
        if source_journal_id == target_journal_id:
            # Nothing to move, and every statement below would read the rows it
            # is about to write: statement 1's EXISTS would match each
            # intermediate link against itself and delete the lot.
            return []

        params = {"source_id": source_journal_id, "target_id": target_journal_id}

        await self._lock_journals(source_journal_id, target_journal_id)

        affected = await self._tasks_referencing(source_journal_id)
        if not affected:
            return []

        # 1. Collapse duplicates *before* the re-point. A task linked to both
        #    journals as an intermediate would otherwise make statement 2 write a
        #    second (task_id, target_id) row and violate the composite primary
        #    key. ON CONFLICT cannot rescue an UPDATE, so the duplicate has to be
        #    gone before the UPDATE runs — the ITER17-001 Phase 4 lesson, and the
        #    same shape as JournalTagRepository.merge_into.
        collapsed = await self._task_ids_from(_COLLAPSE_DUPLICATE_LINKS, params)

        # 2. Re-point what is left. These rows cascade on journal delete, so
        #    without this they would be destroyed silently rather than refused.
        moved = await self._task_ids_from(_REPOINT_INTERMEDIATE_LINKS, params)

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
        dropped = await self._task_ids_from(
            _DROP_REDUNDANT_LINKS,
            params | {"affected_task_ids": [row.task_id for row in affected]},
        )

        return [
            self._summarise(row, collapsed=collapsed, moved=moved, dropped=dropped)
            for row in affected
        ]

    @staticmethod
    def _summarise(
        row: _AffectedTask,
        *,
        collapsed: set[int],
        moved: set[int],
        dropped: set[int],
    ) -> TaskJournalRepointing:
        """One task's share of the merge, as net effect rather than as statements.

        The two anchors come straight off the pre-read. The three link outcomes
        are set membership, and the only subtlety is which link statement 4
        deleted:

        - a task in ``dropped`` **and** in ``moved`` had its own link re-pointed
          onto the survivor and then removed, so it gained nothing — the
          departure alone;
        - a task in ``dropped`` but not in ``moved`` had a link to the survivor
          *before* the merge, and that is the one that went.

        A collapsed duplicate is a departure with no arrival for a different
        reason — the survivor's link was already there and stays — and the two
        deliberately produce the same summary, because they leave the task in
        the same place and a history distinguishing them would be describing SQL
        rather than the task.
        """
        source_link_removed = row.task_id in collapsed or row.task_id in moved
        return TaskJournalRepointing(
            task_id=row.task_id,
            user_id=row.user_id,
            creating_anchor_moved=row.creating_anchor_moved,
            due_anchor_moved=row.due_anchor_moved,
            source_link_removed=source_link_removed,
            target_link_added=row.task_id in moved and row.task_id not in dropped,
            target_link_removed=row.task_id in dropped and row.task_id not in moved,
        )

    async def _task_ids_from(
        self, statement: TextClause, params: dict[str, Any]
    ) -> set[int]:
        """Run one of the three reporting statements and read its ``RETURNING``.

        A set rather than a list: each statement touches a given task at most
        once — the link table is keyed on ``(task_id, journal_id)`` and every one
        of them matches a single journal — and membership is all the summary
        asks.
        """
        result = await self.conn.execute(statement, params)
        return {int(row[0]) for row in result.fetchall()}

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

        **A deadlock against task *retargeting* is also possible, and unlike the
        one above it can be closed.** ``TaskService.retarget_due_journal`` locks
        the **task** row first and only then takes ``FOR KEY SHARE`` on the
        journals, through the link insert's and the anchor update's foreign
        keys; this method and its caller take the **journals** first and then
        write the task rows. Two operations, the same two kinds of row, opposite
        orders — so retargeting a task while a merge absorbs the journal it is
        due in deadlocks. The difference from creation is that a retarget
        *chooses* when it takes each lock, so an ordering exists that removes
        the inversion. Doing so changes both sides and needs a locking read on
        the journal domain's port, which is why it is **ITER18-002 Phase 6**
        rather than a note here. Until it lands, this is a known intermittent
        failure of one of the two callers, not a correctness hole: neither
        operation half-applies.

        As with the deleted-task cases in the task repository's own tests, none
        of the concurrent forms can be staged against the integration fixture —
        one savepoint-bound transaction means a second connection cannot see the
        journals involved — so this is reasoned about rather than pinned by a
        test.
        """
        for journal_id in sorted((source_journal_id, target_journal_id)):
            await self.conn.execute(_LOCK_JOURNAL, {"journal_id": journal_id})

    async def _tasks_referencing(self, journal_id: int) -> list[_AffectedTask]:
        """Every task that names this journal in any of the three roles.

        Read before a re-point moves anything, because afterwards there is
        nothing left pointing at the journal to identify them by — and because
        the anchor roles it carries are overwritten by the re-point itself.

        Ordered by task id, which is the order the events go out in: the union's
        two halves would otherwise arrive in whatever order the plan produced,
        and one merge's outbox rows would differ between runs.
        """
        result = await self.conn.execute(_TASKS_REFERENCING, {"journal_id": journal_id})
        return [
            _AffectedTask(
                task_id=int(row.id),
                user_id=row.user_id,
                creating_anchor_moved=bool(row.creating_anchor_moved),
                due_anchor_moved=bool(row.due_anchor_moved),
            )
            for row in result.fetchall()
        ]

"""The tasks domain's half of a journal merge.

A merge is the one journal operation a task can never block: the anchors are
``ON DELETE RESTRICT`` and intermediate links cascade, so before the absorbed
journal can go, every link a task holds on it has to move onto the survivor.
That write lives in the journal domain, where the merge is. The **event** does
not: it is about a task, aggregated under a task id, and the tasks domain owns
what a task announces about itself.

This service is that seam, and it is deliberately one call wide.
``JournalMergeService`` holds it instead of the repository, so the journal
domain moves task links by asking the tasks domain to do it rather than by
constructing task events itself — the ports-and-adapters stance the domain
architecture document takes, applied to a write instead of a read.

**No new ABC.** ``TaskAnchorRepository`` is an abstract port because adapters
vary; this has one implementation and one consumer, and its single method is
already the whole of the capability the journal domain is being handed — it can
move a task's journal links and do nothing else. A second name for the same
contract would be ceremony, and the class is small enough to read as its own
interface.
"""

import structlog
from core_shared.models.history import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.events import TaskJournalLinksRepointed
from app.core.tasks.models.repositories import TaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger(__name__)


class TaskJournalMergeService:
    """Moves a task's journal links through a merge, and says so."""

    def __init__(
        self,
        task_anchor_repo: TaskAnchorRepository,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.task_anchor_repo = task_anchor_repo
        self.event_publisher = event_publisher

    @transactional
    async def repoint_journal_links(
        self,
        *,
        source_journal_id: int,
        target_journal_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> None:
        """Move every task link off the absorbed journal, announcing each task.

        The row work is the repository's, unchanged: four set-based statements
        under locks on both journals, which is why this is a delegation rather
        than an implementation. What this adds is the announcement the merge
        never made — one :class:`TaskJournalLinksRepointed` per affected task,
        aggregated under the task's own id, so the change reaches the task's
        history instead of only the two journals'.

        **One event per task, in task-id order.** The repository reports in that
        order for exactly this reason: the outbox rows a merge writes are read
        back in ``(occurred_at, id)`` order, and an unordered report would make
        one merge's history differ between runs.

        **A merge that moved no task publishes nothing**, which is most merges.
        The repository reports a task only if it actually moved something for
        it, so there is no "did anything change?" test here to disagree with the
        one the SQL already performed.

        Called from inside :meth:`JournalMergeService.merge_journals`' unit of
        work, so the events and the rows they describe commit together or
        neither does. ``@transactional`` is re-entrant and therefore does nothing
        in that nesting; it is here so the method is safe to call on its own and
        cannot become a write with no unit of work by being reached from a new
        caller.

        Args:
            source_journal_id: The journal being absorbed, about to be deleted.
            target_journal_id: The surviving journal the links move onto.
            transaction: The merge's connection, carried onto each event.
            source: Who performed the merge. A merge is something a person did,
                so the tasks it moved carry that actor rather than ``SYSTEM`` —
                the same reasoning as the intermediate link a retarget retains.
            changed_by: The actor label recorded against each task's history row.
        """
        repointed = await self.task_anchor_repo.repoint_journal_links(
            source_journal_id=source_journal_id,
            target_journal_id=target_journal_id,
        )
        for repointing in repointed:
            await self.event_publisher.publish(
                TaskJournalLinksRepointed(
                    repointing=repointing,
                    source_journal_id=source_journal_id,
                    target_journal_id=target_journal_id,
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )
        if repointed:
            logger.info(
                "Task journal links re-pointed by a merge",
                source_journal_id=source_journal_id,
                target_journal_id=target_journal_id,
                task_count=len(repointed),
            )

"""The tasks domain's half of a journal merge.

A merge is the one journal operation a task can never block: the anchors are
``ON DELETE RESTRICT`` and intermediate links cascade, so before the absorbed
journal can go, every link a task holds on it has to move onto the survivor.
That write lives in the journal domain, where the merge is. The **event** does
not: it is about a task, aggregated under a task id, and the tasks domain owns
what a task announces about itself.

This service is that seam, and it is deliberately narrow.
``JournalMergeService`` holds it instead of the repositories, so the journal
domain moves task links — and list associations — by asking the tasks domain to
do it rather than by constructing task or list events itself — the
ports-and-adapters stance the domain architecture document takes, applied to a
write instead of a read.

It has two calls, run in step 0 of the merge one after the other: the task
links, which lock both journals and then the tasks, and the lists associated
with the absorbed journal, which follow the survivor and are locked last.

**No new ABC.** ``TaskAnchorRepository`` and ``TaskListRepository`` are
abstract ports because adapters vary; this has one implementation and one
consumer, and its two methods are already the whole of the capability the
journal domain is being handed — it can move what names the absorbed journal
and do nothing else. A second name for the same contract would be ceremony,
and the class is small enough to read as its own interface.
"""

import structlog
from core_shared.models.history import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.events import TaskJournalLinksRepointed
from app.core.tasks.models.repositories import TaskAnchorRepository, TaskListRepository
from app.core.tasks.models.task_list_events import TaskListUpdated
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger(__name__)


class TaskJournalMergeService:
    """Moves a task's journal links through a merge, and says so."""

    def __init__(
        self,
        task_anchor_repo: TaskAnchorRepository,
        task_list_repo: TaskListRepository,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.task_anchor_repo = task_anchor_repo
        self.task_list_repo = task_list_repo
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

    @transactional
    async def repoint_list_associations(
        self,
        *,
        source_journal_id: int,
        target_journal_id: int,
        user_id: str,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> None:
        """Move every one of the owner's lists on the absorbed journal to the survivor.

        **One** ``TaskListUpdated`` **per list, in list-id order**, carrying
        ``associated_journal_id`` ``(absorbed, survivor)``, so each list's
        history says where its journal went. A system write: archived lists
        move too, since an archived list keeps its association.

        **Called after** :meth:`repoint_journal_links`, which locks both
        journals and then the tasks, so the lists are taken last — the order a
        journal delete takes them in, with the same remaining window against a
        move or a removal that ``TaskJournalDeletionService.unassociate_lists``
        describes.

        Args:
            source_journal_id: The journal being absorbed, about to be deleted.
            target_journal_id: The surviving journal the lists move onto.
            user_id: Both journals' owner; only their lists are touched.
            transaction: The merge's connection, carried onto each event.
            source: Who performed the merge.
            changed_by: The actor label recorded against each history row.
        """
        moved = await self.task_list_repo.reassociate_journal(
            source_journal_id=source_journal_id,
            target_journal_id=target_journal_id,
            user_id=user_id,
        )
        for task_list_id in moved:
            await self.event_publisher.publish(
                TaskListUpdated(
                    task_list_id=task_list_id,
                    user_id=user_id,
                    changed_fields={
                        "associated_journal_id": (source_journal_id, target_journal_id)
                    },
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )
        if moved:
            logger.info(
                "List associations re-pointed by a merge",
                source_journal_id=source_journal_id,
                target_journal_id=target_journal_id,
                list_count=len(moved),
            )

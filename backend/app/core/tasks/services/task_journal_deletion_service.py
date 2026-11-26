"""The tasks domain's half of a journal delete.

A journal delete is refused while a journal-only task is anchored to it, but a
task on a list never blocks it: the specification has the list task lose its
link to the journal instead, and a task due there becomes undated. That write
happens inside the journal domain's delete, where the journal is. The **event**
does not: it is about a task, aggregated under a task id, and the tasks domain
owns what a task announces about itself.

This service is that seam, mirroring ``TaskJournalMergeService`` for the merge:
``JournalService`` holds it instead of constructing task events itself. It also
answers the delete preview's question, so the count a confirmation states and
the links the delete removes come through one door over one predicate.

A **list** associated with the journal survives the delete too, unassociated,
and announces that in its own history — the same seam, for the same reason.
"""

import structlog
from core_shared.models.history import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.events import TaskJournalLinksRemoved
from app.core.tasks.models.repositories import TaskAnchorRepository, TaskListRepository
from app.core.tasks.models.task_list_events import TaskListUpdated
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger(__name__)


class TaskJournalDeletionService:
    """Detaches list tasks from a journal being deleted, and says so."""

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
    async def remove_list_task_links(
        self,
        *,
        journal_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> int:
        """Remove every list task's links to the journal, announcing each task.

        **One event per task, in task-id order**, as the repository reports
        them, so a delete's history is the same every run. A delete no list
        task links to publishes nothing, which is most deletes.

        Called from inside ``JournalService.delete_journal``'s savepoint, so the
        detach, its events and the journal row's removal commit together or not
        at all. ``@transactional`` is re-entrant and does nothing in that
        nesting; it is here so the method cannot become a write with no unit of
        work by being reached from a new caller.

        Args:
            journal_id: The journal about to be deleted.
            transaction: The delete's connection, carried onto each event.
            source: Who performed the delete; the tasks it changed carry that
                actor rather than ``SYSTEM``, as a merge's do.
            changed_by: The actor label recorded against each history row.

        Returns:
            How many list tasks lost a link.
        """
        detached = await self.task_anchor_repo.detach_list_tasks_from_journal(
            journal_id
        )
        for detachment in detached:
            await self.event_publisher.publish(
                TaskJournalLinksRemoved(
                    detachment=detachment,
                    journal_id=journal_id,
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )
        if detached:
            logger.info(
                "List tasks detached from a deleted journal",
                journal_id=journal_id,
                task_count=len(detached),
            )
        return len(detached)

    async def count_list_task_links(self, journal_id: int) -> int:
        """How many list tasks a delete of this journal would detach."""
        return await self.task_anchor_repo.count_list_tasks_linked_to_journal(
            journal_id
        )

    @transactional
    async def unassociate_lists(
        self,
        *,
        journal_id: int,
        user_id: str,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> None:
        """Leave every one of the owner's lists on the journal unassociated.

        **One** ``TaskListUpdated`` **per list, in list-id order**, carrying
        ``associated_journal_id`` ``(journal, None)``, so each list's history
        says why its journal went. A system write: archived lists are included,
        since an archived list keeps its association and the journal is going
        regardless.

        **Called after** :meth:`remove_list_task_links`, inside the delete's
        savepoint. That call has locked the journal and then its linked list
        tasks, so the lists are taken last — journal, tasks, lists. A task write
        takes its task and then its list, and so never waits on this delete for
        the list while holding a task the delete wants. A move, a removal, a
        reorder of the list's tasks and a list delete take the list and then
        its tasks, so one of those on a list associated with the journal, over
        a task linked to it, can still meet the delete in a deadlock, which
        PostgreSQL resolves by aborting one side (``40P01``, not retried). No
        single order avoids both kinds of writer; the task writes are the
        frequent kind, and the overlap needs one user acting on one list while
        deleting its journal.

        Args:
            journal_id: The journal about to be deleted.
            user_id: The journal's owner; only their lists are touched.
            transaction: The delete's connection, carried onto each event.
            source: Who performed the delete.
            changed_by: The actor label recorded against each history row.
        """
        unassociated = await self.task_list_repo.unassociate_journal(
            journal_id, user_id
        )
        for task_list_id in unassociated:
            await self.event_publisher.publish(
                TaskListUpdated(
                    task_list_id=task_list_id,
                    user_id=user_id,
                    changed_fields={"associated_journal_id": (journal_id, None)},
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )
        if unassociated:
            logger.info(
                "Lists unassociated from a deleted journal",
                journal_id=journal_id,
                list_count=len(unassociated),
            )

    async def count_associated_lists(self, journal_id: int, user_id: str) -> int:
        """How many of the owner's lists a delete of this journal would unassociate."""
        return await self.task_list_repo.count_associated_with_journal(
            journal_id, user_id
        )

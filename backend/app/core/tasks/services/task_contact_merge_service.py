"""The tasks domain's half of a contact merge.

A merge is the one contact operation a task can never block, and until this
existed it was the one that quietly destroyed a task's data:
``task_contacts.contact_id`` is ``ON DELETE CASCADE``, and the merge ends by
deleting the absorbed contact. So before that row can go, every link a task
holds on it has to move onto the survivor. That write lives in the contacts
domain, where the merge is. The **event** does not: it is about a task,
aggregated under a task id, and the tasks domain owns what a task announces
about itself.

This service is that seam, and it is deliberately one call wide — the same shape
and the same reasoning as :mod:`app.core.tasks.services.task_journal_merge_service`.
``ContactMergeService`` holds it instead of the repository, so the contacts
domain moves task links by asking the tasks domain to do it rather than by
constructing task events itself.

**No new ABC.** ``TaskContactRepository`` is an abstract port because it is the
boundary the contacts domain is handed; this has one implementation and one
consumer, and its single method is already the whole of the capability — it can
move a task's contact links and do nothing else.
"""

import structlog
from core_shared.models.history import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.events import (
    TaskUpdated,
    contact_repointing_changed_fields,
)
from app.core.tasks.models.repositories import TaskContactRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger(__name__)


class TaskContactMergeService:
    """Moves a task's people through a merge, and says so."""

    def __init__(
        self,
        task_contact_repo: TaskContactRepository,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.task_contact_repo = task_contact_repo
        self.event_publisher = event_publisher

    @transactional
    async def repoint_contact_links(
        self,
        *,
        source_contact_id: int,
        survivor_contact_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> None:
        """Move every task link off the absorbed contact, announcing each task.

        The row work is the repository's: two set-based statements under locks on
        both contacts, which is why this is a delegation rather than an
        implementation. What this adds is the announcement — one
        :class:`TaskUpdated` per affected task, aggregated under the task's own
        id, so the change reaches the task's history and the survivor's activity
        feed instead of vanishing with the deleted contact.

        **One event per task, in task-id order.** The repository reports in that
        order for exactly this reason: the outbox rows a merge writes are read
        back in ``(occurred_at, id)`` order, and an unordered report would make
        one merge's history differ between runs.

        **A merge that moved no task publishes nothing**, which is most merges.
        The repository reports a task only if it actually moved something for it,
        so there is no "did anything change?" test here to disagree with the one
        the SQL already performed.

        Called from inside :meth:`ContactMergeService.merge_contacts`' unit of
        work, so the events and the rows they describe commit together or neither
        does. ``@transactional`` is re-entrant and therefore does nothing in that
        nesting; it is here so the method is safe to call on its own and cannot
        become a write with no unit of work by being reached from a new caller.

        Args:
            source_contact_id: The contact being absorbed, about to be deleted.
            survivor_contact_id: The surviving contact the links move onto.
            transaction: The merge's connection, carried onto each event.
            source: Who performed the merge. A merge is something a person did,
                so the tasks it moved carry that actor rather than ``SYSTEM``.
            changed_by: The actor label recorded against each task's history row.
        """
        repointed = await self.task_contact_repo.repoint_contact_links(
            source_contact_id=source_contact_id,
            survivor_contact_id=survivor_contact_id,
        )
        for repointing in repointed:
            await self.event_publisher.publish(
                TaskUpdated(
                    task_id=repointing.task_id,
                    user_id=repointing.user_id,
                    changed_fields=contact_repointing_changed_fields(
                        repointing, source_contact_id, survivor_contact_id
                    ),
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )
        if repointed:
            logger.info(
                "Task contact links re-pointed by a merge",
                source_contact_id=source_contact_id,
                survivor_contact_id=survivor_contact_id,
                task_count=len(repointed),
            )

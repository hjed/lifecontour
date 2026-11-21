"""One way for tests to build a real ``JournalService`` by hand.

Production resolves the service from Dishka (``JournalProvider``). Tests that
drive it on their own connection used to spell out its collaborators at every
site, so each new required collaborator meant editing every one of them. This
factory is that spelling, once: real adapters over the given connection unless
a test overrides one to stage a race or isolate a failure.

**The delete's tasks-domain half defaults to the real thing**, built over the
same anchor repository and publisher the service holds. A test that stages the
guard with a double therefore gets a deletion service over that double too, so
the two halves of a delete can never be reading different ports.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.models.repositories import (
    JournalContactRelationshipRepository,
    JournalRepository,
)
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_tag_hierarchy_service import (
    JournalTagHierarchyService,
)
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.models.repositories import TaskAnchorRepository
from app.core.tasks.services.task_journal_deletion_service import (
    TaskJournalDeletionService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


def build_journal_service(
    connection: AsyncConnection,
    *,
    journal_repo: JournalRepository | None = None,
    event_publisher: OutboxEventPublisher | None = None,
    contact_relationship_repo: JournalContactRelationshipRepository | None = None,
    tag_hierarchy: JournalTagHierarchyService | None = None,
    task_anchor_repo: TaskAnchorRepository | None = None,
    task_journal_deletion: TaskJournalDeletionService | None = None,
) -> JournalService:
    """A ``JournalService`` over real adapters on ``connection``.

    Each argument replaces one collaborator; anything left out is the real
    adapter on the same connection, so the service and everything it writes
    share the test's unit of work.
    """
    publisher = event_publisher or OutboxEventPublisher(connection)
    anchors = task_anchor_repo or SqlTaskAnchorRepository(connection)
    return JournalService(
        journal_repo=journal_repo or SqlJournalRepository(connection),
        event_publisher=publisher,
        contact_relationship_repo=contact_relationship_repo,
        tag_hierarchy=tag_hierarchy,
        task_anchor_repo=anchors,
        task_journal_deletion=task_journal_deletion
        or TaskJournalDeletionService(
            task_anchor_repo=anchors, event_publisher=publisher
        ),
    )

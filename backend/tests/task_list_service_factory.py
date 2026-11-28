"""One way for tests to build a real ``TaskListService`` by hand.

Production resolves the service from Dishka (``TaskProvider``). Tests that drive
it on their own connection used to spell out its collaborators at every site, so
each new required collaborator meant editing every one of them. This factory is
that spelling, once: real adapters over the given connection unless a test
overrides one to stage a race or read what was published.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.models.repositories import JournalRepository
from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.models.repositories import TaskListRepository, TaskRepository
from app.core.tasks.services.task_list_service import TaskListService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


def build_task_list_service(
    connection: AsyncConnection,
    *,
    task_list_repo: TaskListRepository | None = None,
    task_repo: TaskRepository | None = None,
    journal_repo: JournalRepository | None = None,
    event_publisher: OutboxEventPublisher | None = None,
) -> TaskListService:
    """A ``TaskListService`` over real adapters on ``connection``.

    Each argument replaces one collaborator; anything left out is the real
    adapter on the same connection, so the service and everything it writes
    share the test's unit of work.
    """
    return TaskListService(
        task_list_repo=task_list_repo or SqlTaskListRepository(connection),
        task_repo=task_repo or SqlTaskRepository(connection),
        journal_repo=journal_repo or SqlJournalRepository(connection),
        event_publisher=event_publisher or OutboxEventPublisher(connection),
    )

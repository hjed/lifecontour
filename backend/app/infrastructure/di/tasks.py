"""Dependency injection providers for the tasks domain."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import ContactRepository
from app.core.journal.models.repositories import (
    CalendarInfoRepository,
    JournalRepository,
)
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.models.repositories import TaskRepository
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


class TaskProvider(Provider):
    """Provides the tasks domain's dependencies.

    Callers depend on the ``TaskRepository`` port; the SQL adapter is what they
    actually receive. The repository is request-scoped because it holds the
    request's ``AsyncConnection``, and it opens no transaction of its own —
    writes are committed by the ``@transactional`` service methods.

    ``TaskService`` reaches across domains for the data its invariants need — a
    journal repository, a contact repository and the journal domain's date
    resolver — so this provider no longer stands alone. Dishka validates the
    whole graph at container construction, not lazily, so a container holding
    this provider also needs ``JournalProvider``, ``ContactProvider``,
    ``SettingsProvider``, ``InfrastructureProvider`` (for ``Settings``) and
    ``IntegrationProvider`` (which ``ContactProvider``'s merge service reaches
    for) — the last two are not dependencies of anything the tasks domain
    resolves. Both the application container and the integration-test container
    register all of them; tests use
    ``tests/integration/tasks/task_seeding.make_task_container``.
    """

    @provide(scope=Scope.REQUEST)
    def task_repository(self, connection: AsyncConnection) -> TaskRepository:
        """Provide a TaskRepository instance."""
        return SqlTaskRepository(connection)

    @provide(scope=Scope.REQUEST)
    def task_service(
        self,
        task_repo: TaskRepository,
        journal_repo: JournalRepository,
        contact_repo: ContactRepository,
        date_resolver: JournalDateResolver,
        event_publisher: OutboxEventPublisher,
    ) -> TaskService:
        """Provide a TaskService instance.

        The outbox publisher comes from ``InfrastructureProvider`` and is bound
        to the same request connection the repositories hold, which is what lets
        a task write and its domain event share one unit of work.
        """
        return TaskService(
            task_repo=task_repo,
            journal_repo=journal_repo,
            contact_repo=contact_repo,
            date_resolver=date_resolver,
            event_publisher=event_publisher,
        )

    @provide(scope=Scope.REQUEST)
    def task_read_service(
        self,
        task_repo: TaskRepository,
        journal_repo: JournalRepository,
        contact_repo: ContactRepository,
        calendar_info_repo: CalendarInfoRepository,
        date_resolver: JournalDateResolver,
    ) -> TaskReadService:
        """Provide a TaskReadService instance.

        Separate from ``TaskService`` rather than more methods on it: this one
        writes nothing, so it takes no event publisher and opens no unit of
        work, and a caller that only needs to read a task should not be handed
        the ability to change one. It is the only consumer of
        ``CalendarInfoRepository`` outside the journal domain, which is where
        the cancelled-journal lapse cause comes from.
        """
        return TaskReadService(
            task_repo=task_repo,
            journal_repo=journal_repo,
            contact_repo=contact_repo,
            calendar_info_repo=calendar_info_repo,
            date_resolver=date_resolver,
        )

"""Dependency injection providers for the tasks domain."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.models.repositories import TaskRepository


class TaskProvider(Provider):
    """Provides the tasks domain's dependencies.

    Callers depend on the ``TaskRepository`` port; the SQL adapter is what they
    actually receive. The repository is request-scoped because it holds the
    request's ``AsyncConnection``, and it opens no transaction of its own —
    writes are committed by the ``@transactional`` services that arrive in
    Phase 4.
    """

    @provide(scope=Scope.REQUEST)
    def task_repository(self, connection: AsyncConnection) -> TaskRepository:
        """Provide a TaskRepository instance."""
        return SqlTaskRepository(connection)

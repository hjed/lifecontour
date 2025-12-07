"""Dependency injection providers for the journal domain."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.models.repositories import JournalRepository


class JournalProvider(Provider):
    """Dishka provider for journal domain dependencies."""

    @provide(scope=Scope.REQUEST)
    def journal_repository(self, connection: AsyncConnection) -> JournalRepository:
        """Provide a JournalRepository instance."""
        return SqlJournalRepository(connection)

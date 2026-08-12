"""Dependency injection providers for the dashboard domain."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dashboard.services.home_dashboard_service import HomeDashboardService
from app.core.journal.services.journal_date_resolver import JournalDateResolver


class DashboardProvider(Provider):
    """Provides the dashboard domain's dependencies.

    Request-scoped, because the service holds the request's ``AsyncConnection``
    for its per-section SAVEPOINTs. It opens no transaction of its own — the
    dashboard is read-only.

    ``JournalDateResolver`` comes from ``JournalProvider`` (which itself needs
    ``SettingsProvider``), and Dishka validates the whole graph at container
    construction, so a container registering this provider must register those
    too. The application container and both integration-test containers do.
    """

    @provide(scope=Scope.REQUEST)
    def home_dashboard_service(
        self,
        date_resolver: JournalDateResolver,
        connection: AsyncConnection,
    ) -> HomeDashboardService:
        """Provide a HomeDashboardService instance."""
        return HomeDashboardService(date_resolver=date_resolver, connection=connection)

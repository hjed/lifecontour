"""Dependency injection providers for the dashboard domain."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services.upcoming_important_dates_service import (
    UpcomingImportantDatesService,
)
from app.core.dashboard.services.home_dashboard_service import HomeDashboardService
from app.core.journal.models.repositories import AgendaRepository
from app.core.journal.services.daily_summary_repository import (
    JournalDailySummaryRepository,
)
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.services.task_read_service import TaskReadService


class DashboardProvider(Provider):
    """Provides the dashboard domain's dependencies.

    Request-scoped, because the service holds the request's ``AsyncConnection``
    for its per-section SAVEPOINTs. It opens no transaction of its own — the
    dashboard is read-only.

    ``JournalDateResolver``, ``JournalDailySummaryRepository`` and
    ``AgendaRepository`` all come from ``JournalProvider`` (which itself needs
    ``SettingsProvider``), and Dishka validates the whole graph at container
    construction, so a container registering this provider must register those
    too. The application container and both integration-test containers do.

    The agenda port sits there rather than here because it reads **journals**;
    the dashboard is one of its two callers, not its owner.
    ``UpcomingImportantDatesService`` comes from ``ContactProvider`` for the same
    reason and with a third caller ahead of it: an agent reaches the same answer
    through ``list_upcoming_important_dates``, and ITER18-005 Phase 6 will reach
    it again from the daily summary's inputs. ``TaskReadService`` comes from
    ``TaskProvider`` on the same terms, and is the most-shared of the four —
    ``GET /api/tasks/upcoming``, ``list_upcoming_tasks`` and the daily summary's
    input assembler all reach the same listing, which is why the tasks section
    adds no query of its own. Every container that registers this provider
    already registered ``TaskProvider``, so nothing needed widening.

    The **repository** rather than ``DailySummaryService`` is deliberate: the
    service's read path generates, and a dashboard load must not write.
    """

    @provide(scope=Scope.REQUEST)
    def home_dashboard_service(
        self,
        date_resolver: JournalDateResolver,
        summary_repo: JournalDailySummaryRepository,
        agenda_repo: AgendaRepository,
        task_read_service: TaskReadService,
        upcoming_dates_service: UpcomingImportantDatesService,
        connection: AsyncConnection,
    ) -> HomeDashboardService:
        """Provide a HomeDashboardService instance."""
        return HomeDashboardService(
            date_resolver=date_resolver,
            summary_repo=summary_repo,
            agenda_repo=agenda_repo,
            task_read_service=task_read_service,
            upcoming_dates_service=upcoming_dates_service,
            connection=connection,
        )

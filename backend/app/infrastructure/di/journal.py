"""Dependency injection providers for the journal domain."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
)
from app.core.journal.adapters.sql.calendar_repository import SqlCalendarRepository
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.adapters.sql.photo_album_data_repository import (
    SqlPhotoAlbumDataRepository,
)
from app.core.journal.adapters.sql.plan_data_repository import SqlPlanDataRepository
from app.core.journal.adapters.sql.travel_data_repository import SqlTravelDataRepository
from app.core.journal.models.repositories import (
    CalendarInfoRepository,
    CalendarRepository,
    JournalContactRelationshipRepository,
    JournalRepository,
    JournalTagRepository,
    MoodDataRepository,
    PhotoAlbumDataRepository,
    PlanDataRepository,
    TravelDataRepository,
)
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


class JournalProvider(Provider):
    """Dishka provider for journal domain dependencies."""

    @provide(scope=Scope.REQUEST)
    def journal_repository(self, connection: AsyncConnection) -> JournalRepository:
        """Provide a JournalRepository instance."""
        return SqlJournalRepository(connection)

    @provide(scope=Scope.REQUEST)
    def calendar_repository(self, connection: AsyncConnection) -> CalendarRepository:
        """Provide a CalendarRepository instance."""
        return SqlCalendarRepository(connection)

    @provide(scope=Scope.REQUEST)
    def calendar_info_repository(
        self, connection: AsyncConnection
    ) -> CalendarInfoRepository:
        """Provide a CalendarInfoRepository instance."""
        return SqlCalendarInfoRepository(connection)

    @provide(scope=Scope.REQUEST)
    def mood_data_repository(self, connection: AsyncConnection) -> MoodDataRepository:
        """Provide a MoodDataRepository instance."""
        return SqlMoodDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def photo_album_data_repository(
        self, connection: AsyncConnection
    ) -> PhotoAlbumDataRepository:
        """Provide a PhotoAlbumDataRepository instance."""
        return SqlPhotoAlbumDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def plan_data_repository(self, connection: AsyncConnection) -> PlanDataRepository:
        """Provide a PlanDataRepository instance."""
        return SqlPlanDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def travel_data_repository(
        self, connection: AsyncConnection
    ) -> TravelDataRepository:
        """Provide a TravelDataRepository instance."""
        return SqlTravelDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def journal_tag_repository(
        self, connection: AsyncConnection
    ) -> JournalTagRepository:
        """Provide a JournalTagRepository instance."""
        return SqlJournalTagRepository(connection)

    @provide(scope=Scope.REQUEST)
    def journal_contact_relationship_repository(
        self, connection: AsyncConnection
    ) -> JournalContactRelationshipRepository:
        """Provide a JournalContactRelationshipRepository instance."""
        return SqlJournalContactRelationshipRepository(connection)

    @provide(scope=Scope.REQUEST)
    def journal_service(
        self,
        journal_repo: JournalRepository,
        event_publisher: OutboxEventPublisher,
    ) -> JournalService:
        """Provide a JournalService instance."""
        return JournalService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
        )

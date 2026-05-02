"""Dependency injection providers for the journal domain."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.abseil_pitch_repository import (
    SqlAbseilPitchRepository,
)
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.activity_template_repository import (
    SqlActivityTemplateRepository,
)
from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
)
from app.core.journal.adapters.sql.calendar_repository import SqlCalendarRepository
from app.core.journal.adapters.sql.canyoning_data_repository import (
    SqlCanyoningDataRepository,
)
from app.core.journal.adapters.sql.caving_data_repository import (
    SqlCavingDataRepository,
)
from app.core.journal.adapters.sql.climbing_data_repository import (
    SqlClimbingDataRepository,
)
from app.core.journal.adapters.sql.cross_country_skiing_data_repository import (
    SqlCrossCountrySkiingDataRepository,
)
from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.jogging_data_repository import (
    SqlJoggingDataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.adapters.sql.kayaking_data_repository import (
    SqlKayakingDataRepository,
)
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)
from app.core.journal.adapters.sql.photo_album_data_repository import (
    SqlPhotoAlbumDataRepository,
)
from app.core.journal.adapters.sql.plan_data_repository import SqlPlanDataRepository
from app.core.journal.adapters.sql.review_item_repository import (
    SqlReviewItemRepository,
)
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.adapters.sql.travel_data_repository import SqlTravelDataRepository
from app.core.journal.models.repositories import (
    AbseilingDataRepository,
    AbseilPitchRepository,
    ActivityTemplateRepository,
    BushwalkingDataRepository,
    CalendarInfoRepository,
    CalendarRepository,
    CanyoningDataRepository,
    CavingDataRepository,
    ClimbingDataRepository,
    CrossCountrySkiingDataRepository,
    FitnessDataRepository,
    JoggingDataRepository,
    JournalContactRelationshipRepository,
    JournalRepository,
    JournalTagRepository,
    KayakingDataRepository,
    MoodDataRepository,
    OutdoorActivityDataRepository,
    PhotoAlbumDataRepository,
    PlanDataRepository,
    ReviewItemRepository,
    RouteRepository,
    TravelDataRepository,
)
from app.core.journal.services.daily_summary_eligibility import (
    DailySummaryEligibilityChecker,
)
from app.core.journal.services.daily_summary_input_assembler import (
    DailySummaryInputAssembler,
)
from app.core.journal.services.daily_summary_prompt_builder import (
    DailySummaryPromptBuilder,
)
from app.core.journal.services.daily_summary_repository import (
    JournalDailySummaryRepository,
)
from app.core.journal.services.daily_summary_service import DailySummaryService
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.route_service import RouteService
from app.infrastructure.config import Settings
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
    def fitness_data_repository(
        self, connection: AsyncConnection
    ) -> FitnessDataRepository:
        """Provide a FitnessDataRepository instance."""
        return SqlFitnessDataRepository(connection)

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
    def outdoor_activity_data_repository(
        self, connection: AsyncConnection
    ) -> OutdoorActivityDataRepository:
        """Provide an OutdoorActivityDataRepository instance."""
        return SqlOutdoorActivityDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def bushwalking_data_repository(
        self, connection: AsyncConnection
    ) -> BushwalkingDataRepository:
        """Provide a BushwalkingDataRepository instance."""
        return SqlBushwalkingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def jogging_data_repository(
        self, connection: AsyncConnection
    ) -> JoggingDataRepository:
        """Provide a JoggingDataRepository instance."""
        return SqlJoggingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def abseil_pitch_repository(
        self, connection: AsyncConnection
    ) -> AbseilPitchRepository:
        """Provide an AbseilPitchRepository instance."""
        return SqlAbseilPitchRepository(connection)

    @provide(scope=Scope.REQUEST)
    def abseiling_data_repository(
        self, connection: AsyncConnection
    ) -> AbseilingDataRepository:
        """Provide an AbseilingDataRepository instance."""
        return SqlAbseilingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def canyoning_data_repository(
        self, connection: AsyncConnection
    ) -> CanyoningDataRepository:
        """Provide a CanyoningDataRepository instance."""
        return SqlCanyoningDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def caving_data_repository(
        self, connection: AsyncConnection
    ) -> CavingDataRepository:
        """Provide a CavingDataRepository instance."""
        return SqlCavingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def climbing_data_repository(
        self, connection: AsyncConnection
    ) -> ClimbingDataRepository:
        """Provide a ClimbingDataRepository instance."""
        return SqlClimbingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def kayaking_data_repository(
        self, connection: AsyncConnection
    ) -> KayakingDataRepository:
        """Provide a KayakingDataRepository instance."""
        return SqlKayakingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def cross_country_skiing_data_repository(
        self, connection: AsyncConnection
    ) -> CrossCountrySkiingDataRepository:
        """Provide a CrossCountrySkiingDataRepository instance."""
        return SqlCrossCountrySkiingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def route_repository(self, connection: AsyncConnection) -> RouteRepository:
        """Provide a RouteRepository instance."""
        return SqlRouteRepository(connection)

    @provide(scope=Scope.REQUEST)
    def review_item_repository(
        self, connection: AsyncConnection
    ) -> ReviewItemRepository:
        """Provide a ReviewItemRepository instance."""
        return SqlReviewItemRepository(connection)

    @provide(scope=Scope.REQUEST)
    def activity_template_repository(
        self, connection: AsyncConnection
    ) -> ActivityTemplateRepository:
        """Provide an ActivityTemplateRepository instance."""
        return SqlActivityTemplateRepository(connection)

    @provide(scope=Scope.REQUEST)
    def journal_service(
        self,
        journal_repo: JournalRepository,
        event_publisher: OutboxEventPublisher,
        contact_relationship_repo: JournalContactRelationshipRepository,
    ) -> JournalService:
        """Provide a JournalService instance."""
        return JournalService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
            contact_relationship_repo=contact_relationship_repo,
        )

    @provide(scope=Scope.REQUEST)
    def journal_merge_service(
        self,
        journal_repo: JournalRepository,
        event_publisher: OutboxEventPublisher,
    ) -> JournalMergeService:
        """Provide a JournalMergeService instance."""
        return JournalMergeService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
        )

    @provide(scope=Scope.REQUEST)
    def route_service(
        self,
        route_repo: RouteRepository,
        event_publisher: OutboxEventPublisher,
    ) -> RouteService:
        """Provide a RouteService instance."""
        return RouteService(
            route_repo=route_repo,
            event_publisher=event_publisher,
        )

    @provide(scope=Scope.REQUEST)
    def journal_contact_service(
        self,
        contact_relationship_repo: JournalContactRelationshipRepository,
        event_publisher: OutboxEventPublisher,
    ) -> JournalContactService:
        """Provide a JournalContactService instance."""
        return JournalContactService(
            contact_relationship_repo=contact_relationship_repo,
            event_publisher=event_publisher,
        )

    @provide(scope=Scope.REQUEST)
    def daily_summary_repository(
        self, connection: AsyncConnection
    ) -> JournalDailySummaryRepository:
        """Provide a JournalDailySummaryRepository instance."""
        return SqlJournalDailySummaryRepository(connection)

    @provide(scope=Scope.REQUEST)
    def daily_summary_eligibility_checker(self) -> DailySummaryEligibilityChecker:
        """Provide a DailySummaryEligibilityChecker instance."""
        return DailySummaryEligibilityChecker()

    @provide(scope=Scope.REQUEST)
    def daily_summary_prompt_builder(self) -> DailySummaryPromptBuilder:
        """Provide a DailySummaryPromptBuilder instance."""
        return DailySummaryPromptBuilder()

    @provide(scope=Scope.REQUEST)
    def daily_summary_input_assembler(
        self,
        journal_repo: JournalRepository,
        mood_repo: MoodDataRepository,
        contact_relationship_repo: JournalContactRelationshipRepository,
        summary_repo: JournalDailySummaryRepository,
    ) -> DailySummaryInputAssembler:
        """Provide a DailySummaryInputAssembler instance."""
        return DailySummaryInputAssembler(
            journal_repo=journal_repo,
            mood_repo=mood_repo,
            contact_relationship_repo=contact_relationship_repo,
            summary_repo=summary_repo,
        )

    @provide(scope=Scope.REQUEST)
    def daily_summary_service(
        self,
        input_assembler: DailySummaryInputAssembler,
        eligibility_checker: DailySummaryEligibilityChecker,
        prompt_builder: DailySummaryPromptBuilder,
        summary_repo: JournalDailySummaryRepository,
        settings: Settings,
    ) -> DailySummaryService:
        """Provide a DailySummaryService instance."""
        return DailySummaryService(
            input_assembler=input_assembler,
            eligibility_checker=eligibility_checker,
            prompt_builder=prompt_builder,
            summary_repo=summary_repo,
            gemini_api_key=settings.gemini_api_key,
            gemini_model=settings.gemini_summary_model,
        )

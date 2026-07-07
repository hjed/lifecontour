"""Dependency injection providers for the journal domain."""

from core_shared.models.journals import (
    LogbookSummaryCalculator,
    ParticipantIndexCalculator,
)
from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryRepository
from app.core.history.services import JournalHistoryService
from app.core.journal.adapters.sql.abseil_pitch_repository import (
    SqlAbseilPitchRepository,
)
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.activity_template_repository import (
    SqlActivityTemplateRepository,
)
from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)
from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
)
from app.core.journal.adapters.sql.calendar_repository import SqlCalendarRepository
from app.core.journal.adapters.sql.canoeing_data_repository import (
    SqlCanoeingDataRepository,
)
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
from app.core.journal.adapters.sql.diving_data_repository import (
    SqlDivingDataRepository,
)
from app.core.journal.adapters.sql.downhill_skiing_data_repository import (
    SqlDownhillSkiingDataRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.gear_item_repository import (
    SqlGearItemRepository,
)
from app.core.journal.adapters.sql.gear_maintenance_data_repository import (
    SqlGearMaintenanceDataRepository,
)
from app.core.journal.adapters.sql.gear_usage_data_repository import (
    SqlGearUsageDataRepository,
)
from app.core.journal.adapters.sql.incomplete_outdoor_activity_repository import (
    SqlIncompleteOutdoorActivityRepository,
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
from app.core.journal.adapters.sql.logbook_export_repository import (
    SqlLogbookExportRepository,
)
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)
from app.core.journal.adapters.sql.outdoor_activity_dismissal_repository import (
    SqlOutdoorActivityDismissalRepository,
)
from app.core.journal.adapters.sql.outdoor_planning_data_repository import (
    SqlOutdoorPlanningDataRepository,
)
from app.core.journal.adapters.sql.outdoor_training_data_repository import (
    SqlOutdoorTrainingDataRepository,
)
from app.core.journal.adapters.sql.plan_data_repository import SqlPlanDataRepository
from app.core.journal.adapters.sql.review_item_repository import (
    SqlReviewItemRepository,
)
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.adapters.sql.snorkelling_data_repository import (
    SqlSnorkellingDataRepository,
)
from app.core.journal.adapters.sql.travel_data_repository import SqlTravelDataRepository
from app.core.journal.models.repositories import (
    AbseilingDataRepository,
    AbseilPitchRepository,
    ActivityTemplateRepository,
    BushwalkingDataRepository,
    CalendarInfoRepository,
    CalendarRepository,
    CanoeingDataRepository,
    CanyoningDataRepository,
    CavingDataRepository,
    ClimbingDataRepository,
    CrossCountrySkiingDataRepository,
    DivingDataRepository,
    DownhillSkiingDataRepository,
    FitnessDataRepository,
    GearItemRepository,
    GearMaintenanceDataRepository,
    GearUsageDataRepository,
    IncompleteOutdoorActivityRepository,
    JoggingDataRepository,
    JournalContactRelationshipRepository,
    JournalRepository,
    JournalTagRepository,
    KayakingDataRepository,
    LogbookExportRepository,
    MoodDataRepository,
    OutdoorActivityDataRepository,
    OutdoorActivityDismissalRepository,
    OutdoorPlanningDataRepository,
    OutdoorTrainingDataRepository,
    PlanDataRepository,
    ReviewItemRepository,
    RouteRepository,
    SnorkellingDataRepository,
    TravelDataRepository,
)
from app.core.journal.services.activity_template_service import ActivityTemplateService
from app.core.journal.services.calendar_service import CalendarService
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
from app.core.journal.services.gear_item_service import GearItemService
from app.core.journal.services.incomplete_outdoor_activity_service import (
    IncompleteOutdoorActivityService,
)
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.logbook_data_service import LogbookDataService
from app.core.journal.services.logbook_pdf_renderer import LogbookPdfRenderer
from app.core.journal.services.outdoor_activity_dismissal_service import (
    OutdoorActivityDismissalService,
)
from app.core.journal.services.review_item_service import ReviewItemService
from app.core.journal.services.route_service import RouteService
from app.core.settings.models import UserSettingsRepository
from app.infrastructure.config import Settings
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


class JournalProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def journal_repository(self, connection: AsyncConnection) -> JournalRepository:
        """Provide a JournalRepository instance."""
        return SqlJournalRepository(connection)

    @provide(scope=Scope.REQUEST)
    def field_history_repository(
        self, connection: AsyncConnection
    ) -> FieldHistoryRepository:
        """Provide the entity-agnostic field-history repository (read side)."""
        return SqlFieldHistoryRepository(connection)

    @provide(scope=Scope.REQUEST)
    def journal_history_service(
        self, history_repo: FieldHistoryRepository
    ) -> JournalHistoryService:
        """Provide the journal history read service."""
        return JournalHistoryService(history_repo)

    @provide(scope=Scope.REQUEST)
    def calendar_repository(self, connection: AsyncConnection) -> CalendarRepository:
        """Provide a CalendarRepository instance."""
        return SqlCalendarRepository(connection)

    @provide(scope=Scope.REQUEST)
    def calendar_service(self, calendar_repo: CalendarRepository) -> CalendarService:
        """Provide a CalendarService instance."""
        return CalendarService(calendar_repo)

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
    def album_sync_read_repository(
        self, connection: AsyncConnection
    ) -> AlbumSyncReadRepository:
        """Provide an AlbumSyncReadRepository for PHOTO_ALBUM type data."""
        return AlbumSyncReadRepository(connection)

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
    def provide_outdoor_planning_data_repository(
        self, connection: AsyncConnection
    ) -> OutdoorPlanningDataRepository:
        """Provide an OutdoorPlanningDataRepository instance."""
        return SqlOutdoorPlanningDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def provide_outdoor_training_data_repository(
        self, connection: AsyncConnection
    ) -> OutdoorTrainingDataRepository:
        """Provide an OutdoorTrainingDataRepository instance."""
        return SqlOutdoorTrainingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def gear_maintenance_data_repository(
        self, connection: AsyncConnection
    ) -> GearMaintenanceDataRepository:
        """Provide a GearMaintenanceDataRepository instance."""
        return SqlGearMaintenanceDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def provide_gear_usage_data_repository(
        self, connection: AsyncConnection
    ) -> GearUsageDataRepository:
        """Provide a GearUsageDataRepository instance."""
        return SqlGearUsageDataRepository(connection)

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
    def canoeing_data_repository(
        self, connection: AsyncConnection
    ) -> CanoeingDataRepository:
        """Provide a CanoeingDataRepository instance."""
        return SqlCanoeingDataRepository(connection)

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
    def outdoor_activity_dismissal_repository(
        self, connection: AsyncConnection
    ) -> OutdoorActivityDismissalRepository:
        """Provide an OutdoorActivityDismissalRepository instance."""
        return SqlOutdoorActivityDismissalRepository(connection)

    @provide(scope=Scope.REQUEST)
    def incomplete_outdoor_activity_repository(
        self, connection: AsyncConnection
    ) -> IncompleteOutdoorActivityRepository:
        """Provide an IncompleteOutdoorActivityRepository instance."""
        return SqlIncompleteOutdoorActivityRepository(connection)

    @provide(scope=Scope.REQUEST)
    def activity_template_repository(
        self, connection: AsyncConnection
    ) -> ActivityTemplateRepository:
        """Provide an ActivityTemplateRepository instance."""
        return SqlActivityTemplateRepository(connection)

    @provide(scope=Scope.REQUEST)
    def activity_template_service(
        self, activity_template_repo: ActivityTemplateRepository
    ) -> ActivityTemplateService:
        """Provide an ActivityTemplateService instance."""
        return ActivityTemplateService(activity_template_repo)

    @provide(scope=Scope.REQUEST)
    def downhill_skiing_data_repository(
        self, connection: AsyncConnection
    ) -> DownhillSkiingDataRepository:
        """Provide a DownhillSkiingDataRepository instance."""
        return SqlDownhillSkiingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def snorkelling_data_repository(
        self, connection: AsyncConnection
    ) -> SnorkellingDataRepository:
        """Provide a SnorkellingDataRepository instance."""
        return SqlSnorkellingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def diving_data_repository(
        self, connection: AsyncConnection
    ) -> DivingDataRepository:
        """Provide a DivingDataRepository instance."""
        return SqlDivingDataRepository(connection)

    @provide(scope=Scope.REQUEST)
    def gear_item_repository(self, connection: AsyncConnection) -> GearItemRepository:
        """Provide a GearItemRepository instance."""
        return SqlGearItemRepository(connection)

    @provide(scope=Scope.REQUEST)
    def gear_item_service(
        self,
        gear_item_repo: GearItemRepository,
        event_publisher: OutboxEventPublisher,
    ) -> GearItemService:
        """Provide a GearItemService instance."""
        return GearItemService(
            gear_item_repo=gear_item_repo,
            event_publisher=event_publisher,
        )

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
    def journal_tag_service(
        self,
        tag_repo: JournalTagRepository,
    ) -> JournalTagService:
        """Provide a JournalTagService instance."""
        return JournalTagService(tag_repo=tag_repo)

    @provide(scope=Scope.REQUEST)
    def review_item_service(
        self,
        review_item_repo: ReviewItemRepository,
        journal_service: JournalService,
        journal_merge_service: JournalMergeService,
    ) -> ReviewItemService:
        """Provide a ReviewItemService instance."""
        return ReviewItemService(
            review_item_repo=review_item_repo,
            journal_service=journal_service,
            journal_merge_service=journal_merge_service,
        )

    @provide(scope=Scope.REQUEST)
    def outdoor_activity_dismissal_service(
        self,
        dismissal_repo: OutdoorActivityDismissalRepository,
    ) -> OutdoorActivityDismissalService:
        """Provide an OutdoorActivityDismissalService instance."""
        return OutdoorActivityDismissalService(dismissal_repo=dismissal_repo)

    @provide(scope=Scope.REQUEST)
    def incomplete_outdoor_activity_service(
        self,
        facts_repo: IncompleteOutdoorActivityRepository,
        dismissal_repo: OutdoorActivityDismissalRepository,
    ) -> IncompleteOutdoorActivityService:
        """Provide an IncompleteOutdoorActivityService instance."""
        return IncompleteOutdoorActivityService(
            facts_repo=facts_repo, dismissal_repo=dismissal_repo
        )

    @provide(scope=Scope.REQUEST)
    def journal_write_service(
        self,
        journal_service: JournalService,
        journal_contact_service: JournalContactService,
        calendar_info_repo: CalendarInfoRepository,
        photo_album_data_repo: AlbumSyncReadRepository,
        mood_data_repo: MoodDataRepository,
        plan_data_repo: PlanDataRepository,
        travel_data_repo: TravelDataRepository,
        fitness_data_repo: FitnessDataRepository,
        outdoor_activity_data_repo: OutdoorActivityDataRepository,
        bushwalking_data_repo: BushwalkingDataRepository,
        jogging_data_repo: JoggingDataRepository,
        abseiling_data_repo: AbseilingDataRepository,
        abseil_pitch_repo: AbseilPitchRepository,
        canyoning_data_repo: CanyoningDataRepository,
        caving_data_repo: CavingDataRepository,
        canoeing_data_repo: CanoeingDataRepository,
        climbing_data_repo: ClimbingDataRepository,
        kayaking_data_repo: KayakingDataRepository,
        skiing_data_repo: CrossCountrySkiingDataRepository,
        snorkelling_data_repo: SnorkellingDataRepository,
        diving_data_repo: DivingDataRepository,
        downhill_skiing_data_repo: DownhillSkiingDataRepository,
        outdoor_planning_data_repo: OutdoorPlanningDataRepository,
        outdoor_training_data_repo: OutdoorTrainingDataRepository,
        gear_maintenance_data_repo: GearMaintenanceDataRepository,
        gear_usage_data_repo: GearUsageDataRepository,
        tag_repo: JournalTagRepository,
        event_publisher: OutboxEventPublisher,
    ) -> JournalWriteService:
        """Provide a JournalWriteService instance (composite journal writes)."""
        return JournalWriteService(
            journal_service=journal_service,
            journal_contact_service=journal_contact_service,
            calendar_info_repo=calendar_info_repo,
            photo_album_data_repo=photo_album_data_repo,
            mood_data_repo=mood_data_repo,
            plan_data_repo=plan_data_repo,
            travel_data_repo=travel_data_repo,
            fitness_data_repo=fitness_data_repo,
            outdoor_activity_data_repo=outdoor_activity_data_repo,
            bushwalking_data_repo=bushwalking_data_repo,
            jogging_data_repo=jogging_data_repo,
            abseiling_data_repo=abseiling_data_repo,
            abseil_pitch_repo=abseil_pitch_repo,
            canyoning_data_repo=canyoning_data_repo,
            caving_data_repo=caving_data_repo,
            canoeing_data_repo=canoeing_data_repo,
            climbing_data_repo=climbing_data_repo,
            kayaking_data_repo=kayaking_data_repo,
            skiing_data_repo=skiing_data_repo,
            snorkelling_data_repo=snorkelling_data_repo,
            diving_data_repo=diving_data_repo,
            downhill_skiing_data_repo=downhill_skiing_data_repo,
            outdoor_planning_data_repo=outdoor_planning_data_repo,
            outdoor_training_data_repo=outdoor_training_data_repo,
            gear_maintenance_data_repo=gear_maintenance_data_repo,
            gear_usage_data_repo=gear_usage_data_repo,
            tag_repo=tag_repo,
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
        user_settings_repo: UserSettingsRepository,
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
            user_settings_repo=user_settings_repo,
        )

    @provide(scope=Scope.REQUEST)
    def logbook_export_repository(
        self, connection: AsyncConnection
    ) -> LogbookExportRepository:
        """Provide a LogbookExportRepository instance."""
        return SqlLogbookExportRepository(connection)

    @provide(scope=Scope.REQUEST)
    def logbook_summary_calculator(self) -> LogbookSummaryCalculator:
        """Provide a LogbookSummaryCalculator instance."""
        return LogbookSummaryCalculator()

    @provide(scope=Scope.REQUEST)
    def participant_index_calculator(self) -> ParticipantIndexCalculator:
        """Provide a ParticipantIndexCalculator instance."""
        return ParticipantIndexCalculator()

    @provide(scope=Scope.REQUEST)
    def logbook_data_service(
        self,
        repository: LogbookExportRepository,
        summary_calculator: LogbookSummaryCalculator,
        participant_calculator: ParticipantIndexCalculator,
    ) -> LogbookDataService:
        """Provide a LogbookDataService instance."""
        return LogbookDataService(
            repository=repository,
            summary_calculator=summary_calculator,
            participant_calculator=participant_calculator,
        )

    @provide(scope=Scope.APP)
    def logbook_pdf_renderer(self) -> LogbookPdfRenderer:
        """Provide a LogbookPdfRenderer instance."""
        return LogbookPdfRenderer()

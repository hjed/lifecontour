"""Dependency injection providers for the journal domain."""

import json

from core_shared.models.journals import (
    ActivityTypeIndexCalculator,
    LogbookSummaryCalculator,
    ParticipantIndexCalculator,
)
from dishka import AsyncContainer, Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services.upcoming_important_dates_service import (
    UpcomingImportantDatesService,
)
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryRepository
from app.core.history.services import JournalHistoryService
from app.core.journal.adapters.http.osm_tile_source import OsmTileSource
from app.core.journal.adapters.sql.abseil_pitch_repository import (
    SqlAbseilPitchRepository,
)
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.activity_stats_repository import (
    SqlActivityStatsRepository,
)
from app.core.journal.adapters.sql.activity_template_repository import (
    SqlActivityTemplateRepository,
)
from app.core.journal.adapters.sql.agenda_repository import SqlAgendaRepository
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
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
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
from app.core.journal.adapters.sql.outdoor_dashboard_repository import (
    SqlOutdoorDashboardRepository,
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
    ActivityStatsRepository,
    ActivityTemplateRepository,
    AgendaRepository,
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
    JournalSeriesRepository,
    JournalTagRepository,
    KayakingDataRepository,
    LogbookExportRepository,
    MoodDataRepository,
    OutdoorActivityDataRepository,
    OutdoorActivityDismissalRepository,
    OutdoorDashboardRepository,
    OutdoorPlanningDataRepository,
    OutdoorTrainingDataRepository,
    PlanDataRepository,
    ReviewItemRepository,
    RouteRepository,
    SnorkellingDataRepository,
    TravelDataRepository,
)
from app.core.journal.models.tile_source import TileSource
from app.core.journal.services.activity_template_service import ActivityTemplateService
from app.core.journal.services.calendar_service import CalendarService
from app.core.journal.services.daily_summary_eligibility import (
    DailySummaryEligibilityChecker,
)
from app.core.journal.services.daily_summary_freshness import (
    DailySummaryFreshnessChecker,
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
from app.core.journal.services.gpx_map_renderer import GpxMapRenderer
from app.core.journal.services.incomplete_outdoor_activity_service import (
    IncompleteOutdoorActivityService,
)
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.journal.services.journal_external_link_service import (
    JournalExternalLinkService,
)
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_search_service import JournalSearchService
from app.core.journal.services.journal_series_service import JournalSeriesService
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_tag_hierarchy_service import (
    JournalTagHierarchyService,
)
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.logbook_data_service import LogbookDataService
from app.core.journal.services.logbook_pdf_renderer import LogbookPdfRenderer
from app.core.journal.services.outdoor_activity_dismissal_service import (
    OutdoorActivityDismissalService,
)
from app.core.journal.services.outdoor_dashboard_service import (
    OutdoorDashboardService,
)
from app.core.journal.services.review_item_service import ReviewItemService
from app.core.journal.services.route_service import RouteService
from app.core.settings.models import UserSettingsRepository
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.models.repositories import TaskAnchorRepository
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.core.tasks.services.task_read_service import TaskReadService
from app.infrastructure.auth.immich_token_service import ImmichTokenService
from app.infrastructure.config import Settings
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.search.search_service import SearchService

# What the daily summary "model" says when ENABLE_TEST_DAILY_SUMMARY_STUB is on.
# Fixed rather than configurable, so the e2e suite can assert the sentence.
DAILY_SUMMARY_STUB_TEXT = (
    "A stubbed daily summary: the end-to-end stack answers without an AI model."
)


class JournalProvider(Provider):
    """Provides the journal domain's dependencies.

    **This provider is no longer self-sufficient, and the reversal is
    deliberate.** Two factories below — ``task_anchor_repository`` and
    ``task_journal_merge_service`` — build tasks-domain objects by hand with
    docstrings arguing that a ``JournalProvider`` depending on ``TaskProvider``
    "would force every container that registers one to register the other".
    That argument came with a condition, stated in those docstrings: *it needs
    nothing but the connection, so there is no graph cost*. Both of those still
    do, so both stay as they are.

    ``daily_summary_input_assembler`` broke the condition. The summary's
    forward-looking input is the dashboard's upcoming-task listing, reused
    whole, and ``TaskReadService`` needs five collaborators drawn from three
    domains. Hand-building it here would mean reaching around the container for
    ``SqlTaskRepository`` *and* ``SqlContactRepository`` — and would produce a
    second instance alongside ``TaskProvider``'s. A provider reaching around the
    container for another domain's adapter is usually a boundary complaining;
    two of them is the boundary saying the edge belongs in the graph.

    The summary's third forward-looking input made the same call a second time
    and for the same reason: ``UpcomingImportantDatesService`` needs the date
    resolver *and* two contacts-domain adapters, so hand-building it here would
    reach around the container again — and the recurrence rule it holds is the
    thing being reused, not either statement underneath. No cycle results:
    everything the contacts domain reaches for here is a journal *port* and none
    of it reaches back.

    So a container registering this provider must also register
    ``TaskProvider``, ``ContactProvider`` and ``IntegrationProvider`` (which
    ``ContactProvider``'s merge service reaches for), alongside the
    ``SettingsProvider`` and ``InfrastructureProvider`` it already needed. Every
    container does; ``tests/integration/journal/test_journal_date_resolver.py``
    was the last exception and gained them with the upcoming-tasks input.
    """

    @provide(scope=Scope.REQUEST)
    def journal_repository(self, connection: AsyncConnection) -> JournalRepository:
        """Provide a JournalRepository instance."""
        return SqlJournalRepository(connection)

    @provide(scope=Scope.REQUEST)
    def agenda_repository(self, connection: AsyncConnection) -> AgendaRepository:
        """Provide an AgendaRepository instance.

        Here rather than in ``DashboardProvider``, because the port is the
        journal domain's: it reads journals. The dashboard consumes it, which is
        the direction that already exists — ``DashboardProvider`` needs this
        provider anyway for the date resolver and the summary repository.
        """
        return SqlAgendaRepository(connection)

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
    def journal_series_repository(
        self, connection: AsyncConnection
    ) -> JournalSeriesRepository:
        """Provide a JournalSeriesRepository instance."""
        return SqlJournalSeriesRepository(connection)

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
    def activity_stats_repository(
        self, connection: AsyncConnection
    ) -> ActivityStatsRepository:
        """Provide an ActivityStatsRepository instance."""
        return SqlActivityStatsRepository(connection)

    @provide(scope=Scope.REQUEST)
    def outdoor_dashboard_repository(
        self, connection: AsyncConnection
    ) -> OutdoorDashboardRepository:
        """Provide an OutdoorDashboardRepository instance."""
        return SqlOutdoorDashboardRepository(connection)

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
    def task_anchor_repository(
        self, connection: AsyncConnection
    ) -> TaskAnchorRepository:
        """Provide a TaskAnchorRepository instance.

        Provided here rather than by ``TaskProvider``, even though the port and
        its adapter belong to the tasks domain, because its only consumer is the
        journal delete guard. Dishka validates the whole graph at construction,
        so making ``JournalProvider`` depend on something ``TaskProvider``
        supplies would force every container that registers one to register the
        other. It needs nothing but the connection, so there is no graph cost to
        keeping ``JournalProvider`` self-sufficient.
        """
        return SqlTaskAnchorRepository(connection)

    @provide(scope=Scope.REQUEST)
    def journal_service(
        self,
        journal_repo: JournalRepository,
        event_publisher: OutboxEventPublisher,
        contact_relationship_repo: JournalContactRelationshipRepository,
        tag_hierarchy: JournalTagHierarchyService,
        task_anchor_repo: TaskAnchorRepository,
    ) -> JournalService:
        """Provide a JournalService instance."""
        return JournalService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
            contact_relationship_repo=contact_relationship_repo,
            tag_hierarchy=tag_hierarchy,
            task_anchor_repo=task_anchor_repo,
        )

    @provide(scope=Scope.REQUEST)
    def task_journal_merge_service(
        self,
        task_anchor_repo: TaskAnchorRepository,
        event_publisher: OutboxEventPublisher,
    ) -> TaskJournalMergeService:
        """Provide the tasks domain's half of a journal merge.

        Provided here rather than by ``TaskProvider``, for the reason the anchor
        repository above is: Dishka validates the whole graph at construction, so
        a ``JournalProvider`` that depended on something ``TaskProvider``
        supplies would force every container registering one to register the
        other — eleven test containers, when this was last measured. It needs
        only the anchor repository this provider already builds and the
        request's outbox publisher, so ``JournalProvider`` stays self-sufficient.
        """
        return TaskJournalMergeService(
            task_anchor_repo=task_anchor_repo,
            event_publisher=event_publisher,
        )

    @provide(scope=Scope.REQUEST)
    def journal_merge_service(
        self,
        journal_repo: JournalRepository,
        event_publisher: OutboxEventPublisher,
        task_merge_service: TaskJournalMergeService,
    ) -> JournalMergeService:
        """Provide a JournalMergeService instance.

        A merge moves task links onto the survivor before deleting the absorbed
        journal, whose anchors would otherwise refuse the delete — and the tasks
        it moves record it in their own history. Both are the tasks domain's
        service to perform, so the journal domain holds that rather than the
        anchor repository the delete guard uses.
        """
        return JournalMergeService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
            task_merge_service=task_merge_service,
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
    def journal_tag_hierarchy_service(
        self,
        tag_repo: JournalTagRepository,
    ) -> JournalTagHierarchyService:
        """Provide a JournalTagHierarchyService instance."""
        return JournalTagHierarchyService(tag_repo=tag_repo)

    @provide(scope=Scope.REQUEST)
    def journal_tag_service(
        self,
        tag_repo: JournalTagRepository,
        hierarchy_service: JournalTagHierarchyService,
        event_publisher: OutboxEventPublisher,
    ) -> JournalTagService:
        """Provide a JournalTagService instance."""
        return JournalTagService(
            tag_repo=tag_repo,
            hierarchy_service=hierarchy_service,
            event_publisher=event_publisher,
        )

    @provide(scope=Scope.REQUEST)
    def journal_series_service(
        self,
        series_repo: JournalSeriesRepository,
        journal_repo: JournalRepository,
    ) -> JournalSeriesService:
        """Provide a JournalSeriesService instance."""
        return JournalSeriesService(series_repo=series_repo, journal_repo=journal_repo)

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
        user_settings_repo: UserSettingsRepository,
    ) -> IncompleteOutdoorActivityService:
        """Provide an IncompleteOutdoorActivityService instance."""
        return IncompleteOutdoorActivityService(
            facts_repo=facts_repo,
            dismissal_repo=dismissal_repo,
            user_settings_repo=user_settings_repo,
        )

    @provide(scope=Scope.REQUEST)
    def journal_external_link_service(
        self,
        journal_repo: JournalRepository,
        immich_token_service: ImmichTokenService,
    ) -> JournalExternalLinkService:
        """Provide a JournalExternalLinkService instance."""
        return JournalExternalLinkService(
            journal_repo=journal_repo, immich_token_service=immich_token_service
        )

    @provide(scope=Scope.REQUEST)
    def journal_search_service(
        self, journal_repo: JournalRepository, search_service: SearchService
    ) -> JournalSearchService:
        """Provide a JournalSearchService instance."""
        return JournalSearchService(
            journal_repo=journal_repo, search_service=search_service
        )

    @provide(scope=Scope.REQUEST)
    def outdoor_dashboard_service(
        self,
        dashboard_repo: OutdoorDashboardRepository,
        date_resolver: JournalDateResolver,
    ) -> OutdoorDashboardService:
        """Provide an OutdoorDashboardService instance."""
        return OutdoorDashboardService(
            dashboard_repo=dashboard_repo, date_resolver=date_resolver
        )

    @provide(scope=Scope.REQUEST)
    def journal_date_resolver(
        self, user_settings_repo: UserSettingsRepository
    ) -> JournalDateResolver:
        """Provide a JournalDateResolver instance."""
        return JournalDateResolver(user_settings_repo=user_settings_repo)

    @provide(scope=Scope.REQUEST)
    def journal_write_service(
        self,
        journal_service: JournalService,
        journal_contact_service: JournalContactService,
        tag_service: JournalTagService,
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
            tag_service=tag_service,
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
    def daily_summary_freshness_checker(self) -> DailySummaryFreshnessChecker:
        """Provide a DailySummaryFreshnessChecker instance."""
        return DailySummaryFreshnessChecker()

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
        series_repo: JournalSeriesRepository,
        agenda_repo: AgendaRepository,
        task_read_service: TaskReadService,
        upcoming_dates_service: UpcomingImportantDatesService,
    ) -> DailySummaryInputAssembler:
        """Provide a DailySummaryInputAssembler instance.

        ``TaskReadService`` comes from ``TaskProvider``, and it is the one
        dependency that makes this provider need that one — see the class
        docstring for why the edge is in the graph rather than hand-built here.
        The read service rather than the repository, because what the summary
        wants is the *listing*: its window, its exclusions and its order, none
        of which live in SQL.

        ``UpcomingImportantDatesService`` comes from ``ContactProvider`` on the
        same reasoning and at no graph cost: every container that registers
        ``JournalProvider`` already registers ``ContactProvider``, which
        ``ContactProvider`` itself requires anyway because it resolves
        ``JournalDateResolver`` from here. The service rather than the two
        repositories, because what the summary wants is the *answer*: the
        recurrence rule, the leap-day candidate and the importance ranking, none
        of which live in either statement alone.
        """
        return DailySummaryInputAssembler(
            journal_repo=journal_repo,
            mood_repo=mood_repo,
            contact_relationship_repo=contact_relationship_repo,
            summary_repo=summary_repo,
            series_repo=series_repo,
            agenda_repo=agenda_repo,
            task_read_service=task_read_service,
            upcoming_dates_service=upcoming_dates_service,
        )

    @provide(scope=Scope.REQUEST)
    def daily_summary_service(
        self,
        input_assembler: DailySummaryInputAssembler,
        eligibility_checker: DailySummaryEligibilityChecker,
        freshness_checker: DailySummaryFreshnessChecker,
        prompt_builder: DailySummaryPromptBuilder,
        summary_repo: JournalDailySummaryRepository,
        user_settings_repo: UserSettingsRepository,
        settings: Settings,
        container: AsyncContainer,
    ) -> DailySummaryService:
        """Provide a DailySummaryService instance.

        ``container`` is the request-scoped Dishka container, passed through so
        the service can expose it to the read-only MCP tools Gemini may call
        during summary generation (via ``mcp_background_container``).
        """
        return DailySummaryService(
            input_assembler=input_assembler,
            eligibility_checker=eligibility_checker,
            prompt_builder=prompt_builder,
            summary_repo=summary_repo,
            gemini_api_key=settings.gemini_api_key,
            gemini_model=settings.gemini_summary_model,
            user_settings_repo=user_settings_repo,
            container=container,
            freshness_checker=freshness_checker,
            _gemini_response_override=(
                json.dumps({"summary_text": DAILY_SUMMARY_STUB_TEXT})
                if settings.enable_test_daily_summary_stub
                else None
            ),
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
    def activity_type_index_calculator(self) -> ActivityTypeIndexCalculator:
        """Provide an ActivityTypeIndexCalculator instance."""
        return ActivityTypeIndexCalculator()

    @provide(scope=Scope.REQUEST)
    def logbook_data_service(
        self,
        repository: LogbookExportRepository,
        summary_calculator: LogbookSummaryCalculator,
        participant_calculator: ParticipantIndexCalculator,
        activity_type_calculator: ActivityTypeIndexCalculator,
    ) -> LogbookDataService:
        """Provide a LogbookDataService instance."""
        return LogbookDataService(
            repository=repository,
            summary_calculator=summary_calculator,
            participant_calculator=participant_calculator,
            activity_type_calculator=activity_type_calculator,
        )

    @provide(scope=Scope.APP)
    def logbook_pdf_renderer(self) -> LogbookPdfRenderer:
        """Provide a LogbookPdfRenderer instance."""
        return LogbookPdfRenderer()

    @provide(scope=Scope.APP)
    def logbook_tile_source(self, settings: Settings) -> TileSource:
        """Provide the outdoor-logbook basemap tile source (ITER16-004).

        APP scope so the on-disk cache and fetch throttle are shared across the
        whole export batch and across requests, keeping tile fetching within
        OSM's usage policy.
        """
        return OsmTileSource(
            base_url=settings.logbook_tile_base_url,
            user_agent=settings.logbook_tile_user_agent,
            cache_dir=settings.logbook_tile_cache_dir,
            tiles_per_second=settings.logbook_tile_throttle_per_second,
        )

    @provide(scope=Scope.APP)
    def gpx_map_renderer(self, tile_source: TileSource) -> GpxMapRenderer:
        """Provide the outdoor-logbook GPX map-image renderer (ITER16-004).

        APP scope like the tile source it wraps: it holds no per-request state,
        and sharing it keeps the tile cache and throttle shared batch-wide.
        """
        return GpxMapRenderer(tile_source)

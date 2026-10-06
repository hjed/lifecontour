"""Building ``JournalEnrichmentService`` over a test connection.

The service reads through two dozen repositories; the core and MCP read tests
both build it here rather than each carrying the list.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.abseil_pitch_repository import (
    SqlAbseilPitchRepository,
)
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
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
from app.core.journal.adapters.sql.diving_data_repository import (
    SqlDivingDataRepository,
)
from app.core.journal.adapters.sql.downhill_skiing_data_repository import (
    SqlDownhillSkiingDataRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.gear_maintenance_data_repository import (
    SqlGearMaintenanceDataRepository,
)
from app.core.journal.adapters.sql.gear_usage_data_repository import (
    SqlGearUsageDataRepository,
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
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)
from app.core.journal.adapters.sql.outdoor_planning_data_repository import (
    SqlOutdoorPlanningDataRepository,
)
from app.core.journal.adapters.sql.outdoor_training_data_repository import (
    SqlOutdoorTrainingDataRepository,
)
from app.core.journal.adapters.sql.plan_data_repository import SqlPlanDataRepository
from app.core.journal.adapters.sql.snorkelling_data_repository import (
    SqlSnorkellingDataRepository,
)
from app.core.journal.adapters.sql.travel_data_repository import (
    SqlTravelDataRepository,
)
from app.core.journal.services.journal_enrichment_service import (
    JournalEnrichmentService,
    JournalTypeDataRepositories,
)


def enrichment_service_for(conn: AsyncConnection) -> JournalEnrichmentService:
    """The enrichment service over SQL repositories sharing ``conn``."""
    return JournalEnrichmentService(
        type_data_repos=JournalTypeDataRepositories(
            calendar_info_repo=SqlCalendarInfoRepository(conn),
            mood_data_repo=SqlMoodDataRepository(conn),
            plan_data_repo=SqlPlanDataRepository(conn),
            travel_data_repo=SqlTravelDataRepository(conn),
            photo_album_data_repo=AlbumSyncReadRepository(conn),
            fitness_data_repo=SqlFitnessDataRepository(conn),
            outdoor_activity_data_repo=SqlOutdoorActivityDataRepository(conn),
            bushwalking_data_repo=SqlBushwalkingDataRepository(conn),
            jogging_data_repo=SqlJoggingDataRepository(conn),
            abseiling_data_repo=SqlAbseilingDataRepository(conn),
            caving_data_repo=SqlCavingDataRepository(conn),
            canyoning_data_repo=SqlCanyoningDataRepository(conn),
            climbing_data_repo=SqlClimbingDataRepository(conn),
            kayaking_data_repo=SqlKayakingDataRepository(conn),
            cross_country_skiing_data_repo=SqlCrossCountrySkiingDataRepository(conn),
            canoeing_data_repo=SqlCanoeingDataRepository(conn),
            snorkelling_data_repo=SqlSnorkellingDataRepository(conn),
            diving_data_repo=SqlDivingDataRepository(conn),
            downhill_skiing_data_repo=SqlDownhillSkiingDataRepository(conn),
            outdoor_planning_data_repo=SqlOutdoorPlanningDataRepository(conn),
            outdoor_training_data_repo=SqlOutdoorTrainingDataRepository(conn),
            gear_maintenance_data_repo=SqlGearMaintenanceDataRepository(conn),
            gear_usage_data_repo=SqlGearUsageDataRepository(conn),
            abseil_pitch_repo=SqlAbseilPitchRepository(conn),
        ),
        journal_repo=SqlJournalRepository(conn),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(conn),
        contact_repo=SqlContactRepository(conn),
        tag_repo=SqlJournalTagRepository(conn),
        series_repo=SqlJournalSeriesRepository(conn),
        calendar_repo=SqlCalendarRepository(conn),
    )

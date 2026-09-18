"""Helpers shared by the journal MCP tool modules.

The repository bundle the tools read journals through, and the conversions
and argument parsing more than one tool module needs.
"""

import dataclasses
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

from core_shared.models.journals import (
    Journal,
    JournalType,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
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
from app.core.journal.adapters.sql.gear_item_repository import (
    SqlGearItemRepository,
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
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.adapters.sql.snorkelling_data_repository import (
    SqlSnorkellingDataRepository,
)
from app.core.journal.adapters.sql.travel_data_repository import SqlTravelDataRepository
from app.core.journal.models.activity_stats import (
    ActivityJournalRow,
)
from app.core.journal.services.journal_type_data_reader import (
    read_journal_types_and_data,
)
from app.mcp.domains.journals.schemas import (
    ContactRelationshipSummary,
    EventDateRangeSchema,
    JournalSearchResult,
)


@dataclasses.dataclass(frozen=True)
class JournalToolRepositories:
    """Concrete SQL repositories used by journal MCP tools."""

    journal_repo: SqlJournalRepository
    calendar_info_repo: SqlCalendarInfoRepository
    mood_data_repo: SqlMoodDataRepository
    plan_data_repo: SqlPlanDataRepository
    travel_data_repo: SqlTravelDataRepository
    photo_album_data_repo: AlbumSyncReadRepository
    fitness_data_repo: SqlFitnessDataRepository
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository
    bushwalking_data_repo: SqlBushwalkingDataRepository
    jogging_data_repo: SqlJoggingDataRepository
    abseiling_data_repo: SqlAbseilingDataRepository
    canyoning_data_repo: SqlCanyoningDataRepository
    caving_data_repo: SqlCavingDataRepository
    climbing_data_repo: SqlClimbingDataRepository
    kayaking_data_repo: SqlKayakingDataRepository
    cross_country_skiing_data_repo: SqlCrossCountrySkiingDataRepository
    canoeing_data_repo: SqlCanoeingDataRepository
    snorkelling_data_repo: SqlSnorkellingDataRepository
    diving_data_repo: SqlDivingDataRepository
    downhill_skiing_data_repo: SqlDownhillSkiingDataRepository
    outdoor_planning_data_repo: SqlOutdoorPlanningDataRepository
    outdoor_training_data_repo: SqlOutdoorTrainingDataRepository
    gear_maintenance_data_repo: SqlGearMaintenanceDataRepository
    gear_usage_data_repo: SqlGearUsageDataRepository
    route_repo: SqlRouteRepository
    contact_relationship_repo: SqlJournalContactRelationshipRepository
    contact_repo: SqlContactRepository
    tag_repo: SqlJournalTagRepository
    activity_template_repo: SqlActivityTemplateRepository
    gear_item_repo: SqlGearItemRepository


def create_journal_tool_repositories(
    db_connection: AsyncConnection,
) -> JournalToolRepositories:
    """Build the concrete repositories needed by journal MCP tools."""

    return JournalToolRepositories(
        journal_repo=SqlJournalRepository(db_connection),
        calendar_info_repo=SqlCalendarInfoRepository(db_connection),
        mood_data_repo=SqlMoodDataRepository(db_connection),
        plan_data_repo=SqlPlanDataRepository(db_connection),
        travel_data_repo=SqlTravelDataRepository(db_connection),
        photo_album_data_repo=AlbumSyncReadRepository(db_connection),
        fitness_data_repo=SqlFitnessDataRepository(db_connection),
        outdoor_activity_data_repo=SqlOutdoorActivityDataRepository(db_connection),
        bushwalking_data_repo=SqlBushwalkingDataRepository(db_connection),
        jogging_data_repo=SqlJoggingDataRepository(db_connection),
        abseiling_data_repo=SqlAbseilingDataRepository(db_connection),
        canyoning_data_repo=SqlCanyoningDataRepository(db_connection),
        caving_data_repo=SqlCavingDataRepository(db_connection),
        climbing_data_repo=SqlClimbingDataRepository(db_connection),
        kayaking_data_repo=SqlKayakingDataRepository(db_connection),
        cross_country_skiing_data_repo=SqlCrossCountrySkiingDataRepository(
            db_connection
        ),
        canoeing_data_repo=SqlCanoeingDataRepository(db_connection),
        snorkelling_data_repo=SqlSnorkellingDataRepository(db_connection),
        diving_data_repo=SqlDivingDataRepository(db_connection),
        downhill_skiing_data_repo=SqlDownhillSkiingDataRepository(db_connection),
        outdoor_planning_data_repo=SqlOutdoorPlanningDataRepository(db_connection),
        outdoor_training_data_repo=SqlOutdoorTrainingDataRepository(db_connection),
        gear_maintenance_data_repo=SqlGearMaintenanceDataRepository(db_connection),
        gear_usage_data_repo=SqlGearUsageDataRepository(db_connection),
        route_repo=SqlRouteRepository(db_connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(
            db_connection
        ),
        contact_repo=SqlContactRepository(db_connection),
        tag_repo=SqlJournalTagRepository(db_connection),
        activity_template_repo=SqlActivityTemplateRepository(db_connection),
        gear_item_repo=SqlGearItemRepository(db_connection),
    )


def journal_to_search_result(
    journal: Journal, *, types: list[str] | None = None, summary: str | None = None
) -> JournalSearchResult:
    """
    Convert a Journal entity to a JournalSearchResult.

    Args:
        journal: The journal entity to convert

    Returns:
        JournalSearchResult with basic journal information
    """
    return JournalSearchResult(
        id=journal.id or 0,
        title=journal.title,
        content_excerpt=journal.content[:200] + "..."
        if len(journal.content) > 200
        else journal.content,
        event_date_range=EventDateRangeSchema(
            start=journal.event_date_range.start,
            end=journal.event_date_range.end,
        ),
        types=types or [],
        tags=[],
        highlighted={},
        summary=summary or f"Journal: {journal.title}",
    )


def parse_type_filters(types: str | None) -> list[str]:
    """Parse and validate comma-separated journal types."""
    if not types:
        return []

    parsed_types: list[str] = []
    for raw_type in types.split(","):
        normalized = raw_type.strip().lower()
        if not normalized:
            continue
        try:
            journal_type = JournalType(normalized)
        except ValueError as exc:
            allowed_types = ", ".join(
                sorted(journal_type.value for journal_type in JournalType)
            )
            raise ValueError(
                f"Invalid journal type '{raw_type.strip()}'. Must be one of: {allowed_types}"
            ) from exc
        if journal_type.value not in parsed_types:
            parsed_types.append(journal_type.value)

    return parsed_types


def parse_optional_datetime_filter(
    value: str | None, field_name: str, *, is_end: bool = False
) -> datetime | None:
    """Validate ISO date/datetime filter strings and normalize to aware datetimes."""
    if value is None:
        return None

    normalized = value.strip()
    try:
        if "T" not in normalized:
            parsed_date = date.fromisoformat(normalized)
            parsed_datetime = datetime.combine(
                parsed_date,
                dt_time.max if is_end else dt_time.min,
                tzinfo=UTC,
            )
        else:
            parsed_datetime = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field_name} '{value}'. Must be a valid ISO date or datetime."
        ) from exc

    return (
        parsed_datetime
        if parsed_datetime.tzinfo
        else parsed_datetime.replace(tzinfo=UTC)
    )


async def fetch_types_for_journal(
    journal_id: int, repos: JournalToolRepositories
) -> tuple[list[str], dict[str, Any]]:
    """Fetch the concrete types and type-specific data for a journal."""
    return await read_journal_types_and_data(journal_id, repos)


async def fetch_parent_journal(
    journal: Journal, journal_repo: SqlJournalRepository, user_id: str
) -> Journal | None:
    """Resolve the parent a journal hangs off, for the ``parent`` response field.

    Every tool that returns a journal resolves the parent through here, so a
    persisted ``parent_id`` cannot show up on one response and be missing from
    the next — a read that omitted it made ``parent_id`` look ignored on create
    even though the link was written.

    The lookup is owner-scoped: somebody else's journal is reported as absent
    rather than having its title read back to the caller (#1267).
    """
    if journal.parent_id is None:
        return None
    return await journal_repo.find_by_id_for_user(journal.parent_id, str(user_id))


async def build_search_results(
    journals: list[Journal],
    repos: JournalToolRepositories,
    *,
    activity_rows_by_id: dict[int, ActivityJournalRow] | None = None,
) -> list[JournalSearchResult]:
    """Build AI-friendly journal search results with concrete types included."""
    results: list[JournalSearchResult] = []
    for journal in journals:
        if journal.id is None:
            continue
        types, _ = await fetch_types_for_journal(journal.id, repos)
        activity_row = (
            activity_rows_by_id.get(journal.id)
            if activity_rows_by_id is not None
            else None
        )
        summary = None
        if activity_row is not None:
            activity_label = activity_row.activity_type.replace("_", " ")
            summary = (
                f"{activity_label.title()} activity '{journal.title}' covering "
                f"{activity_row.distance}m in {activity_row.duration}s"
            )
        results.append(journal_to_search_result(journal, types=types, summary=summary))
    return results


async def fetch_contact_relationships_with_names(
    journal_id: int,
    contact_relationship_repo: SqlJournalContactRelationshipRepository,
    contact_repo: SqlContactRepository,
) -> list[ContactRelationshipSummary]:
    """
    Fetch contact relationships with contact names for a journal.

    Args:
        journal_id: The journal ID to fetch relationships for
        contact_relationship_repo: Contact relationship repository
        contact_repo: Contact repository

    Returns:
        List of ContactRelationshipSummary objects
    """
    contact_relationships = await contact_relationship_repo.get_by_journal(journal_id)

    contacts: list[ContactRelationshipSummary] = []
    for rel in contact_relationships:
        contact = await contact_repo.find_by_id(rel.contact_id)
        if contact:
            contact_name = f"{contact.first_name} {contact.last_name}".strip()
            if not contact_name:
                contact_name = f"Contact {rel.contact_id}"

            contacts.append(
                ContactRelationshipSummary(
                    id=rel.contact_id,
                    name=contact_name,
                    relationship_type=rel.relationship_type.value,
                    status=rel.status.value if rel.status else None,
                    role=rel.role.value if rel.role else None,
                )
            )

    return contacts

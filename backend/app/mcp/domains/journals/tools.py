"""
Journal domain MCP tools.

Provides AI access to journal management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
"""

import dataclasses
import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from typing import Annotated, Any, NamedTuple
from uuid import UUID

import structlog
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    AbseilingData,
    ActivityTemplate,
    BushwalkingData,
    Calendar,
    CalendarInfo,
    CanyoningData,
    ClimbingData,
    CrossCountrySkiingData,
    EventDateRange,
    FitnessData,
    GearItem,
    JoggingData,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    JournalNotFoundError,
    JournalType,
    JournalValidationError,
    KayakingData,
    MoodData,
    OutdoorActivityData,
    PlanData,
    TemplatePitch,
    TravelData,
)
from core_shared.models.journals.constants import (
    VALID_ANCHOR_LOCATIONS,
    VALID_ANCHOR_TYPES,
    VALID_CANYON_TYPES,
    VALID_CLIMBING_TYPES,
    VALID_MAINTENANCE_TYPES,
    VALID_PITCH_TYPES,
    VALID_RAPIDS_GRADES,
    VALID_TEMPLATE_TYPES,
    VALID_TRACK_GRADES,
)
from fastmcp import FastMCP
from meilisearch.errors import MeilisearchError
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry
from app.core.history.services.journal_history_service import JournalHistoryService
from app.core.integrations.external_link_helpers import (
    ExternalLinkInfo,
    build_journal_external_links,
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
from app.core.journal.adapters.sql.review_item_repository import SqlReviewItemRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.adapters.sql.snorkelling_data_repository import (
    SqlSnorkellingDataRepository,
)
from app.core.journal.adapters.sql.travel_data_repository import SqlTravelDataRepository
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.services.activity_template_service import (
    ActivityTemplateService,
)
from app.core.journal.services.calendar_service import CalendarService
from app.core.journal.services.daily_summary_service import DailySummaryService
from app.core.journal.services.gear_item_service import GearItemService
from app.core.journal.services.hierarchy_service import HierarchyNode, HierarchyService
from app.core.journal.services.incomplete_outdoor_activity_service import (
    IncompleteOutdoorActivityService,
)
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.outdoor_activity_dismissal_service import (
    OutdoorActivityDismissalService,
)
from app.core.journal.services.outdoor_dashboard_service import (
    OutdoorDashboardService,
)
from app.core.journal.services.review_item_service import ReviewItemService
from app.core.search.exceptions import SearchServiceUnavailableError
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.search.search_service import SearchService
from app.mcp.domains.journals.converters import (
    ActivityTemplateMCPConverter,
    GearItemMCPConverter,
    JournalConverter,
)
from app.mcp.domains.journals.schemas import (
    ActivityPersonalRecord,
    ActivityStatsResponse,
    ActivityTotals,
    ActivityTrendPeriod,
    ActivityTrendsResponse,
    ActivityTypeStats,
    CanyonType,
    CheckedOutGearMCPEntry,
    ClimbingType,
    ContactRelationshipSummary,
    DailySummaryMCPResponse,
    EventDateRangeSchema,
    IncompleteOutdoorActivitiesMCPResponse,
    IncompleteOutdoorActivityMCPEntry,
    JournalCreateRequest,
    JournalDateWindowResponse,
    JournalHierarchyNode,
    JournalHierarchyResponse,
    JournalHistoryEntry,
    JournalHistoryResponse,
    JournalSearchResponse,
    JournalSearchResult,
    JournalTagInfo,
    JournalTagListMCPResponse,
    JournalTemplateMCPResponse,
    JournalUpdateRequest,
    MergeCandidateResult,
    MergeCandidatesResponse,
    MergeJournalMCPRequest,
    OutdoorActivityDismissalMCPResponse,
    OutdoorDashboardMCPResponse,
    RouteHistoryEntry,
    RouteHistoryResponse,
    RouteSummary,
    SearchDiagnostics,
    TemplateDoneMCPEntry,
    TemplatePitchInput,
    TemplateType,
    UpcomingOutdoorActivityMCPEntry,
    build_dashboard_summary,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_activity_template_service,
    get_async_connection,
    get_calendar_service,
    get_current_user_id,
    get_daily_summary_service,
    get_gear_item_service,
    get_incomplete_outdoor_activity_service,
    get_journal_contact_service,
    get_journal_tag_service,
    get_journal_write_service,
    get_outbox_event_publisher,
    get_outdoor_activity_dismissal_service,
    get_outdoor_dashboard_service,
    get_review_item_service,
    get_search_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder

logger = structlog.get_logger()


@dataclasses.dataclass(frozen=True)
class _JournalToolRepositories:
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


@dataclasses.dataclass(frozen=True)
class _ActivityJournalRow:
    """Activity journal row enriched with resolved activity metrics."""

    journal: Journal
    activity_type: str
    distance: int
    duration: int
    elevation_gain: int
    calories: int


_ACTIVITY_TYPE_PRECEDENCE: tuple[JournalType, ...] = (
    JournalType.CANYONING,
    JournalType.CAVING,
    JournalType.CROSS_COUNTRY_SKIING,
    JournalType.KAYAKING,
    JournalType.CLIMBING,
    JournalType.ABSEILING_TRIP,
    JournalType.BUSHWALKING,
    JournalType.JOGGING,
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
)


def _create_journal_tool_repositories(
    db_connection: AsyncConnection,
) -> _JournalToolRepositories:
    """Build the concrete repositories needed by journal MCP tools."""

    return _JournalToolRepositories(
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


def _journal_to_search_result(
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


def _parse_type_filters(types: str | None) -> list[str]:
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


def _parse_activity_type_filter(activity_type: str | None) -> str | None:
    """Parse and validate an effective activity type filter."""
    if activity_type is None:
        return None

    normalized = activity_type.strip().lower()
    allowed_types = {journal_type.value for journal_type in _ACTIVITY_TYPE_PRECEDENCE}
    if normalized not in allowed_types:
        allowed = ", ".join(sorted(allowed_types))
        raise ValueError(
            f"Invalid activity_type '{activity_type}'. Must be one of: {allowed}"
        )
    return normalized


# Valid integration sources for journal filtering
_VALID_INTEGRATION_SOURCES = {
    "strava",
    "google_calendar",
    "snipeit",
    "snipeit_maintenance",
    "immich_album",
}


def _parse_integration_source_filter(value: str | None) -> str | None:
    """Parse and validate an integration source filter.

    Args:
        value: Integration source string, or None.

    Returns:
        Normalised integration source string, or None.

    Raises:
        ValueError: If the value is not a recognised integration source.
    """
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized not in _VALID_INTEGRATION_SOURCES:
        allowed = ", ".join(sorted(_VALID_INTEGRATION_SOURCES))
        raise ValueError(
            f"Invalid integration_source '{value}'. Must be one of: {allowed}"
        )
    return normalized


def _parse_optional_datetime_filter(
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


def _journal_from_row(row: Any) -> Journal:
    """Build a journal entity from a SQL result row."""
    return Journal(
        id=row.id,
        user_id=row.user_id,
        title=row.title,
        content=row.content,
        event_date_range=EventDateRange(
            start=row.event_date_range_start,
            end=row.event_date_range_end,
        ),
        parent_id=row.parent_id,
        order=row.journal_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _activity_row_from_row(row: Any) -> _ActivityJournalRow:
    """Build an activity journal row from a SQL result row."""
    return _ActivityJournalRow(
        journal=_journal_from_row(row),
        activity_type=row.activity_type,
        distance=int(row.distance or 0),
        duration=int(row.duration or 0),
        elevation_gain=int(row.elevation_gain or 0),
        calories=int(row.calories or 0),
    )


async def _fetch_types_for_journal(
    journal_id: int, repos: _JournalToolRepositories
) -> tuple[list[str], dict[str, Any]]:
    """Fetch the concrete types and type-specific data for a journal."""
    return await _fetch_journal_types_and_data(journal_id, repos)


async def _fetch_parent_journal(
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


def _external_links_preserved(
    before: list[ExternalLinkInfo], after: list[ExternalLinkInfo]
) -> bool | None:
    """Whether every pre-update link survived; None when there were none."""
    if not before:
        return None
    before_keys = {(link.source, link.external_id) for link in before}
    after_keys = {(link.source, link.external_id) for link in after}
    return before_keys <= after_keys


async def _fetch_journal_external_links(
    journal_id: int,
    db_connection: AsyncConnection,
    user_id: str,
) -> list[ExternalLinkInfo]:
    """Fetch external system links for a journal.

    Fetches Strava activity links, Google Calendar links from
    journal_external_event_links, and Snipe-IT / Immich links, then builds
    ExternalLinkInfo objects using the shared helper.

    Args:
        journal_id: The journal ID to fetch links for
        db_connection: Database connection for the link queries
        user_id: The user ID to filter Snipe-IT sync metadata links

    Returns:
        List of ExternalLinkInfo objects for the journal.
    """
    from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

    journal_repo = SqlJournalRepository(db_connection)

    # Every Strava activity linked to the journal — an additively merged
    # journal carries more than one.
    strava_activity_ids = await journal_repo.get_strava_activity_ids(journal_id)

    snipeit_links = await journal_repo.get_snipeit_links(journal_id, user_id)

    # Fetch Immich album links and the user's Immich server URL (reusing the
    # canonical read-only server-URL accessor — no API-key decryption).
    from app.mcp.shared.dependencies import get_immich_token_service

    immich_album_links = await journal_repo.get_immich_album_links(journal_id)
    immich_token_service = await get_immich_token_service()
    immich_server_url = await immich_token_service.get_server_url(user_id)

    # Fetch Google Calendar external event links
    result = await db_connection.execute(
        text(
            "SELECT l.external_event_id, c.google_calendar_id, l.calendar_id "
            "FROM journal_external_event_links l "
            "JOIN calendars c ON l.calendar_id = c.id "
            "WHERE l.journal_id = :journal_id "
            "AND l.external_event_id IS NOT NULL "
            "AND trim(l.external_event_id) != '' "
            "AND c.google_calendar_id IS NOT NULL"
        ),
        {"journal_id": journal_id},
    )
    external_event_links = [
        {
            "external_event_id": row[0],
            "calendar_id": str(row[1]) if row[1] else None,
            "internal_calendar_id": str(row[2]) if row[2] else None,
        }
        for row in result
    ]

    return build_journal_external_links(
        strava_activity_ids=strava_activity_ids,
        external_event_links=external_event_links,
        snipeit_links=snipeit_links,
        immich_album_links=immich_album_links,
        immich_server_url=immich_server_url,
    )


async def _find_journal_id_by_external_id(
    db_connection: AsyncConnection,
    user_id: str,
    integration_source: str,
    external_id: str,
) -> int | None:
    """Resolve the user's journal linked to ``(integration_source, external_id)``.

    Mirrors the per-source link stores used by
    :func:`_fetch_journal_ids_by_integration_source`, keyed on the external id.
    """
    if integration_source == "strava":
        result = await db_connection.execute(
            text(
                "SELECT m.internal_id AS journal_id "
                "FROM sync_metadata m JOIN journals j ON j.id = m.internal_id "
                "WHERE m.integration_source = 'strava' "
                "AND m.internal_entity_type = 'journal' "
                "AND m.external_id = :external_id AND j.user_id = :user_id "
                "UNION "
                "SELECT f.journal_id FROM journal_fitness_data f "
                "JOIN journals j ON f.journal_id = j.id "
                "WHERE f.strava_activity_id = :external_id AND j.user_id = :user_id "
                "ORDER BY journal_id LIMIT 1"
            ),
            {"external_id": external_id, "user_id": user_id},
        )
    elif integration_source == "google_calendar":
        result = await db_connection.execute(
            text(
                "SELECT l.journal_id FROM journal_external_event_links l "
                "JOIN journals j ON l.journal_id = j.id "
                "JOIN calendars c ON l.calendar_id = c.id "
                "WHERE l.external_event_id = :external_id "
                "AND j.user_id = :user_id AND c.google_calendar_id IS NOT NULL "
                "ORDER BY l.journal_id LIMIT 1"
            ),
            {"external_id": external_id, "user_id": user_id},
        )
    elif integration_source in ("snipeit", "snipeit_maintenance", "snipeit_checkout"):
        mapped_source = (
            "snipeit_checkout"
            if integration_source == "snipeit"
            else integration_source
        )
        result = await db_connection.execute(
            text(
                "SELECT CAST(m.internal_uuid AS INTEGER) AS journal_id "
                "FROM sync_metadata m "
                "JOIN journals j ON j.id = CAST(m.internal_uuid AS INTEGER) "
                "WHERE m.integration_source = :integration_source "
                "AND m.external_id = :external_id AND j.user_id = :user_id "
                "ORDER BY journal_id LIMIT 1"
            ),
            {
                "integration_source": mapped_source,
                "external_id": external_id,
                "user_id": user_id,
            },
        )
    elif integration_source == "immich_album":
        result = await db_connection.execute(
            text(
                "SELECT m.internal_id AS journal_id FROM sync_metadata m "
                "JOIN journals j ON j.id = m.internal_id "
                "WHERE m.integration_source = 'immich_album' "
                "AND m.external_id = :external_id AND j.user_id = :user_id "
                "ORDER BY journal_id LIMIT 1"
            ),
            {"external_id": external_id, "user_id": user_id},
        )
    else:
        return None
    row = result.fetchone()
    return int(row[0]) if row and row[0] is not None else None


async def _fetch_journal_ids_by_integration_source(
    db_connection: AsyncConnection,
    user_id: str,
    integration_source: str,
) -> set[int]:
    """Fetch journal IDs linked to a specific integration source.

    Args:
        db_connection: Database connection
        user_id: The user ID to filter by
        integration_source: 'strava', 'google_calendar', 'snipeit', 'snipeit_maintenance', 'snipeit_checkout', or 'immich_album'

    Returns:
        Set of journal IDs linked to the specified source.
    """
    if integration_source == "strava":
        result = await db_connection.execute(
            text(
                "SELECT f.journal_id "
                "FROM journal_fitness_data f "
                "JOIN journals j ON f.journal_id = j.id "
                "WHERE f.strava_activity_id IS NOT NULL "
                "AND trim(f.strava_activity_id) != '' "
                "AND j.user_id = :user_id"
            ),
            {"user_id": user_id},
        )
    elif integration_source == "google_calendar":
        result = await db_connection.execute(
            text(
                "SELECT DISTINCT l.journal_id "
                "FROM journal_external_event_links l "
                "JOIN journals j ON l.journal_id = j.id "
                "JOIN calendars c ON l.calendar_id = c.id "
                "WHERE j.user_id = :user_id "
                "AND l.external_event_id IS NOT NULL "
                "AND trim(l.external_event_id) != '' "
                "AND c.google_calendar_id IS NOT NULL"
            ),
            {"user_id": user_id},
        )
    elif integration_source in ("snipeit", "snipeit_maintenance", "snipeit_checkout"):
        mapped_source = (
            "snipeit_checkout"
            if integration_source == "snipeit"
            else integration_source
        )
        result = await db_connection.execute(
            text(
                "SELECT CAST(internal_uuid AS INTEGER) AS journal_id "
                "FROM sync_metadata "
                "WHERE integration_source = :integration_source "
                "AND internal_uuid IS NOT NULL"
            ),
            {"integration_source": mapped_source},
        )
    elif integration_source == "immich_album":
        # Immich albums track the journal via the integer internal_id (not the
        # UUID column used by Snipe-IT), so join journals to scope by user.
        result = await db_connection.execute(
            text(
                "SELECT m.internal_id AS journal_id "
                "FROM sync_metadata m "
                "JOIN journals j ON j.id = m.internal_id "
                "WHERE m.integration_source = 'immich_album' "
                "AND m.internal_id IS NOT NULL "
                "AND j.user_id = :user_id"
            ),
            {"user_id": user_id},
        )
    else:
        return set()

    return {row[0] for row in result}


async def _build_search_results(
    journals: list[Journal],
    repos: _JournalToolRepositories,
    *,
    activity_rows_by_id: dict[int, _ActivityJournalRow] | None = None,
) -> list[JournalSearchResult]:
    """Build AI-friendly journal search results with concrete types included."""
    results: list[JournalSearchResult] = []
    for journal in journals:
        if journal.id is None:
            continue
        types, _ = await _fetch_types_for_journal(journal.id, repos)
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
        results.append(_journal_to_search_result(journal, types=types, summary=summary))
    return results


async def _build_hierarchy_node(
    node: HierarchyNode, repos: _JournalToolRepositories
) -> JournalHierarchyNode:
    """Build an AI-friendly hierarchy node from a HierarchyNode."""
    assert node.journal.id is not None, "Hierarchy node journal must have an ID"
    types, _ = await _fetch_types_for_journal(node.journal.id, repos)
    children = []
    for child_node in node.children:
        children.append(await _build_hierarchy_node(child_node, repos))

    return JournalHierarchyNode(
        id=node.journal.id or 0,
        title=node.journal.title,
        content_excerpt=node.journal.content[:200] + "..."
        if len(node.journal.content) > 200
        else node.journal.content,
        event_date_range=EventDateRangeSchema(
            start=node.journal.event_date_range.start,
            end=node.journal.event_date_range.end,
        ),
        types=types,
        tags=[],
        highlighted={},
        summary=f"Hierarchical Journal: {node.journal.title}",
        depth=node.depth,
        children_count=node.children_count,
        children=children,
    )


def _build_activity_query_filters(
    user_id: str,
    *,
    search_query: str | None = None,
    activity_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Build shared parameters and filters for activity journal queries."""
    normalized_activity_type = _parse_activity_type_filter(activity_type)
    start_date_filter = _parse_optional_datetime_filter(start_date, "start_date")
    end_date_filter = _parse_optional_datetime_filter(end_date, "end_date", is_end=True)

    params: dict[str, Any] = {"user_id": user_id}
    where_clauses: list[str] = []

    if search_query:
        params["search_pattern"] = f"%{search_query}%"
        where_clauses.append(
            "(title ILIKE :search_pattern OR content ILIKE :search_pattern)"
        )

    if normalized_activity_type is not None:
        params["activity_type"] = normalized_activity_type
        where_clauses.append("activity_type = :activity_type")

    if start_date_filter is not None:
        params["start_date"] = start_date_filter
        where_clauses.append("event_date_range_end >= :start_date")

    if end_date_filter is not None:
        params["end_date"] = end_date_filter
        where_clauses.append("event_date_range_start <= :end_date")

    return params, where_clauses


def _build_activity_rows_query_sql(
    where_clauses: list[str],
    *,
    select_sql: str,
    include_ordering: bool,
) -> str:
    """Build activity journal SQL with optional shared filters and ordering."""
    query_sql = f"""
        WITH activity_rows AS (
            SELECT
                j.id,
                j.user_id,
                j.title,
                j.content,
                j.event_date_range_start,
                j.event_date_range_end,
                j.parent_id,
                j."order" AS journal_order,
                j.created_at,
                j.updated_at,
                COALESCE(f.distance, 0) AS distance,
                COALESCE(f.duration, 0) AS duration,
                COALESCE(f.elevation_gain, 0) AS elevation_gain,
                COALESCE(f.calories, 0) AS calories,
                CASE
                    WHEN canyoning.journal_id IS NOT NULL THEN 'canyoning'
                    WHEN skiing.journal_id IS NOT NULL THEN 'cross_country_skiing'
                    WHEN kayaking.journal_id IS NOT NULL THEN 'kayaking'
                    WHEN climbing.journal_id IS NOT NULL THEN 'climbing'
                    WHEN abseiling.journal_id IS NOT NULL THEN 'abseiling_trip'
                    WHEN bushwalking.journal_id IS NOT NULL THEN 'bushwalking'
                    WHEN jogging.journal_id IS NOT NULL THEN 'jogging'
                    WHEN outdoor_activity.journal_id IS NOT NULL THEN 'outdoor_activity'
                    ELSE 'fitness'
                END AS activity_type
            FROM journals j
            INNER JOIN journal_fitness_data f ON f.journal_id = j.id
            LEFT JOIN journal_outdoor_activity_data outdoor_activity
                ON outdoor_activity.journal_id = j.id
            LEFT JOIN journal_bushwalking_data bushwalking
                ON bushwalking.journal_id = j.id
            LEFT JOIN journal_jogging_data jogging
                ON jogging.journal_id = j.id
            LEFT JOIN journal_abseiling_data abseiling
                ON abseiling.journal_id = j.id
            LEFT JOIN journal_canyoning_data canyoning
                ON canyoning.journal_id = j.id
            LEFT JOIN journal_climbing_data climbing
                ON climbing.journal_id = j.id
            LEFT JOIN journal_kayaking_data kayaking
                ON kayaking.journal_id = j.id
            LEFT JOIN journal_skiing_data skiing
                ON skiing.journal_id = j.id
            WHERE j.user_id = :user_id
        )
        {select_sql}
        FROM activity_rows
        """

    if where_clauses:
        query_sql += "\n        WHERE " + " AND ".join(where_clauses)

    if include_ordering:
        query_sql += "\n        ORDER BY event_date_range_start DESC, created_at DESC"

    return query_sql


async def _fetch_activity_rows(
    db_connection: AsyncConnection,
    user_id: str,
    *,
    search_query: str | None = None,
    activity_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[_ActivityJournalRow]:
    """Fetch activity journals with resolved effective activity types and metrics."""
    params, where_clauses = _build_activity_query_filters(
        user_id,
        search_query=search_query,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )
    query_sql = _build_activity_rows_query_sql(
        where_clauses,
        select_sql="SELECT *",
        include_ordering=True,
    )

    if limit is not None:
        params["limit"] = limit
        params["offset"] = offset
        query_sql += "\n        LIMIT :limit OFFSET :offset"

    result = await db_connection.execute(text(query_sql), params)
    return [_activity_row_from_row(row) for row in result.fetchall()]


async def _count_activity_rows(
    db_connection: AsyncConnection,
    user_id: str,
    *,
    search_query: str | None = None,
    activity_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """Count matching activity journals without materializing the full result set."""
    params, where_clauses = _build_activity_query_filters(
        user_id,
        search_query=search_query,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )
    query_sql = _build_activity_rows_query_sql(
        where_clauses,
        select_sql="SELECT COUNT(*)",
        include_ordering=False,
    )

    result = await db_connection.execute(text(query_sql), params)
    row = result.fetchone()
    if row is None:
        return 0
    count_value = row[0]
    return int(count_value) if count_value is not None else 0


async def _fetch_activity_overall_stats_row(
    db_connection: AsyncConnection,
    user_id: str,
    *,
    activity_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Any:
    """Fetch overall activity aggregate totals without materializing activity rows."""
    params, where_clauses = _build_activity_query_filters(
        user_id,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )
    query_sql = _build_activity_rows_query_sql(
        where_clauses,
        select_sql="""
        SELECT
            COUNT(*) AS total_activities,
            COALESCE(SUM(distance), 0) AS total_distance,
            COALESCE(SUM(duration), 0) AS total_duration,
            COALESCE(SUM(elevation_gain), 0) AS total_elevation_gain,
            COALESCE(SUM(calories), 0) AS total_calories
        """,
        include_ordering=False,
    )

    result = await db_connection.execute(text(query_sql), params)
    return result.fetchone()


async def _fetch_activity_type_stats_rows(
    db_connection: AsyncConnection,
    user_id: str,
    *,
    activity_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[Any]:
    """Fetch grouped activity-type aggregates in SQL."""
    params, where_clauses = _build_activity_query_filters(
        user_id,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )
    query_sql = _build_activity_rows_query_sql(
        where_clauses,
        select_sql="""
        SELECT
            activity_type,
            COUNT(*) AS count,
            COALESCE(SUM(distance), 0) AS total_distance,
            COALESCE(SUM(duration), 0) AS total_duration,
            COALESCE(SUM(elevation_gain), 0) AS total_elevation_gain,
            COALESCE(SUM(calories), 0) AS total_calories
        """,
        include_ordering=False,
    )
    query_sql += """
        GROUP BY activity_type
        ORDER BY activity_type
    """

    result = await db_connection.execute(text(query_sql), params)
    return list(result.fetchall())


async def _fetch_activity_personal_record_row(
    db_connection: AsyncConnection,
    user_id: str,
    *,
    metric_name: str,
    activity_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Any:
    """Fetch the top personal-record row for a metric in SQL."""
    if metric_name not in {"distance", "duration", "elevation_gain", "calories"}:
        raise ValueError(f"Unsupported activity metric '{metric_name}'")

    params, where_clauses = _build_activity_query_filters(
        user_id,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )
    query_sql = _build_activity_rows_query_sql(
        where_clauses,
        select_sql=f"""
        SELECT
            id AS journal_id,
            title AS journal_title,
            activity_type,
            {metric_name} AS metric_value,
            event_date_range_start,
            created_at
        """,
        include_ordering=False,
    )
    query_sql += f"""
        ORDER BY {metric_name} DESC, event_date_range_start DESC, created_at DESC
        LIMIT 1
    """

    result = await db_connection.execute(text(query_sql), params)
    return result.fetchone()


async def _fetch_activity_trend_rows(
    db_connection: AsyncConnection,
    user_id: str,
    *,
    interval: str,
    activity_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[Any]:
    """Fetch time-bucketed activity aggregates in SQL."""
    params, where_clauses = _build_activity_query_filters(
        user_id,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )
    params["interval_unit"] = interval
    query_sql = _build_activity_rows_query_sql(
        where_clauses,
        select_sql="""
        SELECT
            DATE_TRUNC(:interval_unit, event_date_range_start AT TIME ZONE 'UTC')::date AS period_start,
            COUNT(*) AS activity_count,
            COALESCE(SUM(distance), 0) AS total_distance,
            COALESCE(SUM(duration), 0) AS total_duration,
            COALESCE(SUM(elevation_gain), 0) AS total_elevation_gain
        """,
        include_ordering=False,
    )
    query_sql += """
        GROUP BY period_start
        ORDER BY period_start
    """

    result = await db_connection.execute(text(query_sql), params)
    return list(result.fetchall())


async def _fetch_route_history_rows(
    db_connection: AsyncConnection,
    user_id: str,
    route_id: UUID,
) -> list[Any]:
    """Fetch route usage rows across all route-aware activity tables."""
    query = text(
        """
        SELECT
            j.id,
            j.user_id,
            j.title,
            j.content,
            j.event_date_range_start,
            j.event_date_range_end,
            j.parent_id,
            j."order" AS journal_order,
            j.created_at,
            j.updated_at,
            f.distance,
            f.duration,
            'ROUTE' AS activity_type
        FROM journals j
        INNER JOIN routes r ON r.journal_id = j.id
        LEFT JOIN journal_fitness_data f ON f.journal_id = j.id
        WHERE j.user_id = :user_id
          AND r.id = :route_id
        ORDER BY j.event_date_range_start DESC, j.created_at DESC
        """
    )
    result = await db_connection.execute(
        query,
        {"user_id": user_id, "route_id": route_id},
    )
    return list(result.fetchall())


async def _fetch_contact_relationships_with_names(
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


def _build_calendar_data(calendar_info: Any) -> dict[str, Any]:
    """Build calendar event data dictionary."""
    return {
        "calendar_id": str(calendar_info.calendar_id),
        "start_time": calendar_info.start_time.isoformat()
        if calendar_info.start_time
        else None,
        "end_time": calendar_info.end_time.isoformat()
        if calendar_info.end_time
        else None,
        "is_all_day": calendar_info.is_all_day,
        "location": calendar_info.location,
        "description": calendar_info.description,
        "timezone": calendar_info.timezone,
        "sync_invitees": calendar_info.sync_invitees,
        "private_description": calendar_info.private_description,
        "event_state": calendar_info.event_state.value
        if hasattr(calendar_info.event_state, "value")
        else calendar_info.event_state,
    }


def _build_mood_data(mood_data: Any) -> dict[str, Any]:
    """Build mood rating data dictionary."""
    return {
        "mood_value": mood_data.mood_value,
        "mood_label": mood_data.mood_label,
        "energy_level": mood_data.energy_level,
    }


def _build_plan_data(plan_data: Any) -> dict[str, Any]:
    """Build plan data dictionary."""
    return {
        "documents": [
            {
                "title": doc.title,
                "url": doc.url,
                "description": doc.description,
            }
            for doc in plan_data.documents
        ]
        if plan_data.documents
        else [],
    }


def _build_travel_data(travel_data: Any) -> dict[str, Any]:
    """Build travel data dictionary."""
    return {
        "flights": [
            {
                "airline": flight.airline,
                "flight_number": flight.flight_number,
                "departure_airport": flight.departure_airport,
                "arrival_airport": flight.arrival_airport,
                "departure_time": flight.departure_time.isoformat()
                if flight.departure_time
                else None,
                "arrival_time": flight.arrival_time.isoformat()
                if flight.arrival_time
                else None,
                "booking_reference": flight.booking_reference,
            }
            for flight in travel_data.flights
        ]
        if travel_data.flights
        else [],
        "accommodations": [
            {
                "name": acc.name,
                "address": acc.address,
                "check_in_date": acc.check_in_date.isoformat()
                if acc.check_in_date
                else None,
                "check_out_date": acc.check_out_date.isoformat()
                if acc.check_out_date
                else None,
                "booking_reference": acc.booking_reference,
            }
            for acc in travel_data.accommodations
        ]
        if travel_data.accommodations
        else [],
        "transportation": [
            {
                "type": trans.type,
                "details": trans.details,
                "booking_reference": trans.booking_reference,
            }
            for trans in travel_data.transportation
        ]
        if travel_data.transportation
        else [],
    }


def _build_photo_album_data(photo_album_data: dict[str, Any]) -> dict[str, Any]:
    """Build photo album data dictionary from Immich album sync data.

    ``photo_album_data`` comes from ``AlbumSyncReadRepository.find_by_journal_id``
    and contains ``immich_album_id`` plus optional album display fields.
    """
    return dict(photo_album_data)


def _build_fitness_data(fitness_data: Any) -> dict[str, Any]:
    """Build fitness data dictionary."""
    return {
        "heart_rate_avg": fitness_data.heart_rate_avg,
        "heart_rate_max": fitness_data.heart_rate_max,
        "distance": fitness_data.distance,
        "elevation_gain": fitness_data.elevation_gain,
        "elevation_loss": fitness_data.elevation_loss,
        "duration": fitness_data.duration,
        "calories": fitness_data.calories,
        "strava_activity_id": fitness_data.strava_activity_id,
    }


def _build_outdoor_activity_data(outdoor_activity_data: Any) -> dict[str, Any]:
    """Build outdoor activity data dictionary."""
    return {
        "weather_conditions": outdoor_activity_data.weather_conditions,
        "role": outdoor_activity_data.role,
        "in_leadership_role": outdoor_activity_data.in_leadership_role,
        "participant_notes": outdoor_activity_data.participant_notes,
    }


def _build_bushwalking_data(bushwalking_data: Any) -> dict[str, Any]:
    """Build bushwalking data dictionary."""
    return {
        "track_grading": bushwalking_data.track_grading,
    }


def _build_jogging_data(jogging_data: Any) -> dict[str, Any]:
    """Build jogging data dictionary."""
    return {
        "pace": jogging_data.pace,
    }


def _build_abseiling_data(abseiling_data: Any) -> dict[str, Any]:
    """Build abseiling data dictionary."""
    return {
        "template_id": str(abseiling_data.template_id)
        if abseiling_data.template_id
        else None,
        "number_of_abseils": abseiling_data.number_of_abseils,
        "total_length": abseiling_data.total_length,
        "number_of_setups": abseiling_data.number_of_setups,
        "number_of_rescues": abseiling_data.number_of_rescues,
    }


def _build_caving_data(caving_data: Any) -> dict[str, Any]:
    """Build caving data dictionary."""
    return {
        "is_vertical": caving_data.is_vertical,
        "is_horizontal": caving_data.is_horizontal,
    }


def _build_canyoning_data(canyoning_data: Any) -> dict[str, Any]:
    """Build canyoning data dictionary."""
    return {
        "french_grade": canyoning_data.french_grade,
        "water_guage_name": canyoning_data.water_guage_name,
        "water_guage_level": canyoning_data.water_guage_level,
        "is_vertical": canyoning_data.is_vertical,
        "is_night_canyon": canyoning_data.is_night_canyon,
        "is_white_water": canyoning_data.is_white_water,
    }


def _build_climbing_data(climbing_data: Any) -> dict[str, Any]:
    """Build climbing data dictionary."""
    return {
        "climbing_type": climbing_data.climbing_type,
        "grade": climbing_data.grade,
        "length": climbing_data.length,
        "indoor": climbing_data.indoor,
    }


def _build_kayaking_data(kayaking_data: Any) -> dict[str, Any]:
    """Build kayaking data dictionary."""
    return {
        "water_type": kayaking_data.water_type,
        "is_white_water": kayaking_data.is_white_water,
        "rapids_grade": kayaking_data.rapids_grade,
    }


def _build_cross_country_skiing_data(
    cross_country_skiing_data: Any,
) -> dict[str, Any]:
    """Build cross-country skiing data dictionary."""
    return {
        "snow_conditions": cross_country_skiing_data.snow_conditions,
    }


_NOTE_IMPLIED_CONTEXT = (
    "NOTE was requested alongside other types; NOTE is implicit (a journal with "
    "no typed data) so it is not stored separately and will not appear in types."
)


def _note_implied_context(requested_types: list[str] | None) -> str:
    """Explain why NOTE is absent when it was requested with other types."""
    if not requested_types:
        return ""
    names = {t.upper() for t in requested_types}
    if JournalType.NOTE.name in names and len(names) > 1:
        return _NOTE_IMPLIED_CONTEXT
    return ""


def _build_canoeing_data(canoeing_data: Any) -> dict[str, Any]:
    """Build canoeing data dictionary."""
    return {"water_type": canoeing_data.water_type}


def _build_presence_only_data(_data: Any) -> dict[str, Any]:
    """Types whose row records membership only (no editable fields)."""
    return {}


def _build_outdoor_planning_data(outdoor_planning_data: Any) -> dict[str, Any]:
    """Build outdoor planning data dictionary."""
    return {
        "topics": outdoor_planning_data.topics,
        "activity_types": list(outdoor_planning_data.activity_types or []),
    }


def _build_outdoor_training_data(outdoor_training_data: Any) -> dict[str, Any]:
    """Build outdoor training data dictionary."""
    return {"focus_areas": list(outdoor_training_data.focus_areas or [])}


def _build_gear_maintenance_data(gear_maint_data: Any) -> dict[str, Any]:
    """Build gear maintenance data dictionary."""
    return {
        "gear_item_id": str(gear_maint_data.gear_item_id)
        if gear_maint_data.gear_item_id
        else None,
        "maintenance_type": gear_maint_data.maintenance_type,
        "activity_types": gear_maint_data.activity_types,
        "retirement_reason": gear_maint_data.retirement_reason,
    }


def _build_gear_usage_data(gear_usage_data: Any) -> dict[str, Any]:
    """Build gear usage data dictionary."""
    return {
        "gear_item_id": str(gear_usage_data.gear_item_id)
        if gear_usage_data.gear_item_id
        else None,
        "checkout_date": gear_usage_data.checkout_date.isoformat()
        if gear_usage_data.checkout_date
        else None,
        "checkin_date": gear_usage_data.checkin_date.isoformat()
        if gear_usage_data.checkin_date
        else None,
    }


class _TypeDataReader(NamedTuple):
    """How to detect one journal type and render its type_data for MCP."""

    repo_attr: str
    build: Callable[[Any], dict[str, Any]]


# Every journal type except NOTE (which is the absence of typed rows), in the
# order types are reported. A type missing here is written but never read back,
# so tests/unit/journal/test_journal_type_coverage.py enforces completeness.
TYPE_DATA_READERS: dict[JournalType, _TypeDataReader] = {
    JournalType.EVENT: _TypeDataReader("calendar_info_repo", _build_calendar_data),
    JournalType.MOOD_RATING: _TypeDataReader("mood_data_repo", _build_mood_data),
    JournalType.PLAN: _TypeDataReader("plan_data_repo", _build_plan_data),
    JournalType.TRAVEL: _TypeDataReader("travel_data_repo", _build_travel_data),
    JournalType.PHOTO_ALBUM: _TypeDataReader(
        "photo_album_data_repo", _build_photo_album_data
    ),
    JournalType.FITNESS: _TypeDataReader("fitness_data_repo", _build_fitness_data),
    JournalType.OUTDOOR_ACTIVITY: _TypeDataReader(
        "outdoor_activity_data_repo", _build_outdoor_activity_data
    ),
    JournalType.BUSHWALKING: _TypeDataReader(
        "bushwalking_data_repo", _build_bushwalking_data
    ),
    JournalType.JOGGING: _TypeDataReader("jogging_data_repo", _build_jogging_data),
    JournalType.ABSEILING_TRIP: _TypeDataReader(
        "abseiling_data_repo", _build_abseiling_data
    ),
    JournalType.CAVING: _TypeDataReader("caving_data_repo", _build_caving_data),
    JournalType.CANYONING: _TypeDataReader(
        "canyoning_data_repo", _build_canyoning_data
    ),
    JournalType.CLIMBING: _TypeDataReader("climbing_data_repo", _build_climbing_data),
    JournalType.KAYAKING: _TypeDataReader("kayaking_data_repo", _build_kayaking_data),
    JournalType.CROSS_COUNTRY_SKIING: _TypeDataReader(
        "cross_country_skiing_data_repo", _build_cross_country_skiing_data
    ),
    JournalType.CANOEING: _TypeDataReader("canoeing_data_repo", _build_canoeing_data),
    JournalType.SNORKELLING: _TypeDataReader(
        "snorkelling_data_repo", _build_presence_only_data
    ),
    JournalType.DIVING: _TypeDataReader("diving_data_repo", _build_presence_only_data),
    JournalType.DOWNHILL_SKIING: _TypeDataReader(
        "downhill_skiing_data_repo", _build_presence_only_data
    ),
    JournalType.OUTDOOR_PLANNING: _TypeDataReader(
        "outdoor_planning_data_repo", _build_outdoor_planning_data
    ),
    JournalType.OUTDOOR_TRAINING: _TypeDataReader(
        "outdoor_training_data_repo", _build_outdoor_training_data
    ),
    JournalType.GEAR_MAINTENANCE: _TypeDataReader(
        "gear_maintenance_data_repo", _build_gear_maintenance_data
    ),
    JournalType.GEAR_USAGE: _TypeDataReader(
        "gear_usage_data_repo", _build_gear_usage_data
    ),
}


async def _fetch_journal_types_and_data(
    journal_id: int, repos: _JournalToolRepositories
) -> tuple[list[str], dict[str, Any]]:
    """Fetch a journal's types and type-specific data via ``TYPE_DATA_READERS``.

    Returns:
        Tuple of (types list, type_data dict keyed by type value)
    """
    types: list[str] = []
    type_data: dict[str, Any] = {}

    for journal_type, reader in TYPE_DATA_READERS.items():
        repo = getattr(repos, reader.repo_attr)
        data = await repo.find_by_journal_id(journal_id)
        if data:
            types.append(journal_type.value)
            type_data[journal_type.value] = reader.build(data)

    # No typed row at all means the journal is a plain NOTE.
    if not types:
        types.append(JournalType.NOTE.value)

    return types, type_data


async def _create_type_specific_data(
    journal_type: JournalType,
    journal_id: int,
    mood_data_repo: SqlMoodDataRepository,
    plan_data_repo: SqlPlanDataRepository,
    travel_data_repo: SqlTravelDataRepository,
    fitness_data_repo: SqlFitnessDataRepository,
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
    bushwalking_data_repo: SqlBushwalkingDataRepository,
    jogging_data_repo: SqlJoggingDataRepository,
    abseiling_data_repo: SqlAbseilingDataRepository,
    canyoning_data_repo: SqlCanyoningDataRepository,
    caving_data_repo: SqlCavingDataRepository,
    climbing_data_repo: SqlClimbingDataRepository,
    kayaking_data_repo: SqlKayakingDataRepository,
    cross_country_skiing_data_repo: SqlCrossCountrySkiingDataRepository,
    gear_maintenance_data_repo: SqlGearMaintenanceDataRepository,
    gear_usage_data_repo: SqlGearUsageDataRepository,
) -> None:
    """
    Create type-specific data row with default values for the given journal type.

    Args:
        journal_type: The type of journal
        journal_id: The ID of the journal
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        caving_data_repo: Repository for caving data
        climbing_data_repo: Repository for climbing data
        kayaking_data_repo: Repository for kayaking data
        cross_country_skiing_data_repo: Repository for cross-country skiing data
        gear_maintenance_data_repo: Repository for gear maintenance data
        gear_usage_data_repo: Repository for gear usage data
    """
    if journal_type == JournalType.MOOD_RATING:
        mood_data = MoodData(journal_id=journal_id)
        await mood_data_repo.save(mood_data)
    elif journal_type == JournalType.PLAN:
        plan_data = PlanData(journal_id=journal_id)
        await plan_data_repo.save(plan_data)
    elif journal_type == JournalType.TRAVEL:
        travel_data = TravelData(journal_id=journal_id)
        await travel_data_repo.save(travel_data)
    elif journal_type == JournalType.FITNESS:
        fitness_data = FitnessData(journal_id=journal_id)
        await fitness_data_repo.save(fitness_data)
    elif journal_type == JournalType.OUTDOOR_ACTIVITY:
        outdoor_activity_data = OutdoorActivityData(journal_id=journal_id)
        await outdoor_activity_data_repo.save(outdoor_activity_data)
    elif journal_type == JournalType.BUSHWALKING:
        bushwalking_data = BushwalkingData(journal_id=journal_id)
        await bushwalking_data_repo.save(bushwalking_data)
    elif journal_type == JournalType.JOGGING:
        jogging_data = JoggingData(journal_id=journal_id)
        await jogging_data_repo.save(jogging_data)
    elif journal_type == JournalType.ABSEILING_TRIP:
        abseiling_data = AbseilingData(journal_id=journal_id)
        await abseiling_data_repo.save(abseiling_data)
    elif journal_type == JournalType.CANYONING:
        canyoning_data = CanyoningData(journal_id=journal_id)
        await canyoning_data_repo.save(canyoning_data)
    elif journal_type == JournalType.CLIMBING:
        climbing_data = ClimbingData(journal_id=journal_id)
        await climbing_data_repo.save(climbing_data)
    elif journal_type == JournalType.KAYAKING:
        kayaking_data = KayakingData(journal_id=journal_id)
        await kayaking_data_repo.save(kayaking_data)
    elif journal_type == JournalType.CROSS_COUNTRY_SKIING:
        cross_country_skiing_data = CrossCountrySkiingData(journal_id=journal_id)
        await cross_country_skiing_data_repo.save(cross_country_skiing_data)
    elif journal_type == JournalType.GEAR_MAINTENANCE:
        pass  # Deferred to update logic because gear_item_id is required
    elif journal_type == JournalType.GEAR_USAGE:
        pass  # Deferred to update logic because gear_item_id is required
    # EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
    # These will be created when the user provides type_data


def _parse_calendar_id(calendar_id: Any) -> UUID | None:
    if calendar_id is None:
        return None

    if isinstance(calendar_id, UUID):
        return calendar_id

    if isinstance(calendar_id, str):
        try:
            return UUID(calendar_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID."
            ) from exc

    raise ValueError(f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID.")


def _parse_optional_time_field(type_data_dict: dict[str, Any], field_name: str) -> Any:
    value = type_data_dict.get(field_name)
    if not isinstance(value, str):
        return value

    try:
        return dt_time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field_name} '{value}'. Must use HH:MM or HH:MM:SS format."
        ) from exc


async def _update_event_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    calendar_info_repo: SqlCalendarInfoRepository,
) -> None:
    calendar_id = _parse_calendar_id(type_data_dict.get("calendar_id"))
    if calendar_id is None:
        return

    # Anchor clock-only times to the journal's event date range (carried on the
    # existing record via the journals JOIN) so cross-midnight events pass the
    # start<=end validation instead of being wrongly rejected.
    existing = await calendar_info_repo.find_by_journal_id(journal_id)
    event_start_date = existing.event_start_date if existing else None
    event_end_date = existing.event_end_date if existing else None

    calendar_info = CalendarInfo(
        journal_id=journal_id,
        calendar_id=calendar_id,
        start_time=_parse_optional_time_field(type_data_dict, "start_time"),
        end_time=_parse_optional_time_field(type_data_dict, "end_time"),
        is_all_day=type_data_dict.get("is_all_day", False),
        location=type_data_dict.get("location"),
        description=type_data_dict.get("description"),
        timezone=type_data_dict.get("timezone"),
        sync_invitees=type_data_dict.get("sync_invitees", False),
        private_description=type_data_dict.get("private_description", False),
        event_state=type_data_dict.get("event_state", "confirmed"),
        event_start_date=event_start_date,
        event_end_date=event_end_date,
    )
    await calendar_info_repo.save(calendar_info)


async def _update_mood_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    mood_data_repo: SqlMoodDataRepository,
) -> None:
    existing_mood = await mood_data_repo.find_by_journal_id(journal_id)
    if existing_mood:
        if "mood_value" in type_data_dict:
            existing_mood.mood_value = type_data_dict["mood_value"]
        if "mood_label" in type_data_dict:
            existing_mood.mood_label = type_data_dict["mood_label"]
        if "energy_level" in type_data_dict:
            existing_mood.energy_level = type_data_dict["energy_level"]
        await mood_data_repo.save(existing_mood)


async def _update_fitness_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    fitness_data_repo: SqlFitnessDataRepository,
) -> None:
    existing_fitness = await fitness_data_repo.find_by_journal_id(journal_id)
    if existing_fitness:
        for field in [
            "heart_rate_avg",
            "heart_rate_max",
            "distance",
            "elevation_gain",
            "elevation_loss",
            "duration",
            "calories",
            "strava_activity_id",
        ]:
            if field in type_data_dict:
                setattr(existing_fitness, field, type_data_dict[field])
        await fitness_data_repo.save(existing_fitness)


async def _update_outdoor_activity_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
) -> None:
    existing_outdoor = await outdoor_activity_data_repo.find_by_journal_id(journal_id)
    if existing_outdoor:
        updates: dict[str, Any] = {}
        for field in [
            "weather_conditions",
            "role",
            "in_leadership_role",
            "participant_notes",
        ]:
            if field in type_data_dict:
                updates[field] = type_data_dict[field]
        validated_outdoor = dataclasses.replace(existing_outdoor, **updates)
        await outdoor_activity_data_repo.save(validated_outdoor)


async def _update_bushwalking_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    bushwalking_data_repo: SqlBushwalkingDataRepository,
) -> None:
    existing_bushwalking = await bushwalking_data_repo.find_by_journal_id(journal_id)
    if existing_bushwalking:
        bw_updates: dict[str, Any] = {}
        if "track_grading" in type_data_dict:
            bw_updates["track_grading"] = type_data_dict["track_grading"]
        validated_bushwalking = dataclasses.replace(existing_bushwalking, **bw_updates)
        await bushwalking_data_repo.save(validated_bushwalking)


async def _update_jogging_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    jogging_data_repo: SqlJoggingDataRepository,
) -> None:
    existing_jogging = await jogging_data_repo.find_by_journal_id(journal_id)
    if existing_jogging:
        jog_updates: dict[str, Any] = {}
        if "pace" in type_data_dict:
            jog_updates["pace"] = type_data_dict["pace"]
        validated_jogging = dataclasses.replace(existing_jogging, **jog_updates)
        await jogging_data_repo.save(validated_jogging)


async def _update_abseiling_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    abseiling_data_repo: SqlAbseilingDataRepository,
) -> None:
    existing_abseiling = await abseiling_data_repo.find_by_journal_id(journal_id)
    if existing_abseiling:
        abs_updates: dict[str, Any] = {}
        if "template_id" in type_data_dict:
            abs_updates["template_id"] = type_data_dict["template_id"]
        if "number_of_abseils" in type_data_dict:
            abs_updates["number_of_abseils"] = type_data_dict["number_of_abseils"]
        if "total_length" in type_data_dict:
            abs_updates["total_length"] = type_data_dict["total_length"]
        if "number_of_setups" in type_data_dict:
            abs_updates["number_of_setups"] = type_data_dict["number_of_setups"]
        if "number_of_rescues" in type_data_dict:
            abs_updates["number_of_rescues"] = type_data_dict["number_of_rescues"]
        validated_abseiling = dataclasses.replace(existing_abseiling, **abs_updates)
        await abseiling_data_repo.save(validated_abseiling)


async def _update_caving_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    caving_data_repo: SqlCavingDataRepository,
) -> None:
    existing_caving = await caving_data_repo.find_by_journal_id(journal_id)
    if existing_caving:
        cav_updates: dict[str, Any] = {}
        for field in [
            "is_vertical",
            "is_horizontal",
        ]:
            if field in type_data_dict:
                cav_updates[field] = type_data_dict[field]
        validated_caving = dataclasses.replace(existing_caving, **cav_updates)
        await caving_data_repo.save(validated_caving)


async def _update_canyoning_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    canyoning_data_repo: SqlCanyoningDataRepository,
) -> None:
    existing_canyoning = await canyoning_data_repo.find_by_journal_id(journal_id)
    if existing_canyoning:
        can_updates: dict[str, Any] = {}
        for field in [
            "french_grade",
            "water_guage_name",
            "water_guage_level",
            "is_vertical",
            "is_night_canyon",
            "is_white_water",
        ]:
            if field in type_data_dict:
                can_updates[field] = type_data_dict[field]
        validated_canyoning = dataclasses.replace(existing_canyoning, **can_updates)
        await canyoning_data_repo.save(validated_canyoning)


async def _update_climbing_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    climbing_data_repo: SqlClimbingDataRepository,
) -> None:
    existing_climbing = await climbing_data_repo.find_by_journal_id(journal_id)
    if existing_climbing:
        clb_updates: dict[str, Any] = {}
        for field in ["climbing_type", "grade", "length", "indoor"]:
            if field in type_data_dict:
                clb_updates[field] = type_data_dict[field]
        validated_climbing = dataclasses.replace(existing_climbing, **clb_updates)
        await climbing_data_repo.save(validated_climbing)


async def _update_kayaking_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    kayaking_data_repo: SqlKayakingDataRepository,
) -> None:
    existing_kayaking = await kayaking_data_repo.find_by_journal_id(journal_id)
    if existing_kayaking:
        kayaking_updates: dict[str, Any] = {}
        for field in ["water_type", "is_white_water", "rapids_grade"]:
            if field in type_data_dict:
                kayaking_updates[field] = type_data_dict[field]
        validated_kayaking = dataclasses.replace(existing_kayaking, **kayaking_updates)
        await kayaking_data_repo.save(validated_kayaking)


async def _update_cross_country_skiing_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    cross_country_skiing_data_repo: SqlCrossCountrySkiingDataRepository,
) -> None:
    existing_skiing = await cross_country_skiing_data_repo.find_by_journal_id(
        journal_id
    )
    if existing_skiing:
        skiing_updates: dict[str, Any] = {}
        if "snow_conditions" in type_data_dict:
            skiing_updates["snow_conditions"] = type_data_dict["snow_conditions"]
        validated_skiing = dataclasses.replace(existing_skiing, **skiing_updates)
        await cross_country_skiing_data_repo.save(validated_skiing)


async def _update_type_specific_data(
    journal_type: JournalType,
    journal_id: int,
    type_data_dict: dict[str, Any],
    calendar_info_repo: SqlCalendarInfoRepository,
    mood_data_repo: SqlMoodDataRepository,
    photo_album_data_repo: AlbumSyncReadRepository,
    fitness_data_repo: SqlFitnessDataRepository,
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
    bushwalking_data_repo: SqlBushwalkingDataRepository,
    jogging_data_repo: SqlJoggingDataRepository,
    abseiling_data_repo: SqlAbseilingDataRepository,
    canyoning_data_repo: SqlCanyoningDataRepository,
    caving_data_repo: SqlCavingDataRepository,
    climbing_data_repo: SqlClimbingDataRepository,
    kayaking_data_repo: SqlKayakingDataRepository,
    cross_country_skiing_data_repo: SqlCrossCountrySkiingDataRepository,
    gear_maintenance_data_repo: SqlGearMaintenanceDataRepository,
    gear_usage_data_repo: SqlGearUsageDataRepository,
) -> None:
    """
    Update type-specific data for a journal type.

    Args:
        journal_type: The type of journal
        journal_id: The ID of the journal
        type_data_dict: Dictionary containing type-specific data
        calendar_info_repo: Repository for calendar info
        mood_data_repo: Repository for mood data
        photo_album_data_repo: Repository for photo album data
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        caving_data_repo: Repository for caving data
        climbing_data_repo: Repository for climbing data
        kayaking_data_repo: Repository for kayaking data
        cross_country_skiing_data_repo: Repository for cross-country skiing data
        gear_maintenance_data_repo: Repository for gear maintenance data
        gear_usage_data_repo: Repository for gear usage data
    """
    if not type_data_dict:
        return

    if journal_type == JournalType.EVENT:
        await _update_event_data(journal_id, type_data_dict, calendar_info_repo)
    elif journal_type == JournalType.MOOD_RATING:
        await _update_mood_data(journal_id, type_data_dict, mood_data_repo)
    elif journal_type == JournalType.PHOTO_ALBUM:
        # PHOTO_ALBUM data is managed by Immich album sync. Fail fast rather than
        # silently dropping the update so callers don't believe it succeeded
        # (mirrors the REST API behaviour). JournalValidationError is a
        # JournalDomainError, so mcp_unified_error_handler surfaces a clear
        # validation message rather than a generic internal error.
        from core_shared.models.journals import JournalValidationError

        raise JournalValidationError(
            "journal_type",
            "PHOTO_ALBUM data is managed by Immich sync and cannot be edited",
        )
    elif journal_type == JournalType.FITNESS:
        await _update_fitness_data(journal_id, type_data_dict, fitness_data_repo)
    elif journal_type == JournalType.OUTDOOR_ACTIVITY:
        await _update_outdoor_activity_data(
            journal_id, type_data_dict, outdoor_activity_data_repo
        )
    elif journal_type == JournalType.BUSHWALKING:
        await _update_bushwalking_data(
            journal_id, type_data_dict, bushwalking_data_repo
        )
    elif journal_type == JournalType.JOGGING:
        await _update_jogging_data(journal_id, type_data_dict, jogging_data_repo)
    elif journal_type == JournalType.ABSEILING_TRIP:
        await _update_abseiling_data(journal_id, type_data_dict, abseiling_data_repo)

    elif journal_type == JournalType.CAVING:
        await _update_caving_data(journal_id, type_data_dict, caving_data_repo)
    elif journal_type == JournalType.CANYONING:
        await _update_canyoning_data(journal_id, type_data_dict, canyoning_data_repo)
    elif journal_type == JournalType.CLIMBING:
        await _update_climbing_data(journal_id, type_data_dict, climbing_data_repo)
    elif journal_type == JournalType.KAYAKING:
        await _update_kayaking_data(journal_id, type_data_dict, kayaking_data_repo)
    elif journal_type == JournalType.CROSS_COUNTRY_SKIING:
        await _update_cross_country_skiing_data(
            journal_id,
            type_data_dict,
            cross_country_skiing_data_repo,
        )
    elif journal_type == JournalType.GEAR_MAINTENANCE:
        existing_maint = await gear_maintenance_data_repo.find_by_journal_id(journal_id)
        if existing_maint:
            maint_updates: dict[str, Any] = {}
            if "gear_item_id" in type_data_dict and type_data_dict["gear_item_id"]:
                maint_updates["gear_item_id"] = UUID(type_data_dict["gear_item_id"])
            if "maintenance_type" in type_data_dict:
                maint_updates["maintenance_type"] = type_data_dict["maintenance_type"]
            if "activity_types" in type_data_dict:
                maint_updates["activity_types"] = type_data_dict["activity_types"]
            if "retirement_reason" in type_data_dict:
                maint_updates["retirement_reason"] = type_data_dict["retirement_reason"]
            import dataclasses

            validated_maint = dataclasses.replace(existing_maint, **maint_updates)
            await gear_maintenance_data_repo.save(validated_maint)
        else:
            if (
                "gear_item_id" not in type_data_dict
                or not type_data_dict["gear_item_id"]
            ):
                raise ValueError(
                    "gear_item_id is required to create a gear maintenance journal"
                )
            if (
                "maintenance_type" not in type_data_dict
                or not type_data_dict["maintenance_type"]
            ):
                raise ValueError(
                    "maintenance_type is required to create a gear maintenance journal"
                )

            from core_shared.models.journals.gear_maintenance_data import (
                GearMaintenanceData,
            )

            new_maint = GearMaintenanceData(
                journal_id=journal_id,
                gear_item_id=UUID(type_data_dict["gear_item_id"]),
                maintenance_type=type_data_dict["maintenance_type"],
                activity_types=type_data_dict.get("activity_types"),
                retirement_reason=type_data_dict.get("retirement_reason"),
            )
            await gear_maintenance_data_repo.save(new_maint)

    elif journal_type == JournalType.GEAR_USAGE:
        existing_usage = await gear_usage_data_repo.find_by_journal_id(journal_id)
        from datetime import datetime

        if existing_usage:
            usage_updates: dict[str, Any] = {}
            if "gear_item_id" in type_data_dict and type_data_dict["gear_item_id"]:
                usage_updates["gear_item_id"] = UUID(type_data_dict["gear_item_id"])
            if "checkout_date" in type_data_dict:
                usage_updates["checkout_date"] = type_data_dict["checkout_date"]
            if "checkin_date" in type_data_dict:
                usage_updates["checkin_date"] = type_data_dict["checkin_date"]

            if usage_updates.get("checkout_date") and isinstance(
                usage_updates["checkout_date"], str
            ):
                usage_updates["checkout_date"] = datetime.fromisoformat(
                    usage_updates["checkout_date"]
                )
            if usage_updates.get("checkin_date") and isinstance(
                usage_updates["checkin_date"], str
            ):
                usage_updates["checkin_date"] = datetime.fromisoformat(
                    usage_updates["checkin_date"]
                )
            import dataclasses

            validated_usage = dataclasses.replace(existing_usage, **usage_updates)
            await gear_usage_data_repo.save(validated_usage)
        else:
            if (
                "gear_item_id" not in type_data_dict
                or not type_data_dict["gear_item_id"]
            ):
                raise ValueError(
                    "gear_item_id is required to create a gear usage journal"
                )

            chk_out = type_data_dict.get("checkout_date")
            if chk_out and isinstance(chk_out, str):
                chk_out = datetime.fromisoformat(chk_out)

            chk_in = type_data_dict.get("checkin_date")
            if chk_in and isinstance(chk_in, str):
                chk_in = datetime.fromisoformat(chk_in)

            from core_shared.models.journals.gear_usage_data import GearUsageData

            new_usage = GearUsageData(
                journal_id=journal_id,
                gear_item_id=UUID(type_data_dict["gear_item_id"]),
                checkout_date=chk_out,
                checkin_date=chk_in,
            )
            await gear_usage_data_repo.save(new_usage)


def _validate_contact_relationships(
    contact_relationships: list[dict[str, Any]],
) -> None:
    """
    Validate contact relationship inputs without any DB operations.

    Call this BEFORE any DB writes to ensure all inputs are valid.
    Raises ValueError with a clear message if any relationship has invalid
    or missing required fields, wrong types, or unrecognised enum values.
    """
    from core_shared.models.journals.attendee_status import AttendeeStatus
    from core_shared.models.journals.contact_event_role import ContactEventRole

    valid_relationship_types = {t.name for t in JournalContactRelationshipType}

    for i, rel in enumerate(contact_relationships):
        if not isinstance(rel, dict):
            raise ValueError(
                f"contact_relationships[{i}]: expected a dict, got {type(rel).__name__}"
            )

        contact_id = rel.get("contact_id")
        relationship_type_str = rel.get("relationship_type")

        if not contact_id:
            raise ValueError(
                f"contact_relationships[{i}]: missing required field 'contact_id'"
            )
        if not isinstance(contact_id, int):
            raise ValueError(
                f"contact_relationships[{i}]: 'contact_id' must be an int, "
                f"got {type(contact_id).__name__}"
            )
        if not relationship_type_str:
            raise ValueError(
                f"contact_relationships[{i}]: missing required field 'relationship_type'"
            )
        if not isinstance(relationship_type_str, str):
            raise ValueError(
                f"contact_relationships[{i}]: 'relationship_type' must be a string, "
                f"got {type(relationship_type_str).__name__}"
            )
        if relationship_type_str.upper() not in valid_relationship_types:
            raise ValueError(
                f"contact_relationships[{i}]: invalid relationship_type "
                f"'{relationship_type_str}'. "
                f"Valid types are: {', '.join(sorted(valid_relationship_types))}"
            )

        status_raw = rel.get("status")
        if isinstance(status_raw, str):
            try:
                AttendeeStatus[status_raw.upper()]
            except KeyError:
                valid_statuses = {s.name for s in AttendeeStatus}
                raise ValueError(
                    f"contact_relationships[{i}]: invalid status '{status_raw}'. "
                    f"Valid statuses are: {', '.join(sorted(valid_statuses))}"
                ) from None

        role_raw = rel.get("role")
        if isinstance(role_raw, str):
            try:
                ContactEventRole[role_raw.upper()]
            except KeyError:
                valid_roles = {r.name for r in ContactEventRole}
                raise ValueError(
                    f"contact_relationships[{i}]: invalid role '{role_raw}'. "
                    f"Valid roles are: {', '.join(sorted(valid_roles))}"
                ) from None


def _to_service_relationships(
    contact_relationships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalise the MCP flat relationship dicts to the JSON:API-nested shape.

    ``JournalWriteService._process_journal_contact_relationships`` (shared with
    the REST controllers) expects ``{"attributes": {...}}`` items with a string
    ``contact_id`` and an upper-cased ``relationship_type`` enum name. The MCP
    request uses flat ``{contact_id: int, relationship_type: str, ...}`` items,
    so we adapt them here at the call boundary rather than changing the shared
    helper's contract. Inputs are assumed already validated by
    :func:`_validate_contact_relationships`.
    """
    nested: list[dict[str, Any]] = []
    for rel in contact_relationships:
        attributes: dict[str, Any] = {
            "contact_id": str(rel["contact_id"]),
            "relationship_type": rel["relationship_type"].upper(),
        }
        if rel.get("status") is not None:
            attributes["status"] = rel["status"]
        if rel.get("role") is not None:
            attributes["role"] = rel["role"]
        nested.append({"attributes": attributes})
    return nested


async def _fetch_enrichment_data(
    journal_id: int, repos: _JournalToolRepositories
) -> tuple[
    list[str], dict[str, Any], list[ContactRelationshipSummary], list[JournalTag]
]:
    """Fetch all enrichment data for a journal (types, type_data, contacts, tags)."""
    types, type_data = await _fetch_journal_types_and_data(journal_id, repos)

    contacts = await _fetch_contact_relationships_with_names(
        journal_id, repos.contact_relationship_repo, repos.contact_repo
    )

    tags = await repos.tag_repo.get_tags_for_journal(journal_id)

    return types, type_data, contacts, tags


def compute_date_window(
    anchor: date, days_back: int, days_forward: int
) -> tuple[date, date]:
    """Compute a date window around an anchor date.

    Args:
        anchor: The centre date for the window.
        days_back: How many days before the anchor to include.
        days_forward: How many days after the anchor to include.

    Returns:
        Tuple of (window_start, window_end) as date objects.
    """
    return (
        anchor - timedelta(days=days_back),
        anchor + timedelta(days=days_forward),
    )


"""
Register journal-related MCP tools with the FastMCP server.

Args:
    mcp: The FastMCP server instance to register tools with
"""

# -- Type metadata for the discovery tool --
# Keyed by JournalType enum name (uppercase), these describe the type_data
# fields each type accepts.  Keep this in sync with the _update_*_data helpers.
_JOURNAL_TYPE_DESCRIPTIONS: dict[str, str] = {
    "NOTE": "Simple text note using only base journal fields (no type_data needed)",
    "EVENT": "Calendar event with time and location",
    "MOOD_RATING": "Mood and energy level tracking",
    "PLAN": "Event planning (no specific type_data fields)",
    "TRAVEL": "Travel itinerary (no specific type_data fields)",
    "PHOTO_ALBUM": "Photo album linked to Immich",
    "FITNESS": "Base fitness activity with optional metrics",
    "OUTDOOR_ACTIVITY": "Outdoor activity extending FITNESS",
    "BUSHWALKING": "Bushwalking/hiking activity",
    "JOGGING": "Jogging/running activity",
    "ABSEILING_TRIP": "Abseiling/rappelling trip",
    "CANYONING": "Canyoning trip (combines bushwalking + abseiling)",
    "CLIMBING": "Climbing activity (includes abseiling pitches via dependency)",
    "KAYAKING": "Kayaking activity (with optional white water tracking)",
    "CROSS_COUNTRY_SKIING": "Cross-country skiing activity",
    "CAVING": "Caving trip (includes abseiling pitches via dependency)",
    "CANOEING": "Canoeing activity",
    "SNORKELLING": "Snorkelling activity (no specific type_data fields)",
    "DIVING": "Diving activity (no specific type_data fields)",
    "DOWNHILL_SKIING": "Downhill skiing activity (no specific type_data fields)",
    "OUTDOOR_PLANNING": "Outdoor planning meeting (an EVENT about upcoming activities)",
    "OUTDOOR_TRAINING": "Outdoor skills training session",
    "GEAR_MAINTENANCE": "Maintenance or retirement of a gear item",
    "GEAR_USAGE": "Checkout/checkin of a gear item",
}


class _FieldSpec(NamedTuple):
    """Discovery metadata for one type_data field (see list_journal_types)."""

    type: str
    description: str = ""
    unit: str | None = None
    required: bool = False
    allowed_values: Sequence[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        summary = self.type
        if self.unit:
            summary += f" in {self.unit}"
        summary += " (required)" if self.required else " (optional)"
        spec: dict[str, Any] = {
            "type": self.type,
            "unit": self.unit,
            "required": self.required,
            "description": self.description,
            "summary": summary,
        }
        if self.allowed_values is not None:
            spec["allowed_values"] = list(self.allowed_values)
        return spec


_PITCH_FIELDS_DESCRIPTION = (
    "list of pitch objects. pitch_number (int) is required. Optional: height "
    "(int, metres), anchor_location (see enums.anchor_locations), anchor_type "
    "(see enums.anchor_types), did_rescue (bool), did_setup (bool), notes (str)"
)

# Keyed by JournalType name; every field the type_data for that type accepts.
# Units are stated explicitly so an agent never has to infer them.
_JOURNAL_TYPE_DATA_FIELDS: dict[str, dict[str, _FieldSpec]] = {
    "EVENT": {
        "calendar_id": _FieldSpec("uuid", "UUID of the calendar", required=True),
        "start_time": _FieldSpec("string", "Start time (HH:MM or ISO datetime)"),
        "end_time": _FieldSpec("string", "End time (HH:MM or ISO datetime)"),
        "is_all_day": _FieldSpec("bool", "All-day event (default false)"),
        "location": _FieldSpec("string", "Free-text location"),
        "timezone": _FieldSpec("string", "IANA timezone name"),
        "event_state": _FieldSpec("string", "Event state (default 'confirmed')"),
    },
    "MOOD_RATING": {
        "mood_value": _FieldSpec("int", "Mood on a 1-10 scale", unit="1-10 scale"),
        "mood_label": _FieldSpec("string", "Free-text mood label"),
        "energy_level": _FieldSpec("int", "Energy on a 1-10 scale", unit="1-10 scale"),
    },
    "PHOTO_ALBUM": {
        "immich_album_id": _FieldSpec("uuid", "Immich album UUID"),
    },
    "FITNESS": {
        "heart_rate_avg": _FieldSpec("int", "Average heart rate", unit="bpm"),
        "heart_rate_max": _FieldSpec("int", "Maximum heart rate", unit="bpm"),
        "distance": _FieldSpec(
            "int",
            "Distance in whole kilometres (fractions are truncated)",
            unit="km",
        ),
        "elevation_gain": _FieldSpec("int", "Total ascent", unit="m"),
        "elevation_loss": _FieldSpec("int", "Total descent", unit="m"),
        "duration": _FieldSpec("int", "Elapsed time", unit="minutes"),
        "calories": _FieldSpec("int", "Energy expended", unit="kcal"),
        "strava_activity_id": _FieldSpec(
            "string", "Linked Strava activity id (creates the Strava external link)"
        ),
    },
    "OUTDOOR_ACTIVITY": {
        "weather_conditions": _FieldSpec("string", "Weather during the activity"),
        "role": _FieldSpec("string", "Your role on the trip"),
        "in_leadership_role": _FieldSpec("bool", "Whether you led the trip"),
        "participant_notes": _FieldSpec("string", "Notes about participants"),
    },
    "BUSHWALKING": {
        "track_grading": _FieldSpec(
            "string",
            "Australian Walking Track Grading System grade",
            allowed_values=VALID_TRACK_GRADES,
        ),
    },
    "JOGGING": {
        "pace": _FieldSpec("string", "Pace, e.g. '5:30/km'", unit="min/km"),
    },
    "ABSEILING_TRIP": {
        "template_id": _FieldSpec(
            "uuid",
            "Activity template this abseiling-derived journal was created from "
            "(preserved when pitches are edited)",
        ),
        "number_of_abseils": _FieldSpec("int", "Count of abseils"),
        "total_length": _FieldSpec("int", "Total abseiled length", unit="m"),
        "number_of_setups": _FieldSpec("int", "Anchors you set up"),
        "number_of_rescues": _FieldSpec("int", "Rescues performed"),
        "pitches": _FieldSpec("list", _PITCH_FIELDS_DESCRIPTION),
    },
    "CANYONING": {
        "french_grade": _FieldSpec(
            "string", "French canyon grade, e.g. 'v3a2IV**' (v1-7, a1-7, I-VI, *-***)"
        ),
        "water_guage_name": _FieldSpec("string", "Name of the water gauge used"),
        "water_guage_level": _FieldSpec(
            "int", "Gauge reading at the time of the trip", unit="gauge units"
        ),
        "is_vertical": _FieldSpec("bool", "Primarily vertical canyon"),
        "is_night_canyon": _FieldSpec("bool", "Done at night"),
        "is_white_water": _FieldSpec("bool", "Significant white water"),
    },
    "CLIMBING": {
        "template_id": _FieldSpec("uuid", "Activity template reference"),
        "climbing_type": _FieldSpec(
            "string", "Climbing discipline", allowed_values=VALID_CLIMBING_TYPES
        ),
        "grade": _FieldSpec("int", "Ewbank (Australian) grade"),
        "length": _FieldSpec("int", "Route length", unit="m"),
        "indoor": _FieldSpec(
            "bool", "Indoor climb (default false) — independent of climbing_type"
        ),
    },
    "KAYAKING": {
        "water_type": _FieldSpec("string", "Type of water body (river, lake, sea)"),
        "is_white_water": _FieldSpec("bool", "White-water paddle"),
        "rapids_grade": _FieldSpec(
            "string",
            "International Scale of River Difficulty",
            allowed_values=VALID_RAPIDS_GRADES,
        ),
    },
    "CROSS_COUNTRY_SKIING": {
        "snow_conditions": _FieldSpec("string", "Snow conditions"),
    },
    "CAVING": {
        "is_vertical": _FieldSpec("bool", "Vertical cave (SRT)"),
        "is_horizontal": _FieldSpec("bool", "Horizontal cave"),
    },
    "CANOEING": {
        "water_type": _FieldSpec("string", "Type of water body (river, lake, sea)"),
    },
    "OUTDOOR_PLANNING": {
        "topics": _FieldSpec("string", "Meeting topics"),
        "activity_types": _FieldSpec(
            "list[string]", "Outdoor activity types the meeting relates to"
        ),
    },
    "OUTDOOR_TRAINING": {
        "focus_areas": _FieldSpec(
            "list[string]", "Activity subtypes trained, or free text"
        ),
    },
    "GEAR_MAINTENANCE": {
        "gear_item_id": _FieldSpec("uuid", "Gear item", required=True),
        "maintenance_type": _FieldSpec(
            "string",
            "Kind of maintenance",
            required=True,
            allowed_values=VALID_MAINTENANCE_TYPES,
        ),
        "activity_types": _FieldSpec("list[string]", "Related activity types"),
        "retirement_reason": _FieldSpec("string", "Why the item was retired"),
    },
    "GEAR_USAGE": {
        "gear_item_id": _FieldSpec("uuid", "Gear item", required=True),
        "checkout_date": _FieldSpec("datetime", "ISO datetime checked out"),
        "checkin_date": _FieldSpec("datetime", "ISO datetime checked in"),
    },
}

# Closed vocabularies surfaced by list_journal_types so an agent can discover
# valid values up front instead of through validation failures.
_JOURNAL_ENUMS: dict[str, Sequence[str]] = {
    "anchor_types": VALID_ANCHOR_TYPES,
    "anchor_locations": VALID_ANCHOR_LOCATIONS,
    "pitch_types": VALID_PITCH_TYPES,
    "canyon_types": VALID_CANYON_TYPES,
    "climbing_types": VALID_CLIMBING_TYPES,
    "template_types": VALID_TEMPLATE_TYPES,
    "track_grades": VALID_TRACK_GRADES,
    "rapids_grades": VALID_RAPIDS_GRADES,
    "maintenance_types": VALID_MAINTENANCE_TYPES,
}


@mcp_unified_error_handler("list_journal_types", "journal")
async def list_journal_types() -> str:
    """
    List all valid journal types, their descriptions, dependencies, and type_data fields.

    Call this BEFORE create_journal_entry or update_journal_entry to discover
    valid type names, what type_data fields each type accepts, the unit each
    numeric field is stored in, and the allowed values of closed vocabularies
    (anchor types, canyon types, climbing types, pitch types, grades).

    Returns:
        JSON with all available journal types and their schemas
    """
    from core_shared.models.journals.attendee_status import AttendeeStatus
    from core_shared.models.journals.contact_event_role import ContactEventRole

    types_info: list[dict[str, Any]] = []

    for jt in JournalType:
        type_name = jt.name
        deps = JournalType.get_dependencies(jt)
        dep_names = [d.name for d in deps]

        entry: dict[str, Any] = {
            "name": type_name,
            "description": _JOURNAL_TYPE_DESCRIPTIONS.get(type_name, ""),
            "dependencies": dep_names,
        }
        fields = _JOURNAL_TYPE_DATA_FIELDS.get(type_name)
        entry["type_data_fields"] = (
            {name: spec.as_dict() for name, spec in fields.items()} if fields else None
        )

        types_info.append(entry)

    # Also include contact_relationship enum info
    contact_enums = {
        "relationship_types": [t.name for t in JournalContactRelationshipType],
        "attendee_statuses": [s.name for s in AttendeeStatus],
        "contact_event_roles": [r.name for r in ContactEventRole],
    }

    result = {
        "journal_types": types_info,
        "contact_relationship_enums": contact_enums,
        "enums": {name: list(values) for name, values in _JOURNAL_ENUMS.items()},
        "units": {
            "distance": "km (whole kilometres)",
            "elevation_gain": "m",
            "elevation_loss": "m",
            "duration": "minutes",
            "total_length": "m",
            "length": "m",
            "height": "m",
            "heart_rate_avg": "bpm",
            "heart_rate_max": "bpm",
            "calories": "kcal",
        },
        "usage_hint": (
            "Pass type names in the 'types' field of create/update journal_data. "
            "Dependencies are added automatically; NOTE is implicit and ignored "
            "when combined with other types. Pass type-specific data in the "
            "'type_data' field keyed by type name. Each field lists its type, "
            "unit, whether it is required, and allowed_values where the "
            "vocabulary is closed; 'enums' repeats every closed vocabulary."
        ),
    }

    return json.dumps(result, indent=2)


@mcp_unified_error_handler("create_journal_entry", "journal")
async def create_journal_entry(
    request: JournalCreateRequest,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    write_service: JournalWriteService = mcp_depends(get_journal_write_service),
) -> str:
    """
    Create a new journal entry with types, type-specific data, relationships, and tags.

    IMPORTANT: Call list_journal_types first if you are unsure which type names
    or type_data fields are valid. Invalid type names will be rejected.

    Creates a journal entry with support for multiple types, type-specific data
    (e.g. calendar_id for EVENT), contact relationships, and tags.
    Type dependencies are added automatically (e.g. BUSHWALKING adds
    OUTDOOR_ACTIVITY and FITNESS).


    Returns:
        JSON string containing AI-friendly journal information including:
        - Journal details (title, content, date range)
        - Types and type-specific data
        - Contact relationships
        - Tags
        - Contextual summary for AI understanding

    Raises:
        JournalValidationError: If validation fails
        ValueError: If invalid type/relationship_type/status/role values are provided
    """
    # No JSON parsing needed, FastMCP handles request model conversion directly

    # Get current user ID from auth context
    user_id = await get_current_user_id()

    # --- Validate ALL inputs upfront BEFORE any DB writes ---
    # This ensures ValueError is raised before the journal INSERT,
    # preventing partial data commits when the error handler catches it.
    valid_type_names = {t.name for t in JournalType}

    if request.types:
        invalid_types = [t for t in request.types if t.upper() not in valid_type_names]
        if invalid_types:
            raise ValueError(
                f"Invalid journal type(s): {', '.join(invalid_types)}. "
                f"Valid types are: {', '.join(sorted(valid_type_names))}"
            )

        # Enforce type_data requirements for GEAR_MAINTENANCE and GEAR_USAGE
        req_types_upper = {t.upper() for t in request.types}

        def has_non_empty_type_data(target_type: str) -> bool:
            if not request.type_data:
                return False
            for k, v in request.type_data.items():
                if k.upper() == target_type:
                    return bool(v)
            return False

        if "GEAR_MAINTENANCE" in req_types_upper and not has_non_empty_type_data(
            "GEAR_MAINTENANCE"
        ):
            raise ValueError(
                "Type GEAR_MAINTENANCE requires corresponding non-empty type_data to be provided"
            )
        if "GEAR_USAGE" in req_types_upper and not has_non_empty_type_data(
            "GEAR_USAGE"
        ):
            raise ValueError(
                "Type GEAR_USAGE requires corresponding non-empty type_data to be provided"
            )

    if request.type_data:
        invalid_type_data_keys = [
            k for k in request.type_data if k.upper() not in valid_type_names
        ]
        if invalid_type_data_keys:
            raise ValueError(
                f"Invalid type_data key(s): {', '.join(invalid_type_data_keys)}. "
                f"Valid types are: {', '.join(sorted(valid_type_names))}"
            )

    if request.contact_relationships:
        _validate_contact_relationships(request.contact_relationships)

    # --- All inputs validated, proceed with DB writes ---

    # Repositories are still needed to read back enrichment data for the response.
    repos = _create_journal_tool_repositories(db_connection)

    # Create journal entity
    journal = Journal(
        user_id=user_id,
        title=request.title,
        content=request.content,
        event_date_range=EventDateRange(
            start=request.event_date_range.start,
            end=request.event_date_range.end,
        ),
        parent_id=request.parent_id,
    )

    # Delegate the whole composite write (journal + types + type-data +
    # relationships + tags) to the @transactional service, which owns the commit
    # before the response is returned (issue #945/#967). This tool opens no
    # transaction itself.
    relationships = (
        _to_service_relationships(request.contact_relationships)
        if request.contact_relationships
        else None
    )
    created_journal = await write_service.create_journal(
        journal,
        request.types,
        request.type_data,
        relationships,
        db_connection,
        tags=request.tags,
        changed_by="mcp",
        source=Provenance.MCP,
    )

    # Ensure journal_id is not None (it should always be set after creation)
    if created_journal.id is None:
        msg = "Journal ID should be set after creation"
        raise ValueError(msg)
    journal_id = created_journal.id

    # Fetch all enrichment data
    types, type_data, contacts, tags = await _fetch_enrichment_data(journal_id, repos)

    parent = await _fetch_parent_journal(created_journal, repos.journal_repo, user_id)
    external_links = await _fetch_journal_external_links(
        journal_id, db_connection, user_id
    )

    # Convert to AI-friendly response
    response = JournalConverter.to_response(
        journal=created_journal,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=tags,
        parent=parent,
        additional_context=_note_implied_context(request.types),
        external_links=external_links,
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("update_journal_entry", "journal")
async def update_journal_entry(
    journal_id: Annotated[
        int, Field(description="The unique identifier of the journal to update")
    ],
    request: JournalUpdateRequest,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    write_service: JournalWriteService = mcp_depends(get_journal_write_service),
) -> str:
    """
    Update an existing journal entry with partial data.

    IMPORTANT: Call list_journal_types first if you are unsure which type names
    or type_data fields are valid. Invalid values will be rejected.

    Only provided fields are updated; omitted fields remain unchanged.
    When types, tags, or contact_relationships are provided they REPLACE all
    existing values (not merge). Types are expanded through their dependencies
    first, so re-typing (e.g. BUSHWALKING -> CANYONING) keeps the type_data of
    every type that remains, including shared dependencies such as FITNESS and
    its Strava link. Only genuinely dropped types lose data; the response lists
    them in ``types_removed`` and the populated fields lost in
    ``type_data_discarded``.


    Returns:
        JSON string containing AI-friendly updated journal information

    Raises:
        JournalNotFoundError: If the journal with the given ID does not exist
        JournalValidationError: If validation fails
        ValueError: If invalid type/relationship values provided
    """
    # No JSON parsing needed, FastMCP handles request model conversion directly

    # --- Validate ALL inputs upfront BEFORE any DB writes ---
    valid_type_names = {t.name for t in JournalType}

    if request.types is not None:
        invalid_types = [t for t in request.types if t.upper() not in valid_type_names]
        if invalid_types:
            raise ValueError(
                f"Invalid journal type(s): {', '.join(invalid_types)}. "
                f"Valid types are: {', '.join(sorted(valid_type_names))}"
            )

    if request.type_data is not None:
        invalid_type_data_keys = [
            k for k in request.type_data if k.upper() not in valid_type_names
        ]
        if invalid_type_data_keys:
            raise ValueError(
                f"Invalid type_data key(s): {', '.join(invalid_type_data_keys)}. "
                f"Valid types are: {', '.join(sorted(valid_type_names))}"
            )

    if request.contact_relationships is not None:
        _validate_contact_relationships(request.contact_relationships)

    # --- All inputs validated, proceed with DB writes ---

    # Repositories are still needed to load the journal and read back enrichment
    # data for the response.
    repos = _create_journal_tool_repositories(db_connection)

    # Get the existing journal, owner-scoped. Somebody else's is reported as
    # missing, exactly as the read and delete tools report it (#1267) — without
    # this the tool rewrote another user's journal and read it back in its own
    # success response.
    user_id = await get_current_user_id()
    existing_journal = await repos.journal_repo.find_by_id_for_user(
        journal_id, str(user_id)
    )
    if not existing_journal:
        raise JournalNotFoundError(journal_id)

    # Snapshot integration links so the response can state whether the update
    # preserved them (an agent cannot otherwise tell an omitted field from a
    # destroyed link).
    links_before = await _fetch_journal_external_links(
        journal_id, db_connection, user_id
    )

    # Apply the requested core-field changes to the loaded journal.
    if request.title is not None:
        existing_journal.title = request.title
    if request.content is not None:
        existing_journal.content = request.content
    if request.event_date_range is not None:
        existing_journal.event_date_range = EventDateRange(
            start=request.event_date_range.start,
            end=request.event_date_range.end,
        )

    if "parent_id" in request.model_fields_set:
        existing_journal.parent_id = request.parent_id

    # Delegate the whole composite update (core fields + replace-all types /
    # type-data / relationships / tags) to the @transactional service, which
    # owns the commit before the response (issue #945/#967). Tri-state: a field
    # left as None on the request is not touched; a provided list replaces all.
    relationships = (
        _to_service_relationships(request.contact_relationships)
        if request.contact_relationships is not None
        else None
    )
    update_result = await write_service.update_journal_composite(
        existing_journal,
        db_connection,
        types=request.types,
        type_data=request.type_data,
        relationships=relationships,
        tags=request.tags,
        changed_by="mcp",
        source=Provenance.MCP,
    )
    updated_journal = update_result.journal

    # Fetch all enrichment data
    types, type_data, contacts, tags = await _fetch_enrichment_data(journal_id, repos)

    parent = await _fetch_parent_journal(updated_journal, repos.journal_repo, user_id)
    links_after = await _fetch_journal_external_links(
        journal_id, db_connection, user_id
    )
    links_preserved = _external_links_preserved(links_before, links_after)

    # Convert to AI-friendly response
    response = JournalConverter.to_response(
        journal=updated_journal,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=tags,
        parent=parent,
        additional_context=_note_implied_context(request.types),
        external_links=links_after,
        external_links_preserved=links_preserved,
        types_removed=update_result.types_removed,
        type_data_discarded=update_result.type_data_discarded,
    )

    return MCPResponseBuilder.success_response(response)


async def _build_journal_response(
    journal_id: int,
    user_id: str,
    db_connection: AsyncConnection,
    *,
    include_children: bool = False,
) -> str:
    """Full owner-scoped journal payload shared by the get_journal* tools."""
    # Create repositories
    repos = _create_journal_tool_repositories(db_connection)
    journal_repo = repos.journal_repo

    # Get journal
    journal = await journal_repo.find_by_id(journal_id)
    if not journal or str(journal.user_id) != str(user_id):
        raise JournalNotFoundError(journal_id)

    # Resolve the parent this journal hangs off, so a child created with a
    # parent_id reads back as one.
    parent = await _fetch_parent_journal(journal, journal_repo, user_id)

    # Get children if requested
    children = None
    if include_children:
        children = await journal_repo.get_children(journal_id)

    # Fetch types and type-specific data
    types, type_data = await _fetch_journal_types_and_data(journal_id, repos)

    # Fetch contact relationships and contact details
    contacts = await _fetch_contact_relationships_with_names(
        journal_id, repos.contact_relationship_repo, repos.contact_repo
    )

    # Fetch tags
    journal_tags = await repos.tag_repo.get_tags_for_journal(journal_id)

    # Fetch series memberships
    from app.core.journal.adapters.sql.journal_series_repository import (
        SqlJournalSeriesRepository,
    )

    journal_series = await SqlJournalSeriesRepository(
        db_connection
    ).get_series_for_journal(journal_id, user_id)
    series = [
        {"id": str(s.id), "name": s.name} for s in journal_series if s.id is not None
    ]

    # Fetch external links (Strava and Google Calendar)
    external_links = await _fetch_journal_external_links(
        journal_id, db_connection, user_id
    )

    # Convert to AI-friendly response
    response = JournalConverter.to_response(
        journal=journal,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=journal_tags,
        parent=parent,
        children=children,
        external_links=external_links,
        series=series,
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("get_journal", "journal")
async def get_journal(
    journal_id: Annotated[
        int, Field(description="The unique identifier of the journal")
    ],
    include_children: Annotated[
        bool,
        Field(
            default=False,
            description="Optional: Include child journals in the response",
        ),
    ] = False,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get journal details by ID for AI analysis.

    Retrieves comprehensive journal information including title, content, types,
    type-specific data, contact relationships, tags, and a contextual summary.
    Optionally includes child journals.

    Args:
        journal_id: The unique identifier of the journal
        include_children: Optional flag to include child journals

    Returns:
        JSON string containing AI-friendly journal information including:
        - Journal details (title, content, date range)
        - Types and type-specific data
        - Contact relationships
        - Tags
        - Optional child journals
        - Contextual summary for AI understanding

    Raises:
        JournalNotFoundError: If the journal with the given ID does not exist
    """
    user_id = await get_current_user_id()
    return await _build_journal_response(
        journal_id, user_id, db_connection, include_children=include_children
    )


@mcp_unified_error_handler("get_journal_by_external_id", "journal")
async def get_journal_by_external_id(
    source: Annotated[
        str,
        Field(
            description="Integration source the id belongs to. One of: "
            + ", ".join(sorted(_VALID_INTEGRATION_SOURCES))
            + ". Any other value is rejected."
        ),
    ],
    external_id: Annotated[
        str,
        Field(
            description="The external system's identifier, e.g. a Strava activity "
            "id ('16152597201'), a Google Calendar event id, an Immich album "
            "UUID, or a Snipe-IT maintenance/checkout id."
        ),
    ],
    include_children: Annotated[
        bool,
        Field(default=False, description="Optional: Include child journals"),
    ] = False,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Find the journal linked to an external system's record.

    Resolves ``(source, external_id)`` — e.g. ('strava', '16152597201') — to
    the user's journal and returns the same payload as get_journal. Use this
    instead of searching by title when you already hold an integration id.

    Raises:
        ValueError: If ``source`` is not a recognised integration source

    Returns a "Not found" error payload when no journal is linked to that id.
    """
    source_filter = _parse_integration_source_filter(source)
    assert source_filter is not None  # noqa: S101 — `source` is required
    normalized_id = external_id.strip()
    if not normalized_id:
        raise ValueError("external_id must not be empty")

    user_id = await get_current_user_id()
    journal_id = await _find_journal_id_by_external_id(
        db_connection, user_id, source_filter, normalized_id
    )
    if journal_id is None:
        return MCPResponseBuilder.error_response(
            error_type="Not found",
            message=f"No journal is linked to {source_filter} id '{normalized_id}'",
            context={"source": source_filter, "external_id": normalized_id},
        )
    return await _build_journal_response(
        journal_id, user_id, db_connection, include_children=include_children
    )


@mcp_unified_error_handler("get_journal_hierarchy", "journal")
async def get_journal_hierarchy(
    start_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Start date (ISO format) to filter journals",
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: End date (ISO format) to filter journals",
        ),
    ] = None,
    types: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Comma-separated list of journal types to filter by",
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=100,
            description="Maximum number of journals to retrieve before building hierarchy (default: 100)",
        ),
    ] = 100,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get a hierarchical view of journals.

    Retrieves journals and their descendants matching the given filters,
    returning them in a nested tree structure. Useful for exploring
    trips, projects, or multi-day events.

    Args:
        start_date: Optional start date
        end_date: Optional end date
        types: Optional comma-separated list of journal types
        limit: Maximum number of journals to retrieve

    Returns:
        JSON string containing the journal hierarchy tree and summary.
    """
    import time

    start_time = time.time()
    user_id = await get_current_user_id()
    repos = _create_journal_tool_repositories(db_connection)

    type_filters = _parse_type_filters(types)
    journal_type = type_filters[0] if len(type_filters) == 1 else None

    start = _parse_optional_datetime_filter(start_date, "start_date")
    end = _parse_optional_datetime_filter(end_date, "end_date", is_end=True)

    start_str = start.isoformat() if start else None
    end_str = end.isoformat() if end else None

    journals = await repos.journal_repo.get_all(
        user_id=user_id,
        limit=limit,
        offset=0,
        journal_type=journal_type,
        start_date=start_str,
        end_date=end_str,
    )

    filtered_journals = []
    if len(type_filters) > 1:
        for j in journals:
            if j.id is not None:
                j_types, _ = await _fetch_types_for_journal(j.id, repos)
                if any(t in type_filters for t in j_types):
                    filtered_journals.append(j)
        journals = filtered_journals

    returned_ids_list = [j.id for j in journals if j.id is not None]
    children_count_by_parent_id = await repos.journal_repo.count_children_for_parents(
        user_id=user_id, parent_ids=returned_ids_list
    )

    depth_map = await HierarchyService.compute_depth_map(
        returned_ids_list, repos.journal_repo
    )

    hierarchy_nodes = HierarchyService.build_tree_nodes(
        journals, children_count_by_parent_id, depth_map
    )

    root_nodes = []
    for h_node in hierarchy_nodes:
        root_nodes.append(await _build_hierarchy_node(h_node, repos))

    processing_time_ms = int((time.time() - start_time) * 1000)
    summary = (
        f"Found {len(journals)} journal(s), representing {len(root_nodes)} "
        f"root-level item(s) in the hierarchy. (Processing time: {processing_time_ms}ms)"
    )

    response = JournalHierarchyResponse(
        nodes=root_nodes,
        total_nodes=len(journals),
        processing_time_ms=processing_time_ms,
        summary=summary,
    )

    return MCPResponseBuilder.success_response(response)


_SEARCH_UNAVAILABLE_HINT = (
    "The search backend (MeiliSearch) could not be reached, so this is NOT an "
    "empty result. Retry shortly, or use browse_journals_by_date_window / "
    "search_activities, which are database-backed."
)


def _search_hit_to_result(hit: dict[str, Any]) -> JournalSearchResult:
    """Render one MeiliSearch journal hit as an MCP search result."""
    start = hit.get("event_date_range_start")
    end = hit.get("event_date_range_end")
    now = datetime.now(UTC)
    content = hit.get("content") or ""
    formatted = hit.get("_formatted") or {}
    highlighted = {
        key: value
        for key in ("title", "content", "location")
        if isinstance(value := formatted.get(key), str) and "<mark>" in value
    }
    return JournalSearchResult(
        id=int(hit["id"]),
        title=hit.get("title") or "",
        content_excerpt=content[:200] + "..." if len(content) > 200 else content,
        event_date_range=EventDateRangeSchema(
            start=datetime.fromisoformat(start) if start else now,
            end=datetime.fromisoformat(end) if end else now,
        ),
        types=[str(t).lower() for t in hit.get("types", [])],
        tags=[],
        highlighted=highlighted,
        summary=f"Journal: {hit.get('title') or ''}",
    )


def _meili_search_journals(
    search_service: SearchService,
    *,
    query: str,
    user_id: str,
    limit: int,
    type_filters: list[str] | None = None,
    journal_ids: set[int] | None = None,
) -> tuple[list[JournalSearchResult], int, int]:
    """Run a journal full-text search through MeiliSearch (REST parity).

    Returns ``(results, total_hits, processing_time_ms)``. A MeiliSearch
    failure is raised as :class:`SearchServiceUnavailableError` so the caller
    reports it loudly rather than as an empty result.
    """
    filters: dict[str, Any] = {"user_id": user_id}
    if type_filters:
        filters["types"] = [t.upper() for t in type_filters]
    if journal_ids is not None:
        filters["id"] = sorted(journal_ids)
    try:
        raw = search_service.search_journals(
            query=query, filters=filters, limit=limit, offset=0
        )
    except MeilisearchError as exc:
        raise SearchServiceUnavailableError("MeiliSearch", str(exc)) from exc
    results = [_search_hit_to_result(hit) for hit in raw.get("hits", [])]
    return (
        results,
        int(raw.get("estimated_total_hits", len(results))),
        int(raw.get("processing_time_ms", 0)),
    )


async def _zero_result_diagnostics(
    repos: _JournalToolRepositories,
    user_id: str,
    *,
    search_backend: str,
    filters: dict[str, Any],
    source_filter: str | None = None,
    journals_linked_to_source: int | None = None,
    suggestions: list[str],
) -> SearchDiagnostics:
    """Explain an empty result so the agent can tell absence from a bad query."""
    total = await repos.journal_repo.count_all(user_id=user_id)
    if source_filter is not None and journals_linked_to_source is None:
        journals_linked_to_source = len(
            await _fetch_journal_ids_by_integration_source(
                repos.journal_repo.conn, user_id, source_filter
            )
        )
    return SearchDiagnostics(
        search_backend=search_backend,
        filters={k: v for k, v in filters.items() if v not in (None, "", [])},
        journals_for_user_total=total,
        journals_linked_to_source=journals_linked_to_source,
        suggestions=suggestions,
    )


_SEARCH_SUGGESTIONS = [
    "Try fewer or different words — every word must match somewhere in the "
    "title, content or location (typos are tolerated).",
    "If you know roughly when it happened, use browse_journals_by_date_window.",
    "For activities, search_activities filters by activity type and date.",
    "Drop the types / integration_source filter to see whether it excluded "
    "the journal.",
]

_WINDOW_SUGGESTIONS = [
    "Widen the window (days_back / days_forward) or move anchor_date.",
    "Dates are matched on the journal's event date range, in UTC.",
    "Use search_journals for a text search without a date restriction.",
]


@mcp_unified_error_handler("search_journals", "journal")
async def search_journals(
    query: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Search query for full-text search",
        ),
    ] = None,
    types: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Comma-separated list of journal types to filter by",
        ),
    ] = None,
    integration_source: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Filter by integration source (e.g. 'strava', "
            "'google_calendar', 'immich_album'). "
            "Returns only journals linked to the specified external system.",
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=20,
            description="Maximum number of results to return (default: 20)",
        ),
    ] = 20,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    search_service: SearchService = mcp_depends(get_search_service),
) -> str:
    """
    Search journals with filtering options.

    With a ``query``, the search runs through MeiliSearch exactly like the web
    UI (word matching, typo tolerance, relevance ranking) — not a literal
    substring match — so "Zion canyoning" finds a canyoning journal whose text
    mentions Zion. Without a query, journals are listed from the database
    (newest first), optionally narrowed by ``types`` / ``integration_source``.
    If MeiliSearch is unreachable the tool returns an explicit
    "Search unavailable" error, never a silent empty result.

    Args:
        query: Optional search query for full-text search
        types: Optional comma-separated list of journal types
        integration_source: Optional integration source filter (strava, google_calendar)
        limit: Maximum number of results to return

    Returns:
        JSON string containing AI-friendly search results with:
        - List of matching journals with excerpts
        - Search metadata (total hits, processing time)
        - Contextual summary for AI understanding

    Raises:
        ValueError: If invalid filter values are provided
    """
    user_id = await get_current_user_id()
    repos = _create_journal_tool_repositories(db_connection)
    type_filters = _parse_type_filters(types)
    source_filter = _parse_integration_source_filter(integration_source)

    # When integration_source filter is active, fetch journal IDs matching
    # the source first, then intersect with other filters.
    source_journal_ids: set[int] | None = None
    if source_filter is not None:
        source_journal_ids = await _fetch_journal_ids_by_integration_source(
            db_connection, user_id, source_filter
        )
        if not source_journal_ids:
            # No journals match the integration source — return empty, and say
            # whether anything is linked to that source at all.
            response = JournalSearchResponse(
                results=[],
                query=query,
                total_hits=0,
                processing_time_ms=0,
                summary=f"Found 0 journal(s) linked to {source_filter}",
                diagnostics=await _zero_result_diagnostics(
                    repos,
                    user_id,
                    search_backend="database",
                    filters={"integration_source": source_filter, "types": types},
                    journals_linked_to_source=0,
                    suggestions=[
                        f"No journal is linked to {source_filter}. Check "
                        "list_integrations, or trigger_sync if the integration "
                        "is connected but has not imported yet.",
                        *_SEARCH_SUGGESTIONS[:2],
                    ],
                ),
            )
            return MCPResponseBuilder.success_response(response)

    summary_suffix = f" linked to {source_filter}" if source_filter else ""

    if query and query.strip():
        try:
            results, total_hits, processing_time_ms = _meili_search_journals(
                search_service,
                query=query.strip(),
                user_id=user_id,
                limit=limit,
                type_filters=type_filters,
                journal_ids=source_journal_ids,
            )
        except SearchServiceUnavailableError as exc:
            return MCPResponseBuilder.error_response(
                error_type="Search unavailable",
                message=exc.message,
                context={"query": query, "hint": _SEARCH_UNAVAILABLE_HINT},
            )
        response = JournalSearchResponse(
            results=results,
            query=query,
            total_hits=total_hits,
            processing_time_ms=processing_time_ms,
            summary=f"Found {total_hits} journal(s){summary_suffix}",
            diagnostics=await _zero_result_diagnostics(
                repos,
                user_id,
                search_backend="meilisearch",
                filters={
                    "query": query,
                    "types": types,
                    "integration_source": source_filter,
                },
                source_filter=source_filter,
                journals_linked_to_source=(
                    len(source_journal_ids) if source_journal_ids else None
                ),
                suggestions=_SEARCH_SUGGESTIONS,
            )
            if total_hits == 0
            else None,
        )
        return MCPResponseBuilder.success_response(response)

    journal_ids = list(source_journal_ids) if source_journal_ids is not None else None
    if len(type_filters) <= 1:
        journal_type = type_filters[0] if type_filters else None
        total_hits = await repos.journal_repo.count_all(
            user_id=user_id, journal_type=journal_type, journal_ids=journal_ids
        )
        journals = await repos.journal_repo.get_all(
            user_id=user_id,
            limit=limit,
            offset=0,
            journal_type=journal_type,
            journal_ids=journal_ids,
        )
        results = await _build_search_results(journals, repos)
    else:
        candidate_count = await repos.journal_repo.count_all(
            user_id=user_id, journal_ids=journal_ids
        )
        journals = (
            await repos.journal_repo.get_all(
                user_id=user_id,
                limit=candidate_count,
                offset=0,
                journal_ids=journal_ids,
            )
            if candidate_count
            else []
        )
        requested_types = set(type_filters)
        results = []
        for journal in journals:
            if journal.id is None:
                continue
            journal_types, _ = await _fetch_types_for_journal(journal.id, repos)
            if requested_types.isdisjoint(journal_types):
                continue
            results.append(_journal_to_search_result(journal, types=journal_types))
        total_hits = len(results)
        results = results[:limit]

    response = JournalSearchResponse(
        results=results,
        query=query,
        total_hits=total_hits,
        processing_time_ms=0,
        summary=f"Found {total_hits} journal(s){summary_suffix}",
        diagnostics=await _zero_result_diagnostics(
            repos,
            user_id,
            search_backend="database",
            filters={"types": types, "integration_source": source_filter},
            source_filter=source_filter,
            journals_linked_to_source=(
                len(source_journal_ids) if source_journal_ids else None
            ),
            suggestions=_SEARCH_SUGGESTIONS[1:],
        )
        if total_hits == 0
        else None,
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("search_activities", "journal")
async def search_activities(
    query: Annotated[
        str | None,
        Field(default=None, description="Optional search query for title/content"),
    ] = None,
    activity_type: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional effective activity type filter",
        ),
    ] = None,
    start_date: Annotated[
        str | None,
        Field(default=None, description="Optional ISO start date/datetime filter"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(default=None, description="Optional ISO end date/datetime filter"),
    ] = None,
    limit: Annotated[
        int,
        Field(default=20, description="Maximum number of results to return"),
    ] = 20,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """Search activity journals with effective activity-type filtering."""
    user_id = await get_current_user_id()
    repos = _create_journal_tool_repositories(db_connection)
    total_hits = await _count_activity_rows(
        db_connection,
        user_id,
        search_query=query,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )

    activity_rows: list[_ActivityJournalRow] = []
    if total_hits > 0:
        activity_rows = await _fetch_activity_rows(
            db_connection,
            user_id,
            search_query=query,
            activity_type=activity_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=0,
        )

    results = await _build_search_results(
        [activity_row.journal for activity_row in activity_rows],
        repos,
        activity_rows_by_id={
            activity_row.journal.id: activity_row
            for activity_row in activity_rows
            if activity_row.journal.id is not None
        },
    )
    response = JournalSearchResponse(
        results=results,
        query=query,
        total_hits=total_hits,
        processing_time_ms=0,
        summary=f"Found {total_hits} activity journal(s)",
    )
    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("get_activity_stats", "journal")
async def get_activity_stats(
    activity_type: Annotated[
        str | None,
        Field(default=None, description="Optional effective activity type filter"),
    ] = None,
    start_date: Annotated[
        str | None,
        Field(default=None, description="Optional ISO start date/datetime filter"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(default=None, description="Optional ISO end date/datetime filter"),
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """Aggregate activity totals, breakdowns, and personal records."""
    user_id = await get_current_user_id()
    overall_stats_row = await _fetch_activity_overall_stats_row(
        db_connection,
        user_id,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )
    activity_type_rows = await _fetch_activity_type_stats_rows(
        db_connection,
        user_id,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )

    overall_totals = ActivityTotals(
        distance=int(getattr(overall_stats_row, "total_distance", 0) or 0),
        duration=int(getattr(overall_stats_row, "total_duration", 0) or 0),
        elevation_gain=int(getattr(overall_stats_row, "total_elevation_gain", 0) or 0),
        calories=int(getattr(overall_stats_row, "total_calories", 0) or 0),
    )

    activity_type_stats = [
        ActivityTypeStats(
            activity_type=row.activity_type,
            count=int(row.count or 0),
            total_distance=int(row.total_distance or 0),
            total_duration=int(row.total_duration or 0),
            total_elevation_gain=int(row.total_elevation_gain or 0),
            total_calories=int(row.total_calories or 0),
        )
        for row in activity_type_rows
    ]

    async def build_personal_record(
        metric_name: str,
    ) -> ActivityPersonalRecord | None:
        record_row = await _fetch_activity_personal_record_row(
            db_connection,
            user_id,
            metric_name=metric_name,
            activity_type=activity_type,
            start_date=start_date,
            end_date=end_date,
        )
        if record_row is None:
            return None

        return ActivityPersonalRecord(
            activity_type=record_row.activity_type,
            journal_id=int(record_row.journal_id),
            journal_title=record_row.journal_title,
            value=int(record_row.metric_value or 0),
        )

    personal_records = {
        "longest_distance": await build_personal_record("distance"),
        "longest_duration": await build_personal_record("duration"),
        "highest_elevation_gain": await build_personal_record("elevation_gain"),
        "most_calories": await build_personal_record("calories"),
    }
    total_activities = int(getattr(overall_stats_row, "total_activities", 0) or 0)

    response = ActivityStatsResponse(
        total_activities=total_activities,
        overall_totals=overall_totals,
        activity_types=activity_type_stats,
        personal_records=personal_records,
        summary=(
            f"Analysed {total_activities} activity journal(s) across "
            f"{len(activity_type_stats)} activity type(s)"
        ),
    )
    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("analyze_activity_trends", "journal")
async def analyze_activity_trends(
    interval: Annotated[
        str,
        Field(
            default="month",
            description="Trend interval: day, week, month, or year",
        ),
    ] = "month",
    activity_type: Annotated[
        str | None,
        Field(default=None, description="Optional effective activity type filter"),
    ] = None,
    start_date: Annotated[
        str | None,
        Field(default=None, description="Optional ISO start date/datetime filter"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(default=None, description="Optional ISO end date/datetime filter"),
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """Analyse activity trends by day, week, month, or year buckets."""
    normalized_interval = interval.strip().lower()
    if normalized_interval not in {"day", "week", "month", "year"}:
        raise ValueError("interval must be one of: day, week, month, year")

    user_id = await get_current_user_id()
    trend_rows = await _fetch_activity_trend_rows(
        db_connection,
        user_id,
        interval=normalized_interval,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )

    periods = [
        ActivityTrendPeriod(
            period_start=row.period_start.isoformat(),
            activity_count=int(row.activity_count or 0),
            total_distance=int(row.total_distance or 0),
            total_duration=int(row.total_duration or 0),
            total_elevation_gain=int(row.total_elevation_gain or 0),
        )
        for row in trend_rows
    ]
    total_activities = sum(period.activity_count for period in periods)

    response = ActivityTrendsResponse(
        interval=normalized_interval,
        total_activities=total_activities,
        periods=periods,
        summary=(
            f"Analysed {total_activities} activity journal(s) across "
            f"{len(periods)} {normalized_interval} bucket(s)"
        ),
    )
    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("get_route_history", "journal")
async def get_route_history(
    route_id: Annotated[str, Field(description="Route UUID")],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """Return route usage history across route-aware activity journals."""
    user_id = await get_current_user_id()
    repos = _create_journal_tool_repositories(db_connection)

    try:
        route_uuid = UUID(route_id)
    except ValueError as exc:
        raise ValueError(
            f"Invalid route_id '{route_id}'. Must be a valid UUID."
        ) from exc

    route = await repos.route_repo.find_by_id(route_uuid)
    if route is None:
        return MCPResponseBuilder.not_found_error_response("Route", route_id)

    journal = await repos.journal_repo.find_by_id(route.journal_id)
    if journal is None or journal.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Route", route_id)

    history_rows = await _fetch_route_history_rows(db_connection, user_id, route_uuid)
    entries = [
        RouteHistoryEntry(
            journal_id=row.id,
            journal_title=row.title,
            activity_type=row.activity_type,
            event_date_range=EventDateRangeSchema(
                start=row.event_date_range_start,
                end=row.event_date_range_end,
            ),
            distance=int(row.distance) if row.distance is not None else None,
            duration=int(row.duration) if row.duration is not None else None,
        )
        for row in history_rows
    ]
    activity_types = sorted(
        {entry.activity_type for entry in entries if entry.activity_type is not None}
    )

    response = RouteHistoryResponse(
        route=RouteSummary(
            id=str(route.id or route_uuid),
            name=route.name,
            description=route.description,
        ),
        usage_count=len(entries),
        activity_types=activity_types,
        entries=entries,
        summary=(
            f"Route '{route.name}' has been used {len(entries)} time(s) across "
            f"{len(activity_types)} activity type(s)"
        ),
    )
    return MCPResponseBuilder.success_response(response)


def _journal_history_entry_to_schema(
    entry: FieldHistoryEntry,
) -> JournalHistoryEntry:
    """Map a domain ``FieldHistoryEntry`` to the MCP schema.

    Mirrors the REST ``HistoryConverter`` value coercion (Provenance enum →
    string, ISO string → datetime) so the MCP tool returns exactly the same
    field-level detail and provenance the UI shows.
    """
    created_at: datetime | None = None
    if entry.created_at:
        if isinstance(entry.created_at, str):
            try:
                created_at = datetime.fromisoformat(entry.created_at)
            except ValueError:
                created_at = None
        else:
            created_at = entry.created_at

    source = entry.source.value if hasattr(entry.source, "value") else str(entry.source)

    return JournalHistoryEntry(
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        field_name=entry.field_name,
        old_value=entry.old_value,
        new_value=entry.new_value,
        changed_by=entry.changed_by,
        source=source,
        created_at=created_at,
    )


@mcp_unified_error_handler("get_journal_history", "journal")
async def get_journal_history(
    journal_id: Annotated[
        int, Field(description="The unique identifier of the journal")
    ],
    page: Annotated[int, Field(description="Page number (1-based)", ge=1)] = 1,
    limit: Annotated[int, Field(description="Entries per page", ge=1, le=100)] = 20,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """Return a journal's field-level change history with provenance.

    Provides AI-agent parity with the REST ``GET /api/journals/{id}/history``
    endpoint: paginated, most-recent-first entries covering the journal's own
    fields plus its type-specific data, routes, and gear, each tagged with its
    origin (UI, MCP, an external sync, etc.). History is produced asynchronously
    by the projection consumer, so a just-made change may take a moment to
    appear.
    """
    user_id = await get_current_user_id()
    repos = _create_journal_tool_repositories(db_connection)

    # Scope to the authenticated user: a journal owned by someone else is
    # reported as not-found so history cannot leak across users (mirrors
    # get_route_history and the REST endpoint).
    journal = await repos.journal_repo.find_by_id(journal_id)
    if journal is None or journal.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    history_service = JournalHistoryService(SqlFieldHistoryRepository(db_connection))

    offset = (page - 1) * limit
    history_entries = await history_service.get_journal_history(
        journal_id=journal_id,
        limit=limit,
        offset=offset,
    )
    total_count = await history_service.get_journal_history_count(
        journal_id=journal_id,
    )

    entries = [_journal_history_entry_to_schema(entry) for entry in history_entries]

    response = JournalHistoryResponse(
        journal_id=journal_id,
        total_count=total_count,
        page=page,
        limit=limit,
        entries=entries,
        summary=(
            f"Journal {journal_id} has {total_count} recorded change(s); "
            f"showing {len(entries)} on page {page}."
        ),
    )
    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("delete_journal", "journal")
async def delete_journal(
    journal_id: Annotated[
        int, Field(description="The unique identifier of the journal to delete")
    ],
    delete_children: Annotated[
        bool,
        Field(
            default=False,
            description="Optional: Delete child journals as well",
        ),
    ] = False,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    event_publisher: OutboxEventPublisher = mcp_depends(get_outbox_event_publisher),
) -> str:
    """
    Delete a journal entry.

    Deletes a journal entry and optionally its children.
    Returns confirmation response.

    Deletion is refused while any task is anchored to this journal as its
    creating or due journal — whatever that task's status, since a done task's
    link to the journal it was created in is part of the record. Cancel,
    complete or retarget those tasks first, or cancel the journal instead of
    deleting it. A journal a task merely mentions can be deleted; the mention
    goes with it and the task is unaffected.

    The refusal is resolvable without a UI: it comes back with
    ``code: "JOURNAL_HAS_ANCHORED_TASKS"``, an explanatory ``message``, the
    ``journal_id`` that could not be deleted, and a ``blocking_tasks`` list.
    Each entry gives the task's ``task_id``, ``text``, ``status`` and
    ``blocking_roles`` (``creating`` and/or ``due``) plus the
    ``action_journal_id`` and ``action_journal_title`` of the journal that
    surfaces it — normally the task's due journal, or its creating journal when
    the due journal is the one being deleted. Read that journal, deal with the
    task there, and retry.

    Args:
        journal_id: The unique identifier of the journal to delete
        delete_children: Optional flag to delete child journals

    Returns:
        JSON string containing deletion confirmation

    Raises:
        JournalNotFoundError: If the journal with the given ID does not exist
        JournalHasAnchoredTasksError: If a task is anchored to the journal
    """
    # Explicitly reject unsupported delete_children behavior to avoid silent misuse
    if delete_children:
        raise NotImplementedError(
            "The 'delete_children' flag is not yet supported. "
            "Child journals are not deleted automatically."
        )

    # Create repositories
    journal_repo = SqlJournalRepository(db_connection)
    contact_relationship_repo = SqlJournalContactRelationshipRepository(db_connection)

    # Somebody else's journal is reported as missing rather than refused, so
    # neither the deletion nor the explanation it can now return says anything
    # about a journal that is not yours. Same check as the read tool above.
    user_id = await get_current_user_id()
    journal = await journal_repo.find_by_id(journal_id)
    if not journal or str(journal.user_id) != str(user_id):
        raise JournalNotFoundError(journal_id)

    journal_service = JournalService(
        journal_repo,
        event_publisher,
        contact_relationship_repo,
        task_anchor_repo=SqlTaskAnchorRepository(db_connection),
    )

    # Delete journal
    await journal_service.delete_journal(
        journal_id, db_connection, changed_by="mcp", source=Provenance.MCP
    )

    class DeleteResponse(BaseModel):
        journal_id: int
        deleted: bool
        summary: str

    response = DeleteResponse(
        journal_id=journal_id,
        deleted=True,
        summary=f"Successfully deleted journal {journal_id}",
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("get_contact_journals", "journal")
async def get_contact_journals(
    contact_id: Annotated[
        int, Field(description="The unique identifier of the contact")
    ],
    limit: Annotated[
        int,
        Field(
            default=20,
            description="Maximum number of results to return (default: 20)",
        ),
    ] = 20,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get journals associated with a contact.

    Retrieves journals that have relationships with the specified contact.
    Returns AI-friendly summaries.

    Args:
        contact_id: The unique identifier of the contact
        limit: Maximum number of results to return

    Returns:
        JSON string containing AI-friendly journal summaries

    Raises:
        ContactNotFoundError: If the contact with the given ID does not exist
    """
    # Create repositories
    contact_rel_repo = SqlJournalContactRelationshipRepository(db_connection)
    journal_repo = SqlJournalRepository(db_connection)

    # Get relationships
    relationships = await contact_rel_repo.get_by_contact(contact_id)

    # Get journals
    journals = []
    for rel in relationships[:limit]:
        journal = await journal_repo.find_by_id(rel.journal_id)
        if journal:
            journals.append(journal)

    # Convert to search results
    results = [_journal_to_search_result(journal) for journal in journals]

    response = JournalSearchResponse(
        results=results,
        query=None,
        total_hits=len(results),
        processing_time_ms=0,
        summary=f"Found {len(results)} journal(s) for contact {contact_id}",
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("link_journal_to_contact", "journal")
async def link_journal_to_contact(
    journal_id: Annotated[
        int, Field(description="The unique identifier of the journal")
    ],
    contact_id: Annotated[
        int, Field(description="The unique identifier of the contact")
    ],
    relationship_type: Annotated[
        str,
        Field(description="Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)"),
    ],
    status: Annotated[
        str | None,
        Field(
            description="Attendee status: ATTENDING, ATTENDED, MAYBE, NO_REPLY, DECLINED"
        ),
    ] = None,
    role: Annotated[
        str | None,
        Field(description="Event role: ORGANISER, FACILITATOR_HELPER"),
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    journal_contact_service: JournalContactService = mcp_depends(
        get_journal_contact_service
    ),
) -> str:
    """
    Link a journal to a contact with a specific relationship type.

    Creates a relationship between a journal and a contact.
    Returns confirmation response.

    Args:
        journal_id: The unique identifier of the journal
        contact_id: The unique identifier of the contact
        relationship_type: Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)

    Returns:
        JSON string containing relationship creation confirmation

    Raises:
        ValueError: If relationship is invalid, or if journal or contact do not exist.
    """
    # Validate relationship type
    try:
        relationship_enum = JournalContactRelationshipType[relationship_type.upper()]
    except KeyError as e:
        raise ValueError(f"Invalid relationship_type: {relationship_type}") from e

    # Parse status and role if present
    from core_shared.models.journals.attendee_status import AttendeeStatus
    from core_shared.models.journals.contact_event_role import ContactEventRole

    status_enum, role_enum = None, None
    if status is not None:
        try:
            status_enum = AttendeeStatus[status.upper()]
        except KeyError as e:
            raise ValueError(f"Invalid status: {status}") from e

    if role is not None:
        try:
            role_enum = ContactEventRole[role.upper()]
        except KeyError as e:
            raise ValueError(f"Invalid role: {role}") from e

    # Create repositories
    repos = _create_journal_tool_repositories(db_connection)

    # Check that contact and journal exist. The journal is read owner-scoped:
    # linking writes a row to it, so somebody else's must be as unreachable
    # here as it is through the read tool (#1267).
    user_id = await get_current_user_id()
    journal = await repos.journal_repo.find_by_id_for_user(journal_id, str(user_id))
    if not journal:
        raise ValueError(f"Could not find journal with ID {journal_id}")

    contact = await repos.contact_repo.find_by_id(contact_id)
    if not contact:
        raise ValueError(f"Could not find contact with ID {contact_id}")

    rel = JournalContactRelationship(
        journal_id=journal_id,
        contact_id=contact_id,
        relationship_type=relationship_enum,
        status=status_enum,
        role=role_enum,
    )

    import sqlalchemy.exc

    try:
        await journal_contact_service.add_contact_to_journal(
            rel, transaction=db_connection
        )
    except sqlalchemy.exc.IntegrityError as e:
        raise ValueError("Relationship already exists") from e

    class LinkResponse(BaseModel):
        journal_id: int
        contact_id: int
        relationship_type: str
        status: str | None
        role: str | None
        linked: bool
        summary: str

    response = LinkResponse(
        journal_id=journal_id,
        contact_id=contact_id,
        relationship_type=relationship_enum.value,
        status=status_enum.value if status_enum is not None else None,
        role=role_enum.value if role_enum is not None else None,
        linked=True,
        summary=f"Successfully linked journal {journal_id} to contact {contact_id} as {relationship_enum.value}",
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("list_calendars", "journal")
async def list_calendars(
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List all calendars available for EVENT journals.
    """
    user_id = await get_current_user_id()
    calendar_repo = SqlCalendarRepository(db_connection)

    calendars = await calendar_repo.get_all(user_id=user_id)

    class CalendarListItem(BaseModel):
        id: str
        name: str
        description: str | None = None
        color: str | None = None

    class CalendarListResponse(BaseModel):
        calendars: list[CalendarListItem]

    response = CalendarListResponse(
        calendars=[
            CalendarListItem(
                id=str(c.id),
                name=c.name,
                description=c.description,
                color=c.color,
            )
            for c in calendars
        ]
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("create_calendar", "journal")
async def create_calendar(
    name: Annotated[str, Field(description="Calendar name")],
    description: Annotated[
        str | None, Field(description="Calendar description", default=None)
    ] = None,
    color: Annotated[
        str | None, Field(description="Calendar color hex code", default=None)
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    calendar_service: CalendarService = mcp_depends(get_calendar_service),
) -> str:
    """
    Create a new calendar to be used with EVENT journals.
    """
    user_id = await get_current_user_id()

    new_calendar = Calendar(
        user_id=user_id,
        name=name,
        description=description,
        color=color or "#3B82F6",
        is_synced_to_google=False,
        google_calendar_id=None,
    )

    saved_calendar = await calendar_service.create_calendar(
        new_calendar, transaction=db_connection
    )

    class CalendarResponse(BaseModel):
        id: str
        name: str
        summary: str

    return MCPResponseBuilder.success_response(
        CalendarResponse(
            id=str(saved_calendar.id),
            name=saved_calendar.name,
            summary=f"Created calendar '{saved_calendar.name}'",
        )
    )


@mcp_unified_error_handler("update_calendar", "journal")
async def update_calendar(
    calendar_id: Annotated[str, Field(description="Calendar UUID")],
    name: Annotated[
        str | None, Field(description="Calendar name", default=None)
    ] = None,
    description: Annotated[
        str | None, Field(description="Calendar description", default=None)
    ] = None,
    color: Annotated[
        str | None, Field(description="Calendar color hex code", default=None)
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    calendar_service: CalendarService = mcp_depends(get_calendar_service),
) -> str:
    """
    Update an existing calendar.
    """
    user_id = await get_current_user_id()
    calendar_repo = SqlCalendarRepository(db_connection)

    calendar_uuid = _parse_calendar_id(calendar_id)
    if calendar_uuid is None:
        raise ValueError(f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID.")

    calendar = await calendar_repo.find_by_id(calendar_uuid)
    if not calendar or calendar.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Calendar", calendar_id)

    if name is not None:
        calendar.name = name
    if description is not None:
        calendar.description = description
    if color is not None:
        calendar.color = color

    saved_calendar = await calendar_service.update_calendar(
        calendar, transaction=db_connection
    )

    class CalendarResponse(BaseModel):
        id: str
        name: str
        summary: str

    return MCPResponseBuilder.success_response(
        CalendarResponse(
            id=str(saved_calendar.id),
            name=saved_calendar.name,
            summary=f"Updated calendar '{saved_calendar.name}'",
        )
    )


@mcp_unified_error_handler("delete_calendar", "journal")
async def delete_calendar(
    calendar_id: Annotated[str, Field(description="Calendar UUID")],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    calendar_service: CalendarService = mcp_depends(get_calendar_service),
) -> str:
    """
    Delete a calendar. Will fail if the calendar is in use.
    """
    user_id = await get_current_user_id()
    calendar_repo = SqlCalendarRepository(db_connection)

    calendar_uuid = _parse_calendar_id(calendar_id)
    if calendar_uuid is None:
        raise ValueError(f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID.")

    calendar = await calendar_repo.find_by_id(calendar_uuid)
    if not calendar or calendar.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Calendar", calendar_id)

    check_query = text(
        """
        SELECT COUNT(*) as count
        FROM journal_calendar_info
        WHERE calendar_id = :calendar_id
        """
    )
    result = await db_connection.execute(check_query, {"calendar_id": str(calendar.id)})
    usage_count = int(result.scalar_one())

    if usage_count > 0:
        return MCPResponseBuilder.error_response(
            "CONFLICT",
            f"Calendar is in use by {usage_count} journal(s)",
        )

    if calendar.id is not None:
        await calendar_service.delete_calendar(
            calendar, user_id, transaction=db_connection
        )

    class DeleteCalendarResponse(BaseModel):
        summary: str

    return MCPResponseBuilder.success_response(
        DeleteCalendarResponse(summary=f"Deleted calendar '{calendar.name}'")
    )


@mcp_unified_error_handler("merge_journals", "journal")
async def merge_journals(
    target_journal_id: Annotated[
        int,
        Field(description="The ID of the journal to keep (the merge target)"),
    ],
    merge_data: Annotated[
        str,
        Field(
            description=(
                "JSON string with merge parameters. Required key: "
                '"source_journal_id" (int) — the journal to absorb and delete. '
                'Optional keys: "overrides" (object) — explicit conflict resolution '
                'with keys: "title" (str), "content" (str), '
                '"event_date_range" ({start, end}), '
                '"type_data" ({TYPE: {field: value}}); '
                '"fitness_merge_mode" ("replace" | "additive") — how to combine '
                'fitness data, defaulting to "replace"'
            )
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    event_publisher: OutboxEventPublisher = mcp_depends(get_outbox_event_publisher),
) -> str:
    """
    Merge a source journal into a target journal.

    The source journal's content, tags, contacts, type data, routes,
    and child journals are absorbed into the target. The source is then
    deleted. Use 'overrides' to resolve conflicts explicitly (title,
    content, date range, or type-specific data).

    When both journals hold fitness data, 'fitness_merge_mode' decides how to
    reconcile it. The default 'replace' keeps the target's metrics and drops
    the source's integration links — the right choice for a duplicate or a
    re-import. Pass 'additive' when the two journals are two parts of one
    outing (a ride split by a stopped recording, an activity logged on two
    devices): distance, duration, elevation and calories sum, heart rates
    combine, and both journals' Strava activities stay linked to the survivor.

    Call get_merge_candidates first to find suitable merge targets.

    Args:
        target_journal_id: ID of the journal to keep
        merge_data: JSON string containing source_journal_id, optional overrides
            and optional fitness_merge_mode

    Returns:
        JSON string containing the merged target journal with all combined data
    """
    merge_request = MergeJournalMCPRequest.model_validate_json(merge_data)

    repos = _create_journal_tool_repositories(db_connection)

    # Verify ownership — both journals must belong to the current user
    user_id = await get_current_user_id()
    target = await repos.journal_repo.find_by_id(target_journal_id)
    if not target or target.user_id != user_id:
        raise JournalNotFoundError(target_journal_id)
    source = await repos.journal_repo.find_by_id(merge_request.source_journal_id)
    if not source or source.user_id != user_id:
        raise JournalNotFoundError(merge_request.source_journal_id)

    # The anchor repository is built here rather than added to the shared journal
    # tool repositories: merge is the only journal tool that touches task links.
    merge_service = JournalMergeService(
        repos.journal_repo, event_publisher, SqlTaskAnchorRepository(db_connection)
    )

    merged_journal = await merge_service.merge_journals(
        target_id=target_journal_id,
        source_id=merge_request.source_journal_id,
        transaction=db_connection,
        overrides=merge_request.overrides,
        fitness_merge_mode=merge_request.fitness_merge_mode,
    )

    # Fetch enriched target
    types, type_data = await _fetch_journal_types_and_data(target_journal_id, repos)

    contacts = await _fetch_contact_relationships_with_names(
        target_journal_id,
        repos.contact_relationship_repo,
        repos.contact_repo,
    )

    journal_tags = await repos.tag_repo.get_tags_for_journal(target_journal_id)

    # The merge leaves the survivor's parent_id alone, so the response has to
    # report it — otherwise the target reads back as orphaned.
    parent = await _fetch_parent_journal(merged_journal, repos.journal_repo, user_id)

    response = JournalConverter.to_response(
        journal=merged_journal,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=journal_tags,
        parent=parent,
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("get_merge_candidates", "journal")
async def get_merge_candidates(
    journal_id: Annotated[
        int,
        Field(description="The ID of the journal to find merge candidates for"),
    ],
    limit: Annotated[
        int,
        Field(
            default=10,
            description="Maximum number of candidates to return (default: 10)",
        ),
    ] = 10,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Find journals that could be merged with a given journal.

    Returns journals with overlapping date ranges belonging to the same
    user, ordered by start date. Use this before merge_journals
    to identify suitable merge targets.

    Args:
        journal_id: The journal to find candidates for
        limit: Maximum number of candidates to return

    Returns:
        JSON string with merge candidate summaries and AI recommendations
    """
    repos = _create_journal_tool_repositories(db_connection)

    # Owner-scoped, and it matters more here than anywhere else: the candidate
    # query below used to scope itself to ``target.user_id`` — the *owner's* id,
    # not the caller's — so one foreign journal id returned a list of that
    # user's overlapping journals, titles and content included (#1267).
    user_id = str(await get_current_user_id())
    target = await repos.journal_repo.find_by_id_for_user(journal_id, user_id)
    if not target:
        raise JournalNotFoundError(journal_id)

    # Find journals with overlapping date ranges for the same user
    query = text("""
        SELECT j.id, j.title, j.content,
               j.event_date_range_start, j.event_date_range_end
        FROM journals j
        WHERE j.user_id = :user_id
          AND j.id != :journal_id
          AND j.event_date_range_start <= :end_date
          AND j.event_date_range_end >= :start_date
        ORDER BY j.event_date_range_start
        LIMIT :limit
    """)

    result = await db_connection.execute(
        query,
        {
            # The caller's id, not the target's. They are the same id now that
            # the read above is owner-scoped, and saying so keeps them the same
            # if that guard is ever moved.
            "user_id": user_id,
            "journal_id": journal_id,
            "start_date": target.event_date_range.start,
            "end_date": target.event_date_range.end,
            "limit": max(1, min(limit, 50)),
        },
    )
    rows = result.fetchall()

    candidates: list[MergeCandidateResult] = []
    for row in rows:
        candidate_id = int(row[0])
        candidate_title = str(row[1])
        candidate_content = str(row[2]) if row[2] else ""
        candidate_start = row[3]
        candidate_end = row[4]

        # Fetch types and tags for each candidate
        c_types, _ = await _fetch_journal_types_and_data(candidate_id, repos)
        c_tags = await repos.tag_repo.get_tags_for_journal(candidate_id)
        tag_names = [t.name for t in c_tags]

        content_excerpt = candidate_content[:200]
        candidates.append(
            MergeCandidateResult(
                id=candidate_id,
                title=candidate_title,
                content_excerpt=content_excerpt,
                event_date_range=EventDateRangeSchema(
                    start=candidate_start,
                    end=candidate_end,
                ),
                types=c_types,
                tags=tag_names,
                summary=(
                    f"'{candidate_title}' ({', '.join(c_types)}) "
                    f"overlaps with target date range"
                ),
            )
        )

    summary_text = (
        f"Found {len(candidates)} merge candidate(s) for "
        f"'{target.title}' (ID: {journal_id})"
    )
    if candidates:
        summary_text += ". Review each candidate and use merge_journals to combine."
    else:
        summary_text += ". No journals with overlapping date ranges found."

    response = MergeCandidatesResponse(
        target_journal_id=journal_id,
        target_title=target.title,
        candidates=candidates,
        summary=summary_text,
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("browse_journals_by_date_window", "journal")
async def browse_journals_by_date_window(
    anchor_date: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional ISO date to anchor the window on (defaults to today). "
                "Example: '2026-04-02'"
            ),
        ),
    ] = None,
    days_back: Annotated[
        int,
        Field(
            default=2,
            ge=0,
            description="Number of days before the anchor date to include (default: 2)",
        ),
    ] = 2,
    days_forward: Annotated[
        int,
        Field(
            default=4,
            ge=0,
            description="Number of days after the anchor date to include (default: 4)",
        ),
    ] = 4,
    types: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional comma-separated journal types to filter by",
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional text search query within the window",
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=50,
            ge=1,
            description="Maximum results to return per page (default: 50)",
        ),
    ] = 50,
    offset: Annotated[
        int,
        Field(
            default=0,
            ge=0,
            description="Number of results to skip for pagination (default: 0)",
        ),
    ] = 0,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    search_service: SearchService = mcp_depends(get_search_service),
) -> str:
    """
    Browse journals within a date window anchored on a given date.

    Returns journals falling within [anchor - days_back, anchor + days_forward].
    Defaults to a 7-day window (2 days back, 4 days forward from today).
    Supports pagination via offset/limit and optional type/search filters.

    Use this tool for time-oriented journal browsing, such as seeing
    what happened recently or what is coming up.

    Args:
        anchor_date: ISO date string to centre the window on (defaults to today)
        days_back: Days before the anchor to include
        days_forward: Days after the anchor to include
        types: Comma-separated journal types to filter by
        search: Text search query
        limit: Page size
        offset: Pagination offset

    Returns:
        JSON with journals in the window, window boundaries, and pagination info
    """
    user_id = await get_current_user_id()
    repos = _create_journal_tool_repositories(db_connection)

    # Resolve anchor date
    if anchor_date is not None:
        try:
            resolved_anchor = date.fromisoformat(anchor_date.strip())
        except ValueError as exc:
            raise ValueError(
                f"Invalid anchor_date '{anchor_date}'. Must be ISO format (YYYY-MM-DD)."
            ) from exc
    else:
        resolved_anchor = datetime.now(UTC).date()

    window_start, window_end = compute_date_window(
        resolved_anchor, days_back, days_forward
    )

    start_iso = window_start.isoformat()
    # Use end-of-day for window_end so journals occurring later on that
    # day are included (the repo compares event_date_range_start <= end_date,
    # and date.isoformat() alone yields midnight which would exclude them).
    end_iso = datetime.combine(window_end, dt_time(23, 59, 59), tzinfo=UTC).isoformat()

    type_filters = _parse_type_filters(types)
    journal_type = type_filters[0] if len(type_filters) == 1 else None

    total_count = await repos.journal_repo.count_all(
        user_id=user_id,
        journal_type=journal_type,
        start_date=start_iso,
        end_date=end_iso,
    )

    if search and search.strip():
        # Text search inside the window goes through MeiliSearch (word matching
        # and typo tolerance, as in the web UI) restricted to the window's
        # journal ids, rather than a literal substring match.
        in_window = await repos.journal_repo.get_all(
            user_id=user_id,
            limit=max(total_count, 1),
            offset=0,
            journal_type=journal_type,
            start_date=start_iso,
            end_date=end_iso,
        )
        window_ids = {j.id for j in in_window if j.id is not None}
        try:
            matched, _total, _ms = _meili_search_journals(
                search_service,
                query=search.strip(),
                user_id=user_id,
                limit=max(len(window_ids), 1),
                type_filters=type_filters,
                journal_ids=window_ids,
            )
        except SearchServiceUnavailableError as exc:
            return MCPResponseBuilder.error_response(
                error_type="Search unavailable",
                message=exc.message,
                context={"search": search, "hint": _SEARCH_UNAVAILABLE_HINT},
            )
        total_count = len(matched)
        results = matched[offset : offset + limit]
    else:
        journals = await repos.journal_repo.get_all(
            user_id=user_id,
            limit=limit,
            offset=offset,
            journal_type=journal_type,
            start_date=start_iso,
            end_date=end_iso,
        )
        results = await _build_search_results(journals, repos)

    has_more = (offset + limit) < total_count

    response = JournalDateWindowResponse(
        results=results,
        window_start=start_iso,
        window_end=window_end.isoformat(),
        anchor_date=resolved_anchor.isoformat(),
        total_count=total_count,
        has_more=has_more,
        summary=(
            f"Found {total_count} journal(s) between "
            f"{start_iso} and {window_end.isoformat()} "
            f"(anchored on {resolved_anchor.isoformat()})"
        ),
        diagnostics=await _zero_result_diagnostics(
            repos,
            user_id,
            search_backend="meilisearch" if search and search.strip() else "database",
            filters={
                "window_start": start_iso,
                "window_end": window_end.isoformat(),
                "types": types,
                "search": search,
            },
            suggestions=(
                [*_WINDOW_SUGGESTIONS, _SEARCH_SUGGESTIONS[0]]
                if search
                else _WINDOW_SUGGESTIONS
            ),
        )
        if total_count == 0
        else None,
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("list_review_items", "journal")
async def list_review_items(
    limit: Annotated[
        int,
        Field(
            default=20,
            description="Maximum number of results to return (default: 20)",
        ),
    ] = 20,
    offset: Annotated[
        int,
        Field(
            default=0,
            description="Number of results to skip (default: 0)",
        ),
    ] = 0,
    status: Annotated[
        str,
        Field(
            default="pending",
            description="Filter by items status, must be 'pending' for now",
        ),
    ] = "pending",
    user_id_override: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Only for use in tests. Override the user_id.",
        ),
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List pending journal review items for the user.

    Retrieves a list of journals that might need merging, deduplication,
    or review. Used typically to show pending tasks in a queue/sidebar.

    Returns AI-friendly response containing reason, confidence score, and
    candidate journal ids for review.
    """
    # Determine the user ID using similar logic to other tools
    # The user ID is usually extracted from the context, or we can use a helper if we have it
    # Actually tools usually take the test_user_id from context if provided.
    user_id = user_id_override or "dev-system-user"

    if status != "pending":
        return json.dumps({"error": "Only 'pending' status is currently supported"})

    review_item_repo = SqlReviewItemRepository(db_connection)

    items = await review_item_repo.find_pending_by_user(
        user_id, limit=limit, offset=offset
    )
    total_count = await review_item_repo.count_pending_by_user(user_id)

    # Batch-fetch journal summaries for context
    journal_ids = set()
    for item in items:
        journal_ids.add(item.source_journal_id)
        journal_ids.add(item.candidate_journal_id)

    journal_repo = SqlJournalRepository(db_connection)

    journals = await journal_repo.find_by_ids_for_user(user_id, list(journal_ids))
    journal_map = {j.id: j for j in journals if j.id is not None}

    # Build response payload
    results = []
    for item in items:
        source_journal = journal_map.get(item.source_journal_id)
        candidate_journal = journal_map.get(item.candidate_journal_id)

        results.append(
            {
                "id": item.id,
                "status": item.status,
                "reason": item.reason.value
                if hasattr(item.reason, "value")
                else item.reason,
                "confidence_score": item.confidence_score,
                "details": item.details,
                "source_journal": {
                    "id": item.source_journal_id,
                    "title": source_journal.title
                    if source_journal
                    else f"Journal {item.source_journal_id}",
                },
                "candidate_journal": {
                    "id": item.candidate_journal_id,
                    "title": candidate_journal.title
                    if candidate_journal
                    else f"Journal {item.candidate_journal_id}",
                },
            }
        )

    response_data = {
        "meta": {"total_count": total_count, "offset": offset, "limit": limit},
        "data": results,
        "summary": f"Found {total_count} pending review item(s).",
    }

    return json.dumps(response_data, indent=2)


@mcp_unified_error_handler("dismiss_review_item", "journal")
async def dismiss_review_item(
    item_id: int,
    user_id_override: str | None = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    review_item_service: ReviewItemService = mcp_depends(get_review_item_service),
) -> str:
    """
    Dismiss a journal review item.

    Use this tool to dismiss a pending merge candidate review item that the user
    has determined is not a match or should not be merged.
    """
    user_id = user_id_override or "dev-system-user"

    item = await review_item_service.dismiss(
        item_id, user_id, transaction=db_connection
    )

    if not item:
        return json.dumps({"error": f"Review item {item_id} not found."})

    return json.dumps(
        {
            "success": True,
            "message": f"Successfully dismissed review item {item_id}.",
            "status": item.status,
        },
        indent=2,
    )


@mcp_unified_error_handler("list_incomplete_outdoor_activities", "journal")
async def list_incomplete_outdoor_activities(
    include_dismissed: Annotated[
        bool,
        Field(
            description=(
                "Also return dismissed journals, flagged dismissed=true "
                "(default false: dismissed journals are excluded)"
            ),
        ),
    ] = False,
    user_id: str = mcp_depends(get_current_user_id),
    incomplete_service: IncompleteOutdoorActivityService = mcp_depends(
        get_incomplete_outdoor_activity_service
    ),
) -> str:
    """
    List the user's incomplete outdoor activity journals with their reasons.

    Each entry names the rule(s) it matches: ``no_attributes`` (a subtype's own
    type-specific fields are all empty), ``missing_template`` (an
    abseiling-derived activity with no template reference), and
    ``no_participants`` (a non-bushwalking outdoor activity with no PARTICIPANT
    contacts). Only activities that have already started are listed — a journal
    beginning after the end of today (in the user's timezone) is a plan, not a
    gap. Dismissed journals are excluded unless ``include_dismissed`` is
    set (they then carry ``dismissed=true``, so they can be un-dismissed);
    entries are newest first.
    """
    entries = await incomplete_service.list_incomplete(
        user_id, include_dismissed=include_dismissed
    )

    activities = [
        IncompleteOutdoorActivityMCPEntry(
            journal_id=entry.journal_id,
            title=entry.title,
            event_date_range=EventDateRangeSchema(
                start=entry.event_date_range.start,
                end=entry.event_date_range.end,
            ),
            subtypes=[subtype.value for subtype in entry.subtypes],
            reasons=[reason.value for reason in entry.reasons],
            dismissed=entry.dismissed,
        )
        for entry in entries
    ]

    return MCPResponseBuilder.success_response(
        IncompleteOutdoorActivitiesMCPResponse(
            total_count=len(activities),
            activities=activities,
            summary=(
                f"Found {len(activities)} incomplete outdoor activit"
                f"{'y' if len(activities) == 1 else 'ies'}."
            ),
        )
    )


async def _journal_owned_by_user(
    db_connection: AsyncConnection, user_id: str, journal_id: int
) -> bool:
    """Whether the journal exists and belongs to the user."""
    repos = _create_journal_tool_repositories(db_connection)
    journal = await repos.journal_repo.find_by_id(journal_id)
    return journal is not None and journal.user_id == user_id


@mcp_unified_error_handler("dismiss_incomplete_outdoor_activity", "journal")
async def dismiss_incomplete_outdoor_activity(
    journal_id: Annotated[int, Field(description="Journal id to dismiss")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    dismissal_service: OutdoorActivityDismissalService = mcp_depends(
        get_outdoor_activity_dismissal_service
    ),
) -> str:
    """
    Dismiss a journal from the incomplete outdoor activities review.

    A dismissed journal no longer appears in the incomplete review regardless
    of matched rules. Idempotent: re-dismissing refreshes the recorded
    provenance. Reversible via ``undismiss_incomplete_outdoor_activity``.
    """
    if not await _journal_owned_by_user(db_connection, user_id, journal_id):
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    dismissal = await dismissal_service.dismiss(
        journal_id, user_id, Provenance.MCP, db_connection
    )

    return MCPResponseBuilder.success_response(
        OutdoorActivityDismissalMCPResponse(
            journal_id=journal_id,
            dismissed=True,
            provenance=dismissal.provenance.value,
            summary=f"Dismissed journal {journal_id} from the incomplete review.",
        )
    )


@mcp_unified_error_handler("undismiss_incomplete_outdoor_activity", "journal")
async def undismiss_incomplete_outdoor_activity(
    journal_id: Annotated[int, Field(description="Journal id to un-dismiss")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    dismissal_service: OutdoorActivityDismissalService = mcp_depends(
        get_outdoor_activity_dismissal_service
    ),
) -> str:
    """
    Un-dismiss a journal, restoring it to the incomplete review when flagged.

    Idempotent: un-dismissing a journal that was never dismissed succeeds with
    ``was_dismissed`` false.
    """
    if not await _journal_owned_by_user(db_connection, user_id, journal_id):
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    was_dismissed = await dismissal_service.undismiss(
        journal_id, user_id, db_connection
    )

    return MCPResponseBuilder.success_response(
        OutdoorActivityDismissalMCPResponse(
            journal_id=journal_id,
            dismissed=False,
            was_dismissed=was_dismissed,
            summary=(
                f"Un-dismissed journal {journal_id}."
                if was_dismissed
                else f"Journal {journal_id} was not dismissed; nothing to undo."
            ),
        )
    )


@mcp_unified_error_handler("get_outdoor_dashboard", "journal")
async def get_outdoor_dashboard(
    user_id: str = mcp_depends(get_current_user_id),
    dashboard_service: OutdoorDashboardService = mcp_depends(
        get_outdoor_dashboard_service
    ),
) -> str:
    """
    The outdoor logbook dashboard: all four widget sections in one call.

    A read-only projection over the user's outdoor activity journals
    (general fitness journals such as plain jogging are excluded):

    - ``upcoming_activities`` — outdoor activities and OUTDOOR_PLANNING
      events overlapping the next 30 days, soonest first, capped at 10.
    - ``checked_out_gear`` — gear whose resolved checkout window contains
      now and that Snipe-IT hasn't recorded as returned, longest out first.
    - ``activity_totals_last_30_days`` / ``activity_totals_last_365_days``
      — outdoor activity counts by journal type over rolling windows, plus
      ``total_activities_last_30_days`` / ``total_activities_last_365_days``
      counting *distinct journals*. A journal recording two independent
      subtypes lands in two type buckets, so the totals are not the sums of
      the mappings.
    - ``templates_done`` — the unique templates referenced by the user's
      abseiling activities, grouped by template type, each with how many
      activities reference it (all-time), plus
      ``templates_done_last_30_days`` counting the distinct templates done
      recently.

    Windows are anchored on "today" in the user's configured timezone
    server-side, so the tool takes no arguments.
    """
    upcoming = await dashboard_service.list_upcoming_activities(user_id)
    totals = await dashboard_service.activity_totals(user_id)
    checked_out = await dashboard_service.list_checked_out_gear(user_id)
    templates_done = await dashboard_service.templates_done(user_id)

    upcoming_entries = [
        UpcomingOutdoorActivityMCPEntry(
            journal_id=entry.journal_id,
            title=entry.title,
            event_date_range=EventDateRangeSchema(
                start=entry.event_date_range.start,
                end=entry.event_date_range.end,
            ),
            subtypes=[subtype.value for subtype in entry.subtypes],
            is_planning=entry.is_planning,
        )
        for entry in upcoming
    ]
    gear_entries = [
        CheckedOutGearMCPEntry(
            gear_item_id=item.gear_item_id,
            name=item.name,
            checked_out_since=item.checked_out_since,
            journal_id=item.journal_id,
        )
        for item in checked_out
    ]
    template_entries = {
        template_type: [
            TemplateDoneMCPEntry(
                template_id=template.template_id,
                name=template.name,
                done_count=template.done_count,
            )
            for template in templates
        ]
        for template_type, templates in templates_done.by_type.items()
    }

    return MCPResponseBuilder.success_response(
        OutdoorDashboardMCPResponse(
            upcoming_activities=upcoming_entries,
            checked_out_gear=gear_entries,
            activity_totals_last_30_days=totals.last_30_days,
            activity_totals_last_365_days=totals.last_365_days,
            total_activities_last_30_days=totals.total_last_30_days,
            total_activities_last_365_days=totals.total_last_365_days,
            templates_done=template_entries,
            templates_done_last_30_days=templates_done.recent_unique_count,
            summary=build_dashboard_summary(
                upcoming_activities=upcoming_entries,
                checked_out_gear=gear_entries,
                total_last_30_days=totals.total_last_30_days,
                templates_done=template_entries,
                templates_done_last_30_days=templates_done.recent_unique_count,
            ),
        )
    )


@mcp_unified_error_handler("get_daily_summary", "journal")
async def get_daily_summary(
    summary_date: str,
    daily_summary_service: DailySummaryService = mcp_depends(get_daily_summary_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """Get the AI-generated daily summary for a specific date.

    Args:
        summary_date: The date to get the summary for (YYYY-MM-DD format)
    """
    try:
        parsed_date = date.fromisoformat(summary_date)
    except ValueError as e:
        raise ValueError(
            f"Invalid date format. Expected YYYY-MM-DD, got {summary_date}"
        ) from e

    user_id = await get_current_user_id()

    # get_or_generate is @transactional: it commits any summary it persists
    # before the response is returned (issue #945). Pass the request connection
    # and let the service own the commit boundary — this tool opens no
    # transaction itself (the required pattern; see AGENTS.md "Transactions").
    result = await daily_summary_service.get_or_generate(
        user_id, parsed_date, db_connection
    )

    if result is None:
        return json.dumps({"data": None})

    response = DailySummaryMCPResponse(
        summary_date=parsed_date.isoformat(),
        summary_text=result.get_display_text(),
        journal_count=result.journal_count,
        event_count=result.event_count,
        contact_count=result.contact_count,
        mood_average=result.mood_average,
        status=str(result.status.value)
        if hasattr(result.status, "value")
        else str(result.status),
        summary=f"Daily summary for {parsed_date.isoformat()}: {result.status}. {result.journal_count} journals, {result.event_count} events.",
    )

    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("create_template", "journal")
async def create_template(
    name: Annotated[str, Field(description="Template name")],
    template_type: Annotated[TemplateType, Field(description="Type of template")],
    region: Annotated[str | None, Field(default=None, description="Region")] = None,
    description: Annotated[
        str | None, Field(default=None, description="Description")
    ] = None,
    french_grade: Annotated[
        str | None, Field(default=None, description="French grade")
    ] = None,
    canyon_type: Annotated[
        CanyonType | None, Field(default=None, description="Canyon type")
    ] = None,
    water_gauge_name: Annotated[
        str | None, Field(default=None, description="Water gauge name")
    ] = None,
    is_vertical: Annotated[
        bool | None, Field(default=None, description="Is vertical")
    ] = None,
    is_horizontal: Annotated[
        bool | None, Field(default=None, description="Is horizontal")
    ] = None,
    climbing_type: Annotated[
        ClimbingType | None, Field(default=None, description="Climbing type")
    ] = None,
    grade: Annotated[int | None, Field(default=None, description="Grade")] = None,
    length: Annotated[
        int | None, Field(default=None, description="Length in metres")
    ] = None,
    pitches: Annotated[
        list[TemplatePitchInput] | None,
        Field(default=None, description="Pitches in order; pitch_number is required"),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    activity_template_service: ActivityTemplateService = mcp_depends(
        get_activity_template_service
    ),
) -> str:
    """
    Create a new activity template.
    """
    import uuid

    template_id = str(uuid.uuid4())
    pitch_entities: list[TemplatePitch] = []
    if pitches:
        pitch_entities.extend(
            TemplatePitch(template_id=template_id, **p.model_dump()) for p in pitches
        )

    template = ActivityTemplate(
        id=template_id,
        user_id=user_id,
        name=name,
        template_type=template_type,
        region=region,
        description=description,
        french_grade=french_grade,
        canyon_type=canyon_type,
        water_gauge_name=water_gauge_name,
        is_vertical=is_vertical,
        is_horizontal=is_horizontal,
        climbing_type=climbing_type,
        grade=grade,
        length=length,
        pitches=pitch_entities,
    )

    saved_template = await activity_template_service.create(
        template, transaction=db_connection
    )

    response = ActivityTemplateMCPConverter.to_mcp_response(saved_template)
    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("get_template", "journal")
async def get_template(
    template_id: Annotated[str, Field(description="Template UUID")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get a specific activity template by ID.
    """
    repos = _create_journal_tool_repositories(db_connection)

    try:
        import uuid

        uuid.UUID(template_id)
        template = await repos.activity_template_repo.find_by_id(template_id)
        if not template or template.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response("Template", template_id)

        response = ActivityTemplateMCPConverter.to_mcp_response(template)
        return MCPResponseBuilder.success_response(response)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "template_id", "Invalid UUID"
        )


@mcp_unified_error_handler("get_journal_template", "journal")
async def get_journal_template(
    journal_id: Annotated[int, Field(description="Journal id")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Retrieve the activity template an abseiling-derived journal was created from.

    Returns the referenced template (including its own standard pitches) for any
    abseiling-derived journal (ABSEILING_TRIP / CANYONING / CLIMBING / CAVING),
    reading the consolidated ``abseiling_data.template_id``. The template's
    standard pitches are returned even when the journal's own pitches have been
    edited. ``has_template`` is false when the journal has no template reference
    (or is not abseiling-derived).
    """
    repos = _create_journal_tool_repositories(db_connection)

    journal = await repos.journal_repo.find_by_id(journal_id)
    if not journal or journal.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    abseiling_data = await repos.abseiling_data_repo.find_by_journal_id(journal_id)
    template = None
    if abseiling_data is not None and abseiling_data.template_id is not None:
        candidate = await repos.activity_template_repo.find_by_id(
            str(abseiling_data.template_id)
        )
        if candidate is not None and candidate.user_id == user_id:
            template = candidate

    if template is None:
        return MCPResponseBuilder.success_response(
            JournalTemplateMCPResponse(
                journal_id=journal_id,
                has_template=False,
                template=None,
                summary=f"Journal {journal_id} has no template reference.",
            )
        )

    return MCPResponseBuilder.success_response(
        JournalTemplateMCPResponse(
            journal_id=journal_id,
            has_template=True,
            template=ActivityTemplateMCPConverter.to_mcp_response(template),
            summary=f"Journal {journal_id} based on template: {template.name}.",
        )
    )


@mcp_unified_error_handler("search_templates", "journal")
async def search_templates(
    template_type: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional type of template (e.g. canyoning, climbing) to filter by",
        ),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Search activity templates for the user.
    """
    repos = _create_journal_tool_repositories(db_connection)

    templates = await repos.activity_template_repo.find_by_user(user_id)

    if template_type:
        templates = [t for t in templates if t.template_type == template_type]

    response = ActivityTemplateMCPConverter.to_mcp_list_response(templates)
    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("update_template", "journal")
async def update_template(
    template_id: Annotated[str, Field(description="Template UUID")],
    name: Annotated[
        str | None, Field(default=None, description="Template name")
    ] = None,
    region: Annotated[str | None, Field(default=None, description="Region")] = None,
    description: Annotated[
        str | None, Field(default=None, description="Description")
    ] = None,
    french_grade: Annotated[
        str | None, Field(default=None, description="French grade")
    ] = None,
    canyon_type: Annotated[
        CanyonType | None, Field(default=None, description="Canyon type")
    ] = None,
    water_gauge_name: Annotated[
        str | None, Field(default=None, description="Water gauge name")
    ] = None,
    is_vertical: Annotated[
        bool | None, Field(default=None, description="Is vertical")
    ] = None,
    is_horizontal: Annotated[
        bool | None, Field(default=None, description="Is horizontal")
    ] = None,
    climbing_type: Annotated[
        ClimbingType | None, Field(default=None, description="Climbing type")
    ] = None,
    grade: Annotated[int | None, Field(default=None, description="Grade")] = None,
    length: Annotated[
        int | None, Field(default=None, description="Length in metres")
    ] = None,
    pitches: Annotated[
        list[TemplatePitchInput] | None,
        Field(default=None, description="Pitches in order; pitch_number is required"),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    activity_template_service: ActivityTemplateService = mcp_depends(
        get_activity_template_service
    ),
) -> str:
    """
    Update an existing activity template.
    """
    repos = _create_journal_tool_repositories(db_connection)

    try:
        import uuid

        uuid.UUID(template_id)
        template = await repos.activity_template_repo.find_by_id(template_id)
        if not template or template.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response("Template", template_id)

        if name is not None:
            template.name = name
        if region is not None:
            template.region = region
        if description is not None:
            template.description = description
        if french_grade is not None:
            template.french_grade = french_grade
        if canyon_type is not None:
            template.canyon_type = canyon_type
        if water_gauge_name is not None:
            template.water_gauge_name = water_gauge_name
        if is_vertical is not None:
            template.is_vertical = is_vertical
        if is_horizontal is not None:
            template.is_horizontal = is_horizontal
        if climbing_type is not None:
            template.climbing_type = climbing_type
        if grade is not None:
            template.grade = grade
        if length is not None:
            template.length = length

        if pitches is not None:
            pitch_entities: list[TemplatePitch] = []
            pitch_entities.extend(
                TemplatePitch(template_id=str(template.id), **p.model_dump())
                for p in pitches
            )
            template.pitches = pitch_entities

        try:
            template.__post_init__()
        except Exception as e:  # noqa: BLE001
            return MCPResponseBuilder.validation_error_response("template", str(e))

        saved_template = await activity_template_service.update(
            template, transaction=db_connection
        )

        response = ActivityTemplateMCPConverter.to_mcp_response(saved_template)
        return MCPResponseBuilder.success_response(response)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "template_id", "Invalid UUID"
        )


@mcp_unified_error_handler("create_gear_item", "journal")
async def create_gear_item(
    name: Annotated[str, Field(description="Gear item name")],
    model: Annotated[
        str | None, Field(default=None, description="Model name/number")
    ] = None,
    serial_number: Annotated[
        str | None, Field(default=None, description="Serial number")
    ] = None,
    purchase_date: Annotated[
        str | None, Field(default=None, description="Purchase date (YYYY-MM-DD)")
    ] = None,
    manufacturer: Annotated[
        str | None, Field(default=None, description="Manufacturer name")
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    gear_item_service: GearItemService = mcp_depends(get_gear_item_service),
) -> str:
    """
    Create a new gear item for tracking equipment (ropes, harnesses, helmets, etc.).
    """
    parsed_purchase_date = None
    if purchase_date:
        try:
            parsed_purchase_date = date.fromisoformat(purchase_date)
        except ValueError:
            return MCPResponseBuilder.validation_error_response(
                "purchase_date", "Invalid date format, use YYYY-MM-DD"
            )

    item = GearItem(
        user_id=user_id,
        name=name,
        model=model,
        serial_number=serial_number,
        purchase_date=parsed_purchase_date,
        manufacturer=manufacturer,
    )

    saved_item = await gear_item_service.create(item, transaction=db_connection)

    response = GearItemMCPConverter.to_mcp_response(saved_item)
    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("list_gear_items", "journal")
async def list_gear_items(
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List all gear items for the current user.
    """
    repos = _create_journal_tool_repositories(db_connection)

    items = await repos.gear_item_repo.find_by_user(user_id)

    response = GearItemMCPConverter.to_mcp_list_response(items)
    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("get_gear_item", "journal")
async def get_gear_item(
    gear_item_id: Annotated[str, Field(description="Gear item UUID")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get a specific gear item by ID.
    """
    repos = _create_journal_tool_repositories(db_connection)

    try:
        import uuid as uuid_mod

        uuid_mod.UUID(gear_item_id)
        item = await repos.gear_item_repo.find_by_id(gear_item_id)
        if not item or item.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response(
                "Gear item", gear_item_id
            )

        response = GearItemMCPConverter.to_mcp_response(item)
        return MCPResponseBuilder.success_response(response)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "gear_item_id", "Invalid UUID"
        )


@mcp_unified_error_handler("update_gear_item", "journal")
async def update_gear_item(
    gear_item_id: Annotated[str, Field(description="Gear item UUID")],
    name: Annotated[str | None, Field(default=None, description="Updated name")] = None,
    model: Annotated[
        str | None,
        Field(default=None, description="Updated model (pass empty string to clear)"),
    ] = None,
    serial_number: Annotated[
        str | None,
        Field(
            default=None,
            description="Updated serial number (pass empty string to clear)",
        ),
    ] = None,
    purchase_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Updated purchase date YYYY-MM-DD (pass empty string to clear)",
        ),
    ] = None,
    manufacturer: Annotated[
        str | None,
        Field(
            default=None,
            description="Updated manufacturer (pass empty string to clear)",
        ),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    gear_item_service: GearItemService = mcp_depends(get_gear_item_service),
) -> str:
    """
    Update an existing gear item.
    """
    repos = _create_journal_tool_repositories(db_connection)

    try:
        import uuid as uuid_mod

        uuid_mod.UUID(gear_item_id)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "gear_item_id", "Invalid UUID"
        )

    item = await repos.gear_item_repo.find_by_id(gear_item_id)
    if not item or item.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Gear item", gear_item_id)

    if name is not None:
        item.name = name
    if model is not None:
        item.model = None if model == "" else model
    if serial_number is not None:
        item.serial_number = None if serial_number == "" else serial_number
    if purchase_date is not None:
        if purchase_date == "":
            item.purchase_date = None
        else:
            try:
                item.purchase_date = date.fromisoformat(purchase_date)
            except ValueError:
                return MCPResponseBuilder.validation_error_response(
                    "purchase_date", "Invalid date format, use YYYY-MM-DD"
                )
    if manufacturer is not None:
        item.manufacturer = None if manufacturer == "" else manufacturer

    try:
        item.__post_init__()
    except Exception as e:  # noqa: BLE001
        return MCPResponseBuilder.validation_error_response("gear_item", str(e))

    # The service computes the changed-fields diff against the persisted state
    # and publishes GearItemUpdated with MCP provenance.
    saved_item = await gear_item_service.update(
        item,
        transaction=db_connection,
        changed_by="mcp",
        source=Provenance.MCP,
    )

    response = GearItemMCPConverter.to_mcp_response(saved_item)
    return MCPResponseBuilder.success_response(response)


@mcp_unified_error_handler("list_journal_tags", "tag")
async def list_journal_tags(
    limit: Annotated[
        int, Field(description="Maximum number of tags to return", ge=1, le=100)
    ] = 50,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List all available journal tags for organising journal entries.

    Journal tags are a separate namespace from contact tags — use
    list_contact_tags for those. Tags are hierarchical: a tag with a
    parent_id is a child of that tag, and a null parent_id marks a root tag.

    Args:
        limit: Maximum number of tags to return (1-100, default: 50)

    Returns:
        JSON string containing journal tags ordered by name, each with its
        colour, description, and parent_id for reconstructing the hierarchy.
    """
    repos = _create_journal_tool_repositories(db_connection)

    all_tags = await repos.tag_repo.get_all()
    tags = all_tags[:limit]

    tag_data = [
        JournalTagInfo(
            id=str(tag.id),
            name=tag.name,
            color=tag.color,
            description=tag.description,
            parent_id=str(tag.parent_id) if tag.parent_id else None,
            created_at=tag.created_at.isoformat() if tag.created_at else None,
        )
        for tag in tags
    ]

    response_data = JournalTagListMCPResponse(
        tags=tag_data,
        total_count=len(tag_data),
        summary=f"Found {len(tag_data)} journal tag(s). "
        "Journal tags categorise journal entries by theme, project, or activity.",
        suggestions=[
            "Use tags to group journals by theme (training, travel, reflection)",
            "Nest tags under a parent to build a hierarchy (activities/climbing)",
            "Assign tags when creating or updating a journal entry",
        ],
    )

    return MCPResponseBuilder.success_response(response_data)


@mcp_unified_error_handler("update_journal_tag", "tag")
async def update_journal_tag(
    tag_id: Annotated[str, Field(description="UUID of the journal tag to update")],
    name: Annotated[
        str | None, Field(description="New tag name (must be unique)")
    ] = None,
    color: Annotated[
        str | None, Field(description="New hex colour code, e.g. #FF0000")
    ] = None,
    description: Annotated[
        str | None, Field(description="New description of what the tag is for")
    ] = None,
    parent_id: Annotated[
        str | None, Field(description="UUID of the new parent tag")
    ] = None,
    move_to_root: Annotated[
        bool,
        Field(description="Clear the tag's parent, making it a root tag"),
    ] = False,
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Update an existing journal tag's name, colour, description, or parent.

    Journal tags are a separate namespace from contact tags — use
    update_contact_tag for those, and list_journal_tags to find tag UUIDs.

    Only the arguments you supply are changed; omitted arguments are left as
    they are. To move a tag to the root of the hierarchy, pass
    move_to_root=true rather than a null parent_id, since an omitted parent_id
    means "leave the parent alone".

    Args:
        tag_id: UUID of the tag to update
        name: New name; must not collide with another tag (case-insensitive)
        color: New hex colour code (7 characters, e.g. #FF0000)
        description: New description of what the tag is for
        parent_id: UUID of the new parent tag
        move_to_root: Clear the parent instead of setting one

    Returns:
        JSON string containing the updated tag.
    """
    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", f"Invalid tag UUID: {tag_id}") from e

    parent_uuid = None
    if parent_id is not None:
        try:
            parent_uuid = UUID(parent_id)
        except ValueError as e:
            raise JournalValidationError(
                "parent_id", f"Invalid parent tag UUID: {parent_id}"
            ) from e

    # The service owns the unit of work; MCP tools never open transactions.
    updated = await tag_service.update_tag(
        tag_id=tag_uuid,
        transaction=db_connection,
        name=name,
        color=color,
        description=description,
        parent_id=parent_uuid,
        set_parent_null=move_to_root,
        source=Provenance.MCP,
        changed_by="mcp",
    )

    response_data = JournalTagInfo(
        id=str(updated.id),
        name=updated.name,
        color=updated.color,
        description=updated.description,
        parent_id=str(updated.parent_id) if updated.parent_id else None,
        created_at=updated.created_at.isoformat() if updated.created_at else None,
    )

    return MCPResponseBuilder.success_response(response_data)


@mcp_unified_error_handler("delete_journal_tag", "tag")
async def delete_journal_tag(
    tag_id: Annotated[str, Field(description="UUID of the journal tag to delete")],
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Delete a journal tag, removing it from every journal it is assigned to.

    Journal tags are a separate namespace from contact tags — use
    delete_contact_tag for those, and list_journal_tags to find tag UUIDs.

    This is not blocked when the tag is in use: journals keep their content and
    simply lose this tag. Any child tags of the deleted tag are re-parented to
    the root of the hierarchy rather than being deleted.

    Args:
        tag_id: UUID of the tag to delete

    Returns:
        JSON string confirming the deletion.
    """
    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", f"Invalid tag UUID: {tag_id}") from e

    # The service owns the unit of work; MCP tools never open transactions.
    await tag_service.delete_tag(
        tag_id=tag_uuid,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )

    class DeleteJournalTagResponse(BaseModel):
        status: str
        summary: str

    return MCPResponseBuilder.success_response(
        DeleteJournalTagResponse(
            status="success",
            summary=f"Deleted journal tag {tag_id} and removed it from all journals",
        )
    )


@mcp_unified_error_handler("merge_journal_tag", "tag")
async def merge_journal_tag(
    source_tag_id: Annotated[
        str, Field(description="UUID of the journal tag to merge away and delete")
    ],
    target_tag_id: Annotated[
        str, Field(description="UUID of the journal tag to merge into (the survivor)")
    ],
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Merge one journal tag into another, consolidating duplicates.

    Journal tags are a separate namespace from contact tags — use
    merge_contact_tags for those, and list_journal_tags to find tag UUIDs.

    Every journal tagged with the source tag ends up tagged with the target
    instead; a journal already carrying both keeps a single tag. Child tags of
    the source are adopted by the target rather than moved to the root. The
    source tag is then deleted.

    A tag cannot be merged into itself, nor into one of its own descendants —
    the surviving hierarchy would run through a tag that no longer exists.

    Args:
        source_tag_id: UUID of the tag to merge away and delete
        target_tag_id: UUID of the tag that survives the merge

    Returns:
        JSON string confirming the merge.
    """
    try:
        source_uuid = UUID(source_tag_id)
    except ValueError as e:
        raise JournalValidationError(
            "source_tag_id", f"Invalid tag UUID: {source_tag_id}"
        ) from e

    try:
        target_uuid = UUID(target_tag_id)
    except ValueError as e:
        raise JournalValidationError(
            "target_tag_id", f"Invalid tag UUID: {target_tag_id}"
        ) from e

    # The service owns the unit of work; MCP tools never open transactions.
    await tag_service.merge_tag(
        source_id=source_uuid,
        target_id=target_uuid,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )

    class MergeJournalTagResponse(BaseModel):
        status: str
        summary: str

    return MCPResponseBuilder.success_response(
        MergeJournalTagResponse(
            status="success",
            summary=(
                f"Merged journal tag {source_tag_id} into {target_tag_id}; "
                "the source tag was deleted"
            ),
        )
    )


def register_journal_tools(mcp: FastMCP[None]) -> None:
    """
    Register journal-related MCP tools with the FastMCP server.
    """
    mcp.add_tool(list_journal_types)
    mcp.add_tool(create_journal_entry)
    mcp.add_tool(update_journal_entry)
    mcp.add_tool(get_journal)
    mcp.add_tool(get_journal_by_external_id)
    mcp.add_tool(get_journal_hierarchy)
    mcp.add_tool(search_journals)
    mcp.add_tool(search_activities)
    mcp.add_tool(get_activity_stats)
    mcp.add_tool(analyze_activity_trends)
    mcp.add_tool(get_route_history)
    mcp.add_tool(get_journal_history)
    mcp.add_tool(delete_journal)
    mcp.add_tool(get_contact_journals)
    mcp.add_tool(link_journal_to_contact)
    mcp.add_tool(list_calendars)
    mcp.add_tool(create_calendar)
    mcp.add_tool(update_calendar)
    mcp.add_tool(delete_calendar)
    mcp.add_tool(merge_journals)
    mcp.add_tool(get_merge_candidates)
    mcp.add_tool(browse_journals_by_date_window)
    mcp.add_tool(list_review_items)
    mcp.add_tool(dismiss_review_item)
    mcp.add_tool(list_incomplete_outdoor_activities)
    mcp.add_tool(dismiss_incomplete_outdoor_activity)
    mcp.add_tool(undismiss_incomplete_outdoor_activity)
    mcp.add_tool(get_outdoor_dashboard)
    mcp.add_tool(get_daily_summary)
    mcp.add_tool(create_template)
    mcp.add_tool(get_template)
    mcp.add_tool(get_journal_template)
    mcp.add_tool(search_templates)
    mcp.add_tool(update_template)
    mcp.add_tool(create_gear_item)
    mcp.add_tool(list_gear_items)
    mcp.add_tool(get_gear_item)
    mcp.add_tool(update_gear_item)
    mcp.add_tool(list_journal_tags)
    mcp.add_tool(update_journal_tag)
    mcp.add_tool(delete_journal_tag)
    mcp.add_tool(merge_journal_tag)

"""
Journal domain MCP tools.

Provides AI access to journal management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
"""

import dataclasses
import json
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from typing import Annotated, Any
from uuid import UUID

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    ActivityTemplate,
    Calendar,
    CanyonType,
    ClimbingType,
    EventDateRange,
    GearItem,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    JournalNotFoundError,
    JournalType,
    JournalValidationError,
    TemplatePitch,
    TemplateType,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
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
from app.core.integrations.link_sources import (
    journal_source_names,
    resolve_journal_source,
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
from app.core.journal.models.activity_stats import (
    ActivityFilters,
    ActivityJournalRow,
    ActivityMetric,
    TrendInterval,
    parse_activity_type,
)
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.repositories import (
    ActivityStatsRepository,
    JournalTagRepository,
)
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
from app.core.journal.services.journal_search_service import (
    SEARCH_SUGGESTIONS,
    SEARCH_UNAVAILABLE_HINT,
    WINDOW_SUGGESTIONS,
    JournalSearchHit,
    explain_empty_result,
    search_journals_text,
)
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_tag_hierarchy_service import (
    JournalTagHierarchyService,
)
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.journal.services.journal_type_data_reader import (
    read_journal_types_and_data,
)
from app.core.journal.services.journal_type_metadata import describe_journal_types
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.outdoor_activity_dismissal_service import (
    OutdoorActivityDismissalService,
)
from app.core.journal.services.outdoor_dashboard_service import (
    OutdoorDashboardService,
)
from app.core.journal.services.review_item_service import ReviewItemService
from app.core.journal.services.template_application import (
    apply_template_to_type_data,
)
from app.core.search.exceptions import SearchServiceUnavailableError
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
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
    CheckedOutGearMCPEntry,
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
    UpcomingOutdoorActivityMCPEntry,
    build_dashboard_summary,
    validate_type_data,
)
from app.mcp.shared.annotations import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
    READ_ONLY_EXTERNAL,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_activity_stats_repository,
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


def _parse_integration_source_filter(value: str | None) -> str | None:
    """Normalise an integration source filter (None passes through)."""
    return None if value is None else resolve_journal_source(value)


async def _resolve_tag_filters(
    tags: str | None, tag_repo: JournalTagRepository
) -> list[str] | None:
    """Resolve a comma-separated ``tags`` filter to journal tag ids.

    Each entry is either a tag UUID or a tag name, because a name is what an AI
    client actually has to hand; names match case-insensitively, as the
    repository does. A name that resolves to nothing raises rather than being
    dropped, which would silently widen the search instead of narrowing it.

    Every id is then expanded to its whole subtree, so filtering by a parent tag
    returns journals tagged with a descendant — the behaviour the REST journal
    list gets from ``JournalService._expand_tag_ids_with_descendants``.
    """
    if not tags:
        return None

    resolved: dict[str, None] = {}
    for raw_tag in tags.split(","):
        value = raw_tag.strip()
        if not value:
            continue
        try:
            resolved[str(UUID(value))] = None
            continue
        except ValueError:
            pass
        tag = await tag_repo.find_by_name(value)
        if tag is None or tag.id is None:
            raise ValueError(
                f"Unknown journal tag '{value}'. Pass a tag name or id from "
                "list_journal_tags."
            )
        resolved[str(tag.id)] = None

    if not resolved:
        return None

    descendants = await JournalTagHierarchyService(tag_repo).get_all_descendants_bulk(
        [UUID(tag_id) for tag_id in resolved]
    )
    for descendant in descendants:
        if descendant.id is not None:
            resolved[str(descendant.id)] = None

    return list(resolved)


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


def _activity_filters(
    user_id: str,
    *,
    activity_type: str | None,
    start_date: str | None,
    end_date: str | None,
    search_query: str | None = None,
) -> ActivityFilters:
    """Validate the activity tools' filter arguments into ``ActivityFilters``."""
    return ActivityFilters(
        user_id=user_id,
        activity_type=parse_activity_type(activity_type),
        start_date=_parse_optional_datetime_filter(start_date, "start_date"),
        end_date=_parse_optional_datetime_filter(end_date, "end_date", is_end=True),
        search_query=search_query,
    )


async def _fetch_types_for_journal(
    journal_id: int, repos: _JournalToolRepositories
) -> tuple[list[str], dict[str, Any]]:
    """Fetch the concrete types and type-specific data for a journal."""
    return await read_journal_types_and_data(journal_id, repos)


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


async def _build_search_results(
    journals: list[Journal],
    repos: _JournalToolRepositories,
    *,
    activity_rows_by_id: dict[int, ActivityJournalRow] | None = None,
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
    types, type_data = await read_journal_types_and_data(journal_id, repos)

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


@tool(annotations=READ_ONLY)
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
    return json.dumps(describe_journal_types(), indent=2)


async def _load_own_template(
    template_id: str,
    user_id: str,
    activity_template_repo: SqlActivityTemplateRepository,
) -> ActivityTemplate:
    """Load a template the caller owns, refusing anything they cannot use.

    Another user's template is reported as missing rather than forbidden: the
    caller has no way to tell it exists, and no way to act on the difference.
    """
    try:
        UUID(template_id)
    except ValueError as e:
        raise JournalValidationError(
            "template_id", f"Template ID {template_id!r} must be a valid UUID"
        ) from e

    template = await activity_template_repo.find_by_id(template_id)
    if template is None or template.user_id != user_id:
        raise JournalValidationError(
            "template_id",
            f"Template {template_id} not found. Call search_templates to list "
            "your templates.",
        )
    return template


@tool(annotations=ADDITIVE_WRITE)
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

    For a trip down a known canyon, cave or climb, pass that activity template's
    id as ``template_id`` (find one with search_templates) instead of copying its
    pitches yourself: the journal records the template reference and is filled in
    with the template's standard pitches, the abseil counts derived from them,
    and the template's own type fields. Anything you also pass in ``type_data``
    wins over the template — your own ``pitches`` replace the template's, and the
    abseil counts are derived from whichever pitches are stored unless you set
    the counts yourself.

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

    # Check every value against its type's write model before anything is
    # written, so a bad one is refused with the field named rather than
    # reaching the column (see validate_type_data).
    validated_type_data = validate_type_data(request.type_data)

    if request.contact_relationships:
        _validate_contact_relationships(request.contact_relationships)

    # Repositories are needed to resolve the template below, and to read back
    # enrichment data for the response.
    repos = _create_journal_tool_repositories(db_connection)

    # A template contributes its standard pitches and its own type fields — the
    # same thing selecting one in the UI does (the abseil counts then follow from
    # the pitches, in AbseilingService). Resolved here, before any write, so an
    # unusable template_id creates no journal.
    type_data = validated_type_data
    # ``is not None`` rather than truthiness: an explicit empty string is a
    # malformed id, and must be refused rather than quietly creating an
    # untemplated journal.
    if request.template_id is not None:
        template = await _load_own_template(
            request.template_id, user_id, repos.activity_template_repo
        )
        type_data = apply_template_to_type_data(template, request.types, type_data)

    # --- All inputs validated, proceed with DB writes ---

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
        type_data,
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


@tool(annotations=IDEMPOTENT_WRITE)
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

    To edit safely, pass the ``version`` from get_journal as
    ``expected_version``: the update is then refused, with nothing written, if
    the journal changed in between. The refusal carries ``current_version`` to
    retry with after re-reading.

    Returns:
        JSON string containing AI-friendly updated journal information

    Raises:
        JournalNotFoundError: If the journal with the given ID does not exist
        JournalValidationError: If validation fails
        PreconditionFailedError: If expected_version names a superseded version
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

    # Check every value against its type's write model before anything is
    # written. The composite update reaches the type-data write down two
    # different branches and only one of them ran the domain's checks, so an
    # over-long value came back as a bare "Internal error" when ``types`` was
    # sent alongside it (see validate_type_data).
    validated_type_data = validate_type_data(request.type_data, partial=True)

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
        type_data=validated_type_data,
        relationships=relationships,
        tags=request.tags,
        changed_by="mcp",
        source=Provenance.MCP,
        # Checked inside the service's unit of work, under the row lock, so a
        # stale version refuses before any part of the composite is written.
        expected_etags=(
            [request.expected_version] if request.expected_version is not None else None
        ),
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
    types, type_data = await read_journal_types_and_data(journal_id, repos)

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

    # Fetch every calendar this event lives in. One event held by two
    # calendars — where one invited the other — is a single journal linked
    # to each, so reporting only the one it is displayed in would hide the
    # rest.
    linked_calendars = await SqlCalendarRepository(
        db_connection
    ).find_linked_to_journal(journal_id)

    # Convert to AI-friendly response
    response = JournalConverter.to_response(
        journal=journal,
        types=types,
        type_data=type_data,
        linked_calendars=linked_calendars,
        contacts=contacts,
        tags=journal_tags,
        parent=parent,
        children=children,
        external_links=external_links,
        series=series,
    )

    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
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


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_journal_by_external_id", "journal")
async def get_journal_by_external_id(
    source: Annotated[
        str,
        Field(
            description="Integration source the id belongs to. One of: "
            + ", ".join(journal_source_names())
            + ". Any other value is rejected."
        ),
    ],
    external_id: Annotated[
        str,
        Field(
            description="The external system's identifier exactly as a journal's "
            "external_links report it: a Strava activity id ('16152597201'), a "
            "Google Calendar event id, an Immich album UUID, a Snipe-IT "
            "maintenance id, or (source 'snipeit') the Snipe-IT asset id of the "
            "gear checked out on the journal."
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
    source_filter = resolve_journal_source(source)
    normalized_id = external_id.strip()
    if not normalized_id:
        raise ValueError("external_id must not be empty")

    user_id = await get_current_user_id()
    journal_id = await SqlJournalRepository(db_connection).find_id_by_external_id(
        user_id, source_filter, normalized_id
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


@tool(annotations=READ_ONLY)
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


def _search_hit_to_result(hit: JournalSearchHit) -> JournalSearchResult:
    """Render a search hit as the MCP search result schema."""
    return JournalSearchResult(
        id=hit.id,
        title=hit.title,
        content_excerpt=hit.content_excerpt,
        event_date_range=EventDateRangeSchema(start=hit.start, end=hit.end),
        types=hit.types,
        tags=[],
        highlighted=hit.highlighted,
        summary=f"Journal: {hit.title}",
    )


def _meili_search_journals(
    search_service: SearchService,
    *,
    query: str,
    user_id: str,
    limit: int,
    offset: int = 0,
    type_filters: list[str] | None = None,
    journal_ids: set[int] | None = None,
) -> tuple[list[JournalSearchResult], int, int]:
    """Full-text search returning MCP result schemas."""
    hits, total, ms = search_journals_text(
        search_service,
        query=query,
        user_id=user_id,
        limit=limit,
        offset=offset,
        type_filters=type_filters,
        journal_ids=journal_ids,
    )
    return [_search_hit_to_result(hit) for hit in hits], total, ms


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
    """MCP schema for :func:`explain_empty_result`."""
    explained = await explain_empty_result(
        repos.journal_repo,
        user_id,
        search_backend=search_backend,
        filters=filters,
        source_filter=source_filter,
        journals_linked_to_source=journals_linked_to_source,
        suggestions=suggestions,
    )
    return SearchDiagnostics(**dataclasses.asdict(explained))


@tool(annotations=READ_ONLY)
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
    start_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: ISO date or datetime lower bound. Journals "
            "whose event range overlaps the window are returned.",
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: ISO date or datetime upper bound. A bare "
            "date includes the whole day.",
        ),
    ] = None,
    tags: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Comma-separated journal tag names or tag ids "
            "(see list_journal_tags). A journal matching any of them — or any "
            "of their descendant tags — is returned.",
        ),
    ] = None,
    contact_id: Annotated[
        int | None,
        Field(
            default=None, description="Optional: Only journals linked to this contact"
        ),
    ] = None,
    calendar_id: Annotated[
        str | None,
        Field(default=None, description="Optional: Only journals on this calendar"),
    ] = None,
    parent_id: Annotated[
        int | None,
        Field(
            default=None,
            description="Optional: Only the direct children of this journal "
            "(e.g. the days of a trip)",
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=20,
            description="Maximum number of results to return (default: 20)",
        ),
    ] = 20,
    offset: Annotated[
        int,
        Field(default=0, ge=0, description="Number of results to skip (default: 0)"),
    ] = 0,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    search_service: SearchService = mcp_depends(get_search_service),
) -> str:
    """
    Search journals with filtering options.

    With a ``query``, the search runs through MeiliSearch exactly like the web
    UI (word matching, typo tolerance, relevance ranking) — not a literal
    substring match — so "Zion canyoning" finds a canyoning journal whose text
    mentions Zion. Without a query, journals are listed from the database
    (newest first). Every other argument is a filter, and they combine: they
    narrow the listing and the full-text query alike, so
    ``query="canyon", start_date="2025-10-01", tags="trips"`` searches the text
    of October's trip journals only.
    If MeiliSearch is unreachable the tool returns an explicit
    "Search unavailable" error, never a silent empty result.

    Args:
        query: Optional search query for full-text search
        types: Optional comma-separated list of journal types
        integration_source: Optional integration source filter (strava, google_calendar)
        start_date: Optional ISO date/datetime lower bound for the event range
        end_date: Optional ISO date/datetime upper bound for the event range
        tags: Optional comma-separated tag names or tag ids
        contact_id: Optional contact the journal must be linked to
        calendar_id: Optional calendar the journal must belong to
        parent_id: Optional parent journal whose direct children to return
        limit: Maximum number of results to return
        offset: Number of results to skip, for paging

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
    start_filter = _parse_optional_datetime_filter(start_date, "start_date")
    end_filter = _parse_optional_datetime_filter(end_date, "end_date", is_end=True)
    tag_filters = await _resolve_tag_filters(tags, repos.tag_repo)

    # The filters the database resolves, in the spelling get_all/count_all use.
    relational_filters: dict[str, Any] = {
        "start_date": start_filter.isoformat() if start_filter else None,
        "end_date": end_filter.isoformat() if end_filter else None,
        "contact_id": str(contact_id) if contact_id is not None else None,
        "tag_ids": tag_filters,
        "calendar_id": calendar_id,
        "parent_id": parent_id,
    }
    # ...and the same filters as the agent spelled them, for the diagnostics.
    reported_filters: dict[str, Any] = {
        "types": types,
        "integration_source": source_filter,
        "start_date": start_date,
        "end_date": end_date,
        "tags": tags,
        "contact_id": contact_id,
        "calendar_id": calendar_id,
        "parent_id": parent_id,
    }

    # When integration_source filter is active, fetch journal IDs matching
    # the source first, then intersect with other filters.
    source_journal_ids: set[int] | None = None
    if source_filter is not None:
        source_journal_ids = await repos.journal_repo.find_ids_by_integration_source(
            user_id, source_filter
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
                    filters=reported_filters,
                    journals_linked_to_source=0,
                    suggestions=[
                        f"No journal is linked to {source_filter}. Check "
                        "list_integrations, or trigger_sync if the integration "
                        "is connected but has not imported yet.",
                        *SEARCH_SUGGESTIONS[:2],
                    ],
                ),
            )
            return MCPResponseBuilder.success_response(response)

    summary_suffix = f" linked to {source_filter}" if source_filter else ""

    if query and query.strip():
        # MeiliSearch indexes the event dates as ISO strings and its range
        # operators are numeric-only, so the relational filters are resolved to
        # candidate ids here and intersected through Meili's `id IN [...]`,
        # the same way the integration_source filter already is.
        candidate_ids = source_journal_ids
        if any(value is not None for value in relational_filters.values()):
            candidate_ids = await repos.journal_repo.find_ids_by_filters(
                user_id=user_id,
                journal_ids=(
                    sorted(source_journal_ids)
                    if source_journal_ids is not None
                    else None
                ),
                **relational_filters,
            )
        try:
            results, total_hits, processing_time_ms = _meili_search_journals(
                search_service,
                query=query.strip(),
                user_id=user_id,
                limit=limit,
                offset=offset,
                type_filters=type_filters,
                journal_ids=candidate_ids,
            )
        except SearchServiceUnavailableError as exc:
            return MCPResponseBuilder.error_response(
                error_type="Search unavailable",
                message=exc.message,
                context={"query": query, "hint": SEARCH_UNAVAILABLE_HINT},
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
                filters={"query": query, **reported_filters},
                source_filter=source_filter,
                journals_linked_to_source=(
                    len(source_journal_ids) if source_journal_ids else None
                ),
                suggestions=SEARCH_SUGGESTIONS,
            )
            if total_hits == 0
            else None,
        )
        return MCPResponseBuilder.success_response(response)

    journal_ids = list(source_journal_ids) if source_journal_ids is not None else None
    if len(type_filters) <= 1:
        journal_type = type_filters[0] if type_filters else None
        total_hits = await repos.journal_repo.count_all(
            user_id=user_id,
            journal_type=journal_type,
            journal_ids=journal_ids,
            **relational_filters,
        )
        journals = await repos.journal_repo.get_all(
            user_id=user_id,
            limit=limit,
            offset=offset,
            journal_type=journal_type,
            journal_ids=journal_ids,
            **relational_filters,
        )
        results = await _build_search_results(journals, repos)
    else:
        # Several types cannot be expressed as one SQL filter, so every
        # candidate the other filters allow is fetched and typed in Python.
        candidate_count = await repos.journal_repo.count_all(
            user_id=user_id, journal_ids=journal_ids, **relational_filters
        )
        journals = (
            await repos.journal_repo.get_all(
                user_id=user_id,
                limit=candidate_count,
                offset=0,
                journal_ids=journal_ids,
                **relational_filters,
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
        results = results[offset : offset + limit]

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
            filters=reported_filters,
            source_filter=source_filter,
            journals_linked_to_source=(
                len(source_journal_ids) if source_journal_ids else None
            ),
            suggestions=SEARCH_SUGGESTIONS[1:],
        )
        if total_hits == 0
        else None,
    )

    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
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
    activity_stats_repo: ActivityStatsRepository = mcp_depends(
        get_activity_stats_repository
    ),
) -> str:
    """Search activity journals with effective activity-type filtering."""
    user_id = await get_current_user_id()
    repos = _create_journal_tool_repositories(db_connection)
    filters = _activity_filters(
        user_id,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
        search_query=query,
    )
    total_hits = await activity_stats_repo.count_activity_journals(filters)

    activity_rows: list[ActivityJournalRow] = []
    if total_hits > 0:
        activity_rows = await activity_stats_repo.list_activity_journals(
            filters, limit=limit, offset=0
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


@tool(annotations=READ_ONLY)
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
    activity_stats_repo: ActivityStatsRepository = mcp_depends(
        get_activity_stats_repository
    ),
) -> str:
    """Aggregate activity totals, breakdowns, and personal records."""
    user_id = await get_current_user_id()
    filters = _activity_filters(
        user_id,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )
    totals = await activity_stats_repo.get_totals(filters)
    activity_type_rows = await activity_stats_repo.list_type_totals(filters)

    overall_totals = ActivityTotals(
        distance=totals.total_distance,
        duration=totals.total_duration,
        elevation_gain=totals.total_elevation_gain,
        calories=totals.total_calories,
    )

    activity_type_stats = [
        ActivityTypeStats(
            activity_type=row.activity_type,
            count=row.count,
            total_distance=row.total_distance,
            total_duration=row.total_duration,
            total_elevation_gain=row.total_elevation_gain,
            total_calories=row.total_calories,
        )
        for row in activity_type_rows
    ]

    async def build_personal_record(
        metric: ActivityMetric,
    ) -> ActivityPersonalRecord | None:
        record_row = await activity_stats_repo.find_personal_record(filters, metric)
        if record_row is None:
            return None

        return ActivityPersonalRecord(
            activity_type=record_row.activity_type,
            journal_id=record_row.journal_id,
            journal_title=record_row.journal_title,
            value=record_row.value,
        )

    personal_records = {
        "longest_distance": await build_personal_record(ActivityMetric.DISTANCE),
        "longest_duration": await build_personal_record(ActivityMetric.DURATION),
        "highest_elevation_gain": await build_personal_record(
            ActivityMetric.ELEVATION_GAIN
        ),
        "most_calories": await build_personal_record(ActivityMetric.CALORIES),
    }
    total_activities = totals.total_activities

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


@tool(annotations=READ_ONLY)
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
    activity_stats_repo: ActivityStatsRepository = mcp_depends(
        get_activity_stats_repository
    ),
) -> str:
    """Analyse activity trends by day, week, month, or year buckets."""
    normalized_interval = interval.strip().lower()
    try:
        trend_interval = TrendInterval(normalized_interval)
    except ValueError as exc:
        raise ValueError("interval must be one of: day, week, month, year") from exc

    user_id = await get_current_user_id()
    filters = _activity_filters(
        user_id,
        activity_type=activity_type,
        start_date=start_date,
        end_date=end_date,
    )
    trend_rows = await activity_stats_repo.list_trend_buckets(filters, trend_interval)

    periods = [
        ActivityTrendPeriod(
            period_start=row.period_start.isoformat(),
            activity_count=row.activity_count,
            total_distance=row.total_distance,
            total_duration=row.total_duration,
            total_elevation_gain=row.total_elevation_gain,
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


@tool(annotations=READ_ONLY)
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

    history_rows = await repos.route_repo.find_usage_history(user_id, route_uuid)
    entries = [
        RouteHistoryEntry(
            journal_id=row.journal_id,
            journal_title=row.journal_title,
            activity_type=row.activity_type,
            event_date_range=EventDateRangeSchema(
                start=row.event_date_range.start,
                end=row.event_date_range.end,
            ),
            distance=row.distance,
            duration=row.duration,
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


@tool(annotations=READ_ONLY)
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


@tool(annotations=DESTRUCTIVE_WRITE)
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


@tool(annotations=READ_ONLY)
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


@tool(annotations=IDEMPOTENT_WRITE)
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


@tool(annotations=READ_ONLY)
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


@tool(annotations=ADDITIVE_WRITE)
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


@tool(annotations=IDEMPOTENT_WRITE)
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


@tool(annotations=DESTRUCTIVE_WRITE)
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


@tool(annotations=DESTRUCTIVE_WRITE)
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

    # The tasks domain's merge service is built here rather than added to the
    # shared journal tool repositories: merge is the only journal tool that
    # touches task links. It owns the anchor repository and publishes an event
    # per task the merge moves, so the journal domain never constructs one.
    merge_service = JournalMergeService(
        repos.journal_repo,
        event_publisher,
        TaskJournalMergeService(
            task_anchor_repo=SqlTaskAnchorRepository(db_connection),
            event_publisher=event_publisher,
        ),
    )

    merged_journal = await merge_service.merge_journals(
        target_id=target_journal_id,
        source_id=merge_request.source_journal_id,
        transaction=db_connection,
        overrides=merge_request.overrides,
        fitness_merge_mode=merge_request.fitness_merge_mode,
        # An assistant merged these journals, so the tasks it moved say so.
        source=Provenance.MCP,
        changed_by="mcp",
    )

    # Fetch enriched target
    types, type_data = await read_journal_types_and_data(target_journal_id, repos)

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


@tool(annotations=READ_ONLY)
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
        c_types, _ = await read_journal_types_and_data(candidate_id, repos)
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


@tool(annotations=READ_ONLY)
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
                context={"search": search, "hint": SEARCH_UNAVAILABLE_HINT},
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
                [*WINDOW_SUGGESTIONS, SEARCH_SUGGESTIONS[0]]
                if search
                else WINDOW_SUGGESTIONS
            ),
        )
        if total_count == 0
        else None,
    )

    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
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
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List pending journal review items for the user.

    Retrieves a list of journals that might need merging, deduplication,
    or review. Used typically to show pending tasks in a queue/sidebar.

    Returns AI-friendly response containing reason, confidence score, and
    candidate journal ids for review.
    """
    user_id = await get_current_user_id()

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


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("dismiss_review_item", "journal")
async def dismiss_review_item(
    item_id: int,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    review_item_service: ReviewItemService = mcp_depends(get_review_item_service),
) -> str:
    """
    Dismiss a journal review item.

    Use this tool to dismiss a pending merge candidate review item that the user
    has determined is not a match or should not be merged.
    """
    user_id = await get_current_user_id()

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


@tool(annotations=READ_ONLY)
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


@tool(annotations=IDEMPOTENT_WRITE)
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


@tool(annotations=IDEMPOTENT_WRITE)
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


@tool(annotations=READ_ONLY)
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


# Read-only to the caller, though it may generate and persist. Asking for a
# summary reads a summary; the caching write behind it is not part of the
# world an agent calling this tool reasons about.
@tool(annotations=READ_ONLY_EXTERNAL)
@mcp_unified_error_handler("get_daily_summary", "journal")
async def get_daily_summary(
    summary_date: str,
    daily_summary_service: DailySummaryService = mcp_depends(get_daily_summary_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """Get the AI-generated daily summary for a specific date.

    Today (in the user's configured timezone) is always eligible for a summary,
    however few journals it has, and today's summary is regenerated on read if
    it was not generated today in that timezone, so it always reflects today.
    Any other date needs at least two journals and otherwise comes back with
    status "disabled"; its summary is served from cache however old it is.

    Today's summary is also grounded in the day's agenda — its event journals
    with their times, locations and participants — while any other day's
    describes only that day's journals.

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


@tool(annotations=ADDITIVE_WRITE)
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
            TemplatePitch(template_id=template_id, **p.model_dump(mode="json"))
            for p in pitches
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


@tool(annotations=READ_ONLY)
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


@tool(annotations=READ_ONLY)
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


@tool(annotations=READ_ONLY)
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


@tool(annotations=IDEMPOTENT_WRITE)
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
                TemplatePitch(template_id=str(template.id), **p.model_dump(mode="json"))
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


@tool(annotations=ADDITIVE_WRITE)
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


@tool(annotations=READ_ONLY)
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


@tool(annotations=READ_ONLY)
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


@tool(annotations=IDEMPOTENT_WRITE)
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


@tool(annotations=READ_ONLY)
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


@tool(annotations=IDEMPOTENT_WRITE)
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


@tool(annotations=DESTRUCTIVE_WRITE)
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


@tool(annotations=DESTRUCTIVE_WRITE)
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

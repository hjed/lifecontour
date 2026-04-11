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

import structlog
from core_shared.models.journals import (
    AbseilingData,
    BushwalkingData,
    Calendar,
    CalendarInfo,
    CanyoningData,
    ClimbingData,
    CrossCountrySkiingData,
    EventDateRange,
    FitnessData,
    JoggingData,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    JournalNotFoundError,
    JournalType,
    KayakingData,
    MoodData,
    OutdoorActivityData,
    PhotoAlbumData,
    PlanData,
    TravelData,
)
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
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
from app.core.journal.adapters.sql.climbing_data_repository import (
    SqlClimbingDataRepository,
)
from app.core.journal.adapters.sql.cross_country_skiing_data_repository import (
    SqlCrossCountrySkiingDataRepository,
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
from app.core.journal.adapters.sql.review_item_repository import SqlReviewItemRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.adapters.sql.travel_data_repository import SqlTravelDataRepository
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.services.hierarchy_service import HierarchyNode, HierarchyService
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.mcp.domains.journals.converters import JournalConverter
from app.mcp.domains.journals.schemas import (
    ActivityPersonalRecord,
    ActivityStatsResponse,
    ActivityTotals,
    ActivityTrendPeriod,
    ActivityTrendsResponse,
    ActivityTypeStats,
    EventDateRangeSchema,
    JournalCreateRequest,
    JournalDateWindowResponse,
    JournalHierarchyNode,
    JournalHierarchyResponse,
    JournalSearchResponse,
    JournalSearchResult,
    JournalUpdateRequest,
    MergeCandidateResult,
    MergeCandidatesResponse,
    MergeJournalMCPRequest,
    RouteHistoryEntry,
    RouteHistoryResponse,
    RouteSummary,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_outbox_event_publisher,
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
    photo_album_data_repo: SqlPhotoAlbumDataRepository
    fitness_data_repo: SqlFitnessDataRepository
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository
    bushwalking_data_repo: SqlBushwalkingDataRepository
    jogging_data_repo: SqlJoggingDataRepository
    abseiling_data_repo: SqlAbseilingDataRepository
    canyoning_data_repo: SqlCanyoningDataRepository
    climbing_data_repo: SqlClimbingDataRepository
    kayaking_data_repo: SqlKayakingDataRepository
    cross_country_skiing_data_repo: SqlCrossCountrySkiingDataRepository
    route_repo: SqlRouteRepository
    contact_relationship_repo: SqlJournalContactRelationshipRepository
    contact_repo: SqlContactRepository
    tag_repo: SqlJournalTagRepository


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
        photo_album_data_repo=SqlPhotoAlbumDataRepository(db_connection),
        fitness_data_repo=SqlFitnessDataRepository(db_connection),
        outdoor_activity_data_repo=SqlOutdoorActivityDataRepository(db_connection),
        bushwalking_data_repo=SqlBushwalkingDataRepository(db_connection),
        jogging_data_repo=SqlJoggingDataRepository(db_connection),
        abseiling_data_repo=SqlAbseilingDataRepository(db_connection),
        canyoning_data_repo=SqlCanyoningDataRepository(db_connection),
        climbing_data_repo=SqlClimbingDataRepository(db_connection),
        kayaking_data_repo=SqlKayakingDataRepository(db_connection),
        cross_country_skiing_data_repo=SqlCrossCountrySkiingDataRepository(
            db_connection
        ),
        route_repo=SqlRouteRepository(db_connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(
            db_connection
        ),
        contact_repo=SqlContactRepository(db_connection),
        tag_repo=SqlJournalTagRepository(db_connection),
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
            parsed_datetime = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
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
    return await _fetch_journal_types_and_data(
        journal_id,
        repos.calendar_info_repo,
        repos.mood_data_repo,
        repos.plan_data_repo,
        repos.travel_data_repo,
        repos.photo_album_data_repo,
        repos.fitness_data_repo,
        repos.outdoor_activity_data_repo,
        repos.bushwalking_data_repo,
        repos.jogging_data_repo,
        repos.abseiling_data_repo,
        repos.canyoning_data_repo,
        repos.climbing_data_repo,
        repos.kayaking_data_repo,
        repos.cross_country_skiing_data_repo,
    )


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
) -> list[tuple[int, str, str]]:
    """
    Fetch contact relationships with contact names for a journal.

    Args:
        journal_id: The journal ID to fetch relationships for
        contact_relationship_repo: Contact relationship repository
        contact_repo: Contact repository

    Returns:
        List of tuples (contact_id, contact_name, relationship_type)
    """
    contact_relationships = await contact_relationship_repo.get_by_journal(journal_id)

    contacts: list[tuple[int, str, str]] = []
    for rel in contact_relationships:
        contact = await contact_repo.find_by_id(rel.contact_id)
        if contact:
            contact_name = f"{contact.first_name} {contact.last_name}".strip()
            if not contact_name:
                contact_name = f"Contact {rel.contact_id}"
            contacts.append((rel.contact_id, contact_name, rel.relationship_type.value))

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
        "timezone": calendar_info.timezone,
        "sync_invitees": calendar_info.sync_invitees,
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


def _build_photo_album_data(photo_album_data: Any) -> dict[str, Any]:
    """Build photo album data dictionary."""
    return {
        "immich_album_id": str(photo_album_data.immich_album_id),
    }


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
        "activity_type": outdoor_activity_data.activity_type,
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
        "number_of_abseils": abseiling_data.number_of_abseils,
        "total_length": abseiling_data.total_length,
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
    }


def _build_kayaking_data(kayaking_data: Any) -> dict[str, Any]:
    """Build kayaking data dictionary."""
    return {
        "water_type": kayaking_data.water_type,
    }


def _build_cross_country_skiing_data(
    cross_country_skiing_data: Any,
) -> dict[str, Any]:
    """Build cross-country skiing data dictionary."""
    return {
        "snow_conditions": cross_country_skiing_data.snow_conditions,
    }


async def _fetch_journal_types_and_data(
    journal_id: int,
    calendar_info_repo: SqlCalendarInfoRepository,
    mood_data_repo: SqlMoodDataRepository,
    plan_data_repo: SqlPlanDataRepository,
    travel_data_repo: SqlTravelDataRepository,
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
    fitness_data_repo: SqlFitnessDataRepository,
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
    bushwalking_data_repo: SqlBushwalkingDataRepository,
    jogging_data_repo: SqlJoggingDataRepository,
    abseiling_data_repo: SqlAbseilingDataRepository,
    canyoning_data_repo: SqlCanyoningDataRepository,
    climbing_data_repo: SqlClimbingDataRepository,
    kayaking_data_repo: SqlKayakingDataRepository,
    cross_country_skiing_data_repo: SqlCrossCountrySkiingDataRepository,
) -> tuple[list[str], dict[str, Any]]:
    """
    Fetch all type-specific data for a journal.

    Args:
        journal_id: The journal ID to fetch data for
        calendar_info_repo: Calendar info repository
        mood_data_repo: Mood data repository
        plan_data_repo: Plan data repository
        travel_data_repo: Travel data repository
        photo_album_data_repo: Photo album data repository
        fitness_data_repo: Fitness data repository
        outdoor_activity_data_repo: Outdoor activity data repository
        bushwalking_data_repo: Bushwalking data repository
        jogging_data_repo: Jogging data repository
        abseiling_data_repo: Abseiling data repository
        canyoning_data_repo: Canyoning data repository
        climbing_data_repo: Climbing data repository
        kayaking_data_repo: Kayaking data repository
        cross_country_skiing_data_repo: Cross-country skiing data repository

    Returns:
        Tuple of (types list, type_data dict)
    """
    types: list[str] = []
    type_data: dict[str, Any] = {}

    # Check each type-specific data table to determine journal types
    calendar_info = await calendar_info_repo.find_by_journal_id(journal_id)
    if calendar_info:
        types.append(JournalType.EVENT.value)
        type_data[JournalType.EVENT.value] = _build_calendar_data(calendar_info)

    mood_data = await mood_data_repo.find_by_journal_id(journal_id)
    if mood_data:
        types.append(JournalType.MOOD_RATING.value)
        type_data[JournalType.MOOD_RATING.value] = _build_mood_data(mood_data)

    plan_data = await plan_data_repo.find_by_journal_id(journal_id)
    if plan_data:
        types.append(JournalType.PLAN.value)
        type_data[JournalType.PLAN.value] = _build_plan_data(plan_data)

    travel_data = await travel_data_repo.find_by_journal_id(journal_id)
    if travel_data:
        types.append(JournalType.TRAVEL.value)
        type_data[JournalType.TRAVEL.value] = _build_travel_data(travel_data)

    photo_album_data = await photo_album_data_repo.find_by_journal_id(journal_id)
    if photo_album_data:
        types.append(JournalType.PHOTO_ALBUM.value)
        type_data[JournalType.PHOTO_ALBUM.value] = _build_photo_album_data(
            photo_album_data
        )

    fitness_data = await fitness_data_repo.find_by_journal_id(journal_id)
    if fitness_data:
        types.append(JournalType.FITNESS.value)
        type_data[JournalType.FITNESS.value] = _build_fitness_data(fitness_data)

    outdoor_activity_data = await outdoor_activity_data_repo.find_by_journal_id(
        journal_id
    )
    if outdoor_activity_data:
        types.append(JournalType.OUTDOOR_ACTIVITY.value)
        type_data[JournalType.OUTDOOR_ACTIVITY.value] = _build_outdoor_activity_data(
            outdoor_activity_data
        )

    bushwalking_data = await bushwalking_data_repo.find_by_journal_id(journal_id)
    if bushwalking_data:
        types.append(JournalType.BUSHWALKING.value)
        type_data[JournalType.BUSHWALKING.value] = _build_bushwalking_data(
            bushwalking_data
        )

    jogging_data = await jogging_data_repo.find_by_journal_id(journal_id)
    if jogging_data:
        types.append(JournalType.JOGGING.value)
        type_data[JournalType.JOGGING.value] = _build_jogging_data(jogging_data)

    abseiling_data = await abseiling_data_repo.find_by_journal_id(journal_id)
    if abseiling_data:
        types.append(JournalType.ABSEILING_TRIP.value)
        type_data[JournalType.ABSEILING_TRIP.value] = _build_abseiling_data(
            abseiling_data
        )

    canyoning_data = await canyoning_data_repo.find_by_journal_id(journal_id)
    if canyoning_data:
        types.append(JournalType.CANYONING.value)
        type_data[JournalType.CANYONING.value] = _build_canyoning_data(canyoning_data)

    climbing_data = await climbing_data_repo.find_by_journal_id(journal_id)
    if climbing_data:
        types.append(JournalType.CLIMBING.value)
        type_data[JournalType.CLIMBING.value] = _build_climbing_data(climbing_data)

    kayaking_data = await kayaking_data_repo.find_by_journal_id(journal_id)
    if kayaking_data:
        types.append(JournalType.KAYAKING.value)
        type_data[JournalType.KAYAKING.value] = _build_kayaking_data(kayaking_data)

    cross_country_skiing_data = await cross_country_skiing_data_repo.find_by_journal_id(
        journal_id
    )
    if cross_country_skiing_data:
        types.append(JournalType.CROSS_COUNTRY_SKIING.value)
        type_data[JournalType.CROSS_COUNTRY_SKIING.value] = (
            _build_cross_country_skiing_data(cross_country_skiing_data)
        )

    # If no types found, it's a NOTE
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
    climbing_data_repo: SqlClimbingDataRepository,
    kayaking_data_repo: SqlKayakingDataRepository,
    cross_country_skiing_data_repo: SqlCrossCountrySkiingDataRepository,
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
        climbing_data_repo: Repository for climbing data
        kayaking_data_repo: Repository for kayaking data
        cross_country_skiing_data_repo: Repository for cross-country skiing data
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

    calendar_info = CalendarInfo(
        journal_id=journal_id,
        calendar_id=calendar_id,
        start_time=_parse_optional_time_field(type_data_dict, "start_time"),
        end_time=_parse_optional_time_field(type_data_dict, "end_time"),
        is_all_day=type_data_dict.get("is_all_day", False),
        location=type_data_dict.get("location"),
        timezone=type_data_dict.get("timezone"),
        sync_invitees=type_data_dict.get("sync_invitees", False),
        event_state=type_data_dict.get("event_state", "confirmed"),
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


async def _update_photo_album_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
) -> None:
    immich_album_id = type_data_dict.get("immich_album_id")
    if immich_album_id is not None:
        photo_album_data = PhotoAlbumData(
            journal_id=journal_id,
            immich_album_id=str(immich_album_id),
        )
        await photo_album_data_repo.save(photo_album_data)


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
            "activity_type",
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
        if "number_of_abseils" in type_data_dict:
            abs_updates["number_of_abseils"] = type_data_dict["number_of_abseils"]
        if "total_length" in type_data_dict:
            abs_updates["total_length"] = type_data_dict["total_length"]
        validated_abseiling = dataclasses.replace(existing_abseiling, **abs_updates)
        await abseiling_data_repo.save(validated_abseiling)


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
        for field in ["climbing_type", "grade", "length"]:
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
        if "water_type" in type_data_dict:
            kayaking_updates["water_type"] = type_data_dict["water_type"]
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
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
    fitness_data_repo: SqlFitnessDataRepository,
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
    bushwalking_data_repo: SqlBushwalkingDataRepository,
    jogging_data_repo: SqlJoggingDataRepository,
    abseiling_data_repo: SqlAbseilingDataRepository,
    canyoning_data_repo: SqlCanyoningDataRepository,
    climbing_data_repo: SqlClimbingDataRepository,
    kayaking_data_repo: SqlKayakingDataRepository,
    cross_country_skiing_data_repo: SqlCrossCountrySkiingDataRepository,
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
        climbing_data_repo: Repository for climbing data
        kayaking_data_repo: Repository for kayaking data
        cross_country_skiing_data_repo: Repository for cross-country skiing data
    """
    if not type_data_dict:
        return

    if journal_type == JournalType.EVENT:
        await _update_event_data(journal_id, type_data_dict, calendar_info_repo)
    elif journal_type == JournalType.MOOD_RATING:
        await _update_mood_data(journal_id, type_data_dict, mood_data_repo)
    elif journal_type == JournalType.PHOTO_ALBUM:
        await _update_photo_album_data(
            journal_id, type_data_dict, photo_album_data_repo
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


async def _persist_contact_relationships(
    journal_id: int,
    contact_relationships: list[dict[str, Any]],
    contact_relationship_repo: SqlJournalContactRelationshipRepository,
) -> None:
    """
    Create contact relationships for a journal.

    Args:
        journal_id: The ID of the journal
        contact_relationships: List of relationship dictionaries with contact_id and relationship_type
        contact_relationship_repo: Repository for contact relationships
    """
    for rel_dict in contact_relationships:
        try:
            contact_id = rel_dict.get("contact_id")
            relationship_type_str = rel_dict.get("relationship_type")

            if contact_id and relationship_type_str:
                # Convert relationship type string to enum
                relationship_type = JournalContactRelationshipType[
                    relationship_type_str.upper()
                ]

                # Create relationship
                relationship = JournalContactRelationship(
                    journal_id=journal_id,
                    contact_id=contact_id,
                    relationship_type=relationship_type,
                )
                await contact_relationship_repo.create(relationship)
        except (ValueError, KeyError):
            # Invalid relationship, skip
            pass


async def _persist_tags(
    journal_id: int,
    tags: list[str],
    tag_repo: SqlJournalTagRepository,
) -> None:
    """
    Find or create tags and assign them to a journal.

    Args:
        journal_id: The ID of the journal
        tags: List of tag names
        tag_repo: Repository for tags
    """
    from uuid import uuid4

    for tag_name in tags:
        try:
            # Find or create tag by name
            all_tags = await tag_repo.get_all()
            tag: JournalTag | None = next(
                (t for t in all_tags if t.name.lower() == tag_name.lower()),
                None,
            )

            if not tag:
                # Tag doesn't exist, create it
                tag = JournalTag(
                    id=uuid4(),
                    name=tag_name,
                    color="#808080",  # Default gray color
                )
                tag = await tag_repo.save(tag)

            # Assign tag to journal (tag.id is guaranteed to be set after save)
            if tag.id is not None:
                await tag_repo.assign_tag(journal_id, tag.id)
        except Exception:
            # Error creating/assigning tag, skip
            pass


async def _fetch_enrichment_data(
    journal_id: int,
    calendar_info_repo: SqlCalendarInfoRepository,
    mood_data_repo: SqlMoodDataRepository,
    plan_data_repo: SqlPlanDataRepository,
    travel_data_repo: SqlTravelDataRepository,
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
    fitness_data_repo: SqlFitnessDataRepository,
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
    bushwalking_data_repo: SqlBushwalkingDataRepository,
    jogging_data_repo: SqlJoggingDataRepository,
    abseiling_data_repo: SqlAbseilingDataRepository,
    canyoning_data_repo: SqlCanyoningDataRepository,
    climbing_data_repo: SqlClimbingDataRepository,
    kayaking_data_repo: SqlKayakingDataRepository,
    cross_country_skiing_data_repo: SqlCrossCountrySkiingDataRepository,
    contact_relationship_repo: SqlJournalContactRelationshipRepository,
    contact_repo: SqlContactRepository,
    tag_repo: SqlJournalTagRepository,
) -> tuple[list[str], dict[str, Any], list[tuple[int, str, str]], list[JournalTag]]:
    """
    Fetch all enrichment data for a journal (types, type_data, contacts, tags).

    Args:
        journal_id: The ID of the journal
        calendar_info_repo: Repository for calendar info
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
        photo_album_data_repo: Repository for photo album data
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        climbing_data_repo: Repository for climbing data
        kayaking_data_repo: Repository for kayaking data
        cross_country_skiing_data_repo: Repository for cross-country skiing data
        contact_relationship_repo: Repository for contact relationships
        contact_repo: Repository for contacts
        tag_repo: Repository for tags

    Returns:
        Tuple of (types, type_data, contacts, tags)
    """
    types, type_data = await _fetch_journal_types_and_data(
        journal_id,
        calendar_info_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        cross_country_skiing_data_repo,
    )

    contacts = await _fetch_contact_relationships_with_names(
        journal_id, contact_relationship_repo, contact_repo
    )

    tags = await tag_repo.get_tags_for_journal(journal_id)

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


def register_journal_tools(mcp: FastMCP[None]) -> None:
    """
    Register journal-related MCP tools with the FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools with
    """

    @mcp.tool
    @mcp_unified_error_handler("create_journal_entry", "journal")
    async def create_journal_entry(
        journal_data: Annotated[
            str,
            Field(
                description="JSON string containing journal creation data with fields: "
                "title (str), content (str), event_date_range (dict with start/end), "
                "types (list[str]), type_data (dict), contact_relationships (list[dict]), "
                "tags (list[str]), parent_id (int, optional)"
            ),
        ],
        db_connection: AsyncConnection = mcp_depends(get_async_connection),
        event_publisher: OutboxEventPublisher = mcp_depends(get_outbox_event_publisher),
    ) -> str:
        """
        Create a new journal entry with types, type-specific data, relationships, and tags.

        Creates a journal entry with support for multiple types (NOTE, EVENT, MOOD_RATING, etc.),
        type-specific data (e.g., calendar_id for EVENT), contact relationships, and tags.
        Returns AI-friendly response with contextual summary.

        Args:
            journal_data: JSON string with journal creation data

        Returns:
            JSON string containing AI-friendly journal information including:
            - Journal details (title, content, date range)
            - Types and type-specific data
            - Contact relationships
            - Tags
            - Contextual summary for AI understanding

        Raises:
            JournalValidationError: If validation fails
            ValueError: If JSON parsing fails or required fields are missing
        """
        # Parse JSON input
        try:
            data_dict = json.loads(journal_data)
            request = JournalCreateRequest(**data_dict)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}") from e
        except Exception as e:
            raise ValueError(f"Invalid journal data: {e}") from e

        # Get current user ID from auth context
        user_id = await get_current_user_id()

        # Create repositories
        repos = _create_journal_tool_repositories(db_connection)
        journal_repo = repos.journal_repo

        # Create journal service
        journal_service = JournalService(journal_repo, event_publisher)

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

        # Create journal
        created_journal = await journal_service.create_journal(journal, db_connection)

        # Ensure journal_id is not None (it should always be set after creation)
        if created_journal.id is None:
            msg = "Journal ID should be set after creation"
            raise ValueError(msg)
        journal_id = created_journal.id

        # Add types if provided in the request
        if request.types:
            for type_str in request.types:
                try:
                    # Convert type string to enum
                    journal_type = JournalType[type_str.upper()]

                    # Capture the return value: includes all types added (requested +
                    # auto-resolved dependencies like FITNESS for OUTDOOR_ACTIVITY).
                    added_types = await journal_service.add_type_to_journal(
                        journal_id, journal_type, db_connection
                    )

                    # Create type-specific data rows for ALL added types (including
                    # dependency types like FITNESS). Mirrors REST controller behaviour.
                    for added_type in added_types:
                        await _create_type_specific_data(
                            added_type,
                            journal_id,
                            repos.mood_data_repo,
                            repos.plan_data_repo,
                            repos.travel_data_repo,
                            repos.fitness_data_repo,
                            repos.outdoor_activity_data_repo,
                            repos.bushwalking_data_repo,
                            repos.jogging_data_repo,
                            repos.abseiling_data_repo,
                            repos.canyoning_data_repo,
                            repos.climbing_data_repo,
                            repos.kayaking_data_repo,
                            repos.cross_country_skiing_data_repo,
                        )

                    # Update type-specific data if provided
                    if request.type_data and type_str.upper() in request.type_data:
                        await _update_type_specific_data(
                            journal_type,
                            journal_id,
                            request.type_data[type_str.upper()],
                            repos.calendar_info_repo,
                            repos.mood_data_repo,
                            repos.photo_album_data_repo,
                            repos.fitness_data_repo,
                            repos.outdoor_activity_data_repo,
                            repos.bushwalking_data_repo,
                            repos.jogging_data_repo,
                            repos.abseiling_data_repo,
                            repos.canyoning_data_repo,
                            repos.climbing_data_repo,
                            repos.kayaking_data_repo,
                            repos.cross_country_skiing_data_repo,
                        )
                except (ValueError, KeyError):
                    # Invalid type, skip
                    pass

        # Add contact relationships if provided
        if request.contact_relationships:
            await _persist_contact_relationships(
                journal_id,
                request.contact_relationships,
                repos.contact_relationship_repo,
            )

        # Add tags if provided
        if request.tags:
            await _persist_tags(journal_id, request.tags, repos.tag_repo)

        # Fetch all enrichment data
        types, type_data, contacts, tags = await _fetch_enrichment_data(
            journal_id,
            repos.calendar_info_repo,
            repos.mood_data_repo,
            repos.plan_data_repo,
            repos.travel_data_repo,
            repos.photo_album_data_repo,
            repos.fitness_data_repo,
            repos.outdoor_activity_data_repo,
            repos.bushwalking_data_repo,
            repos.jogging_data_repo,
            repos.abseiling_data_repo,
            repos.canyoning_data_repo,
            repos.climbing_data_repo,
            repos.kayaking_data_repo,
            repos.cross_country_skiing_data_repo,
            repos.contact_relationship_repo,
            repos.contact_repo,
            repos.tag_repo,
        )

        parent = None
        if created_journal.parent_id is not None:
            parent = await repos.journal_repo.find_by_id(created_journal.parent_id)

        # Convert to AI-friendly response
        response = JournalConverter.to_response(
            journal=created_journal,
            types=types,
            type_data=type_data,
            contacts=contacts,
            tags=tags,
            parent=parent,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def update_journal_entry(
        journal_id: Annotated[
            int, Field(description="The unique identifier of the journal to update")
        ],
        journal_data: Annotated[
            str,
            Field(
                description="JSON string containing journal update data with optional fields: "
                "title (str), content (str), event_date_range (dict with start/end), "
                "types (list[str]), type_data (dict), contact_relationships (list[dict]), "
                "tags (list[str])"
            ),
        ],
        db_connection: AsyncConnection = mcp_depends(get_async_connection),
        event_publisher: OutboxEventPublisher = mcp_depends(get_outbox_event_publisher),
    ) -> str:
        """
        Update an existing journal entry with partial data.

        Updates journal fields, types, type-specific data, contact relationships, and tags.
        Only provided fields are updated; omitted fields remain unchanged.
        Returns AI-friendly response with contextual summary.

        Args:
            journal_id: The unique identifier of the journal to update
            journal_data: JSON string with journal update data (partial)

        Returns:
            JSON string containing AI-friendly updated journal information

        Raises:
            JournalNotFoundError: If the journal with the given ID does not exist
            JournalValidationError: If validation fails
            ValueError: If JSON parsing fails
        """
        # Parse JSON input
        try:
            data_dict = json.loads(journal_data)
            request = JournalUpdateRequest(**data_dict)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}") from e
        except Exception as e:
            raise ValueError(f"Invalid journal data: {e}") from e

        # Create repositories
        repos = _create_journal_tool_repositories(db_connection)
        journal_repo = repos.journal_repo
        journal_service = JournalService(journal_repo, event_publisher)

        # Get existing journal
        existing_journal = await journal_repo.find_by_id(journal_id)
        if not existing_journal:
            raise JournalNotFoundError(journal_id)

        # Track changed fields
        changed_fields: dict[str, Any] = {}

        # Update journal fields
        if request.title is not None:
            existing_journal.title = request.title
            changed_fields["title"] = request.title
        if request.content is not None:
            existing_journal.content = request.content
            changed_fields["content"] = request.content
        if request.event_date_range is not None:
            existing_journal.event_date_range = EventDateRange(
                start=request.event_date_range.start,
                end=request.event_date_range.end,
            )
            changed_fields["event_date_range"] = request.event_date_range

        if "parent_id" in request.model_fields_set:
            existing_journal.parent_id = request.parent_id
            changed_fields["parent_id"] = request.parent_id

        # Update journal
        updated_journal = await journal_service.update_journal(
            existing_journal, changed_fields, db_connection
        )

        # Update types if provided (replace all types)
        if request.types is not None:
            # Get current types
            current_types, _ = await _fetch_journal_types_and_data(
                journal_id,
                repos.calendar_info_repo,
                repos.mood_data_repo,
                repos.plan_data_repo,
                repos.travel_data_repo,
                repos.photo_album_data_repo,
                repos.fitness_data_repo,
                repos.outdoor_activity_data_repo,
                repos.bushwalking_data_repo,
                repos.jogging_data_repo,
                repos.abseiling_data_repo,
                repos.canyoning_data_repo,
                repos.climbing_data_repo,
                repos.kayaking_data_repo,
                repos.cross_country_skiing_data_repo,
            )

            # Remove types that are not in the new list
            for current_type_str in current_types:
                if current_type_str not in [t.upper() for t in request.types]:
                    try:
                        current_type = JournalType[current_type_str.upper()]
                        await journal_service.remove_type_from_journal(
                            journal_id, current_type, db_connection
                        )
                    except (ValueError, KeyError):
                        pass

            # Add new types
            for type_str in request.types:
                try:
                    journal_type = JournalType[type_str.upper()]

                    # Only add if not already present
                    if type_str.upper() not in current_types:
                        # Capture the return value: includes all types added (requested +
                        # auto-resolved dependencies like FITNESS for OUTDOOR_ACTIVITY).
                        added_types = await journal_service.add_type_to_journal(
                            journal_id, journal_type, db_connection
                        )

                        # Create type-specific data rows for ALL added types (including
                        # dependency types like FITNESS). Mirrors REST controller behaviour.
                        for added_type in added_types:
                            await _create_type_specific_data(
                                added_type,
                                journal_id,
                                repos.mood_data_repo,
                                repos.plan_data_repo,
                                repos.travel_data_repo,
                                repos.fitness_data_repo,
                                repos.outdoor_activity_data_repo,
                                repos.bushwalking_data_repo,
                                repos.jogging_data_repo,
                                repos.abseiling_data_repo,
                                repos.canyoning_data_repo,
                                repos.climbing_data_repo,
                                repos.kayaking_data_repo,
                                repos.cross_country_skiing_data_repo,
                            )

                    # Update type-specific data if provided
                    if request.type_data and type_str.upper() in request.type_data:
                        await _update_type_specific_data(
                            journal_type,
                            journal_id,
                            request.type_data[type_str.upper()],
                            repos.calendar_info_repo,
                            repos.mood_data_repo,
                            repos.photo_album_data_repo,
                            repos.fitness_data_repo,
                            repos.outdoor_activity_data_repo,
                            repos.bushwalking_data_repo,
                            repos.jogging_data_repo,
                            repos.abseiling_data_repo,
                            repos.canyoning_data_repo,
                            repos.climbing_data_repo,
                            repos.kayaking_data_repo,
                            repos.cross_country_skiing_data_repo,
                        )
                except (ValueError, KeyError):
                    # Invalid type, skip
                    pass

        # Update type_data if provided (without changing types)
        elif request.type_data is not None:
            for type_str, type_data_dict in request.type_data.items():
                try:
                    journal_type = JournalType[type_str.upper()]
                    await _update_type_specific_data(
                        journal_type,
                        journal_id,
                        type_data_dict,
                        repos.calendar_info_repo,
                        repos.mood_data_repo,
                        repos.photo_album_data_repo,
                        repos.fitness_data_repo,
                        repos.outdoor_activity_data_repo,
                        repos.bushwalking_data_repo,
                        repos.jogging_data_repo,
                        repos.abseiling_data_repo,
                        repos.canyoning_data_repo,
                        repos.climbing_data_repo,
                        repos.kayaking_data_repo,
                        repos.cross_country_skiing_data_repo,
                    )
                except (ValueError, KeyError):
                    # Invalid type, skip
                    pass

        # Update contact relationships if provided (replace all relationships)
        if request.contact_relationships is not None:
            # Remove all existing relationships
            existing_relationships = (
                await repos.contact_relationship_repo.get_by_journal(journal_id)
            )
            for rel in existing_relationships:
                await repos.contact_relationship_repo.delete(
                    journal_id, rel.contact_id, rel.relationship_type
                )

            # Add new relationships
            await _persist_contact_relationships(
                journal_id,
                request.contact_relationships,
                repos.contact_relationship_repo,
            )

        # Update tags if provided (replace all tags)
        if request.tags is not None:
            # Remove all existing tags
            existing_tags = await repos.tag_repo.get_tags_for_journal(journal_id)
            for existing_tag in existing_tags:
                if existing_tag.id is not None:
                    await repos.tag_repo.remove_tag(journal_id, existing_tag.id)

            # Add new tags
            await _persist_tags(journal_id, request.tags, repos.tag_repo)

        # Fetch all enrichment data
        types, type_data, contacts, tags = await _fetch_enrichment_data(
            journal_id,
            repos.calendar_info_repo,
            repos.mood_data_repo,
            repos.plan_data_repo,
            repos.travel_data_repo,
            repos.photo_album_data_repo,
            repos.fitness_data_repo,
            repos.outdoor_activity_data_repo,
            repos.bushwalking_data_repo,
            repos.jogging_data_repo,
            repos.abseiling_data_repo,
            repos.canyoning_data_repo,
            repos.climbing_data_repo,
            repos.kayaking_data_repo,
            repos.cross_country_skiing_data_repo,
            repos.contact_relationship_repo,
            repos.contact_repo,
            repos.tag_repo,
        )

        parent = None
        if updated_journal.parent_id is not None:
            parent = await repos.journal_repo.find_by_id(updated_journal.parent_id)

        # Convert to AI-friendly response
        response = JournalConverter.to_response(
            journal=updated_journal,
            types=types,
            type_data=type_data,
            contacts=contacts,
            tags=tags,
            parent=parent,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
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
        # Create repositories
        repos = _create_journal_tool_repositories(db_connection)
        journal_repo = repos.journal_repo

        # Get journal
        journal = await journal_repo.find_by_id(journal_id)
        if not journal:
            raise JournalNotFoundError(journal_id)

        # Get children if requested
        children = None
        if include_children:
            children = await journal_repo.get_children(journal_id)

        # Fetch types and type-specific data
        types, type_data = await _fetch_journal_types_and_data(
            journal_id,
            repos.calendar_info_repo,
            repos.mood_data_repo,
            repos.plan_data_repo,
            repos.travel_data_repo,
            repos.photo_album_data_repo,
            repos.fitness_data_repo,
            repos.outdoor_activity_data_repo,
            repos.bushwalking_data_repo,
            repos.jogging_data_repo,
            repos.abseiling_data_repo,
            repos.canyoning_data_repo,
            repos.climbing_data_repo,
            repos.kayaking_data_repo,
            repos.cross_country_skiing_data_repo,
        )

        # Fetch contact relationships and contact details
        contacts = await _fetch_contact_relationships_with_names(
            journal_id, repos.contact_relationship_repo, repos.contact_repo
        )

        # Fetch tags
        journal_tags = await repos.tag_repo.get_tags_for_journal(journal_id)

        # Convert to AI-friendly response
        response = JournalConverter.to_response(
            journal=journal,
            types=types,
            type_data=type_data,
            contacts=contacts,
            tags=journal_tags,
            children=children,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
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
        children_count_by_parent_id = (
            await repos.journal_repo.count_children_for_parents(
                user_id=user_id, parent_ids=returned_ids_list
            )
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

    @mcp.tool
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
        Search journals with filtering options.

        Searches journals by query, types, and other filters.
        Returns AI-friendly summaries with relevance scores.

        Args:
            query: Optional search query for full-text search
            types: Optional comma-separated list of journal types
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

        if len(type_filters) <= 1:
            journal_type = type_filters[0] if type_filters else None
            total_hits = await repos.journal_repo.count_all(
                user_id=user_id,
                journal_type=journal_type,
                search=query,
            )
            journals = await repos.journal_repo.get_all(
                user_id=user_id,
                limit=limit,
                offset=0,
                journal_type=journal_type,
                search=query,
            )
            results = await _build_search_results(journals, repos)
        else:
            candidate_count = await repos.journal_repo.count_all(
                user_id=user_id, search=query
            )
            if candidate_count == 0:
                journals = []
            else:
                journals = await repos.journal_repo.get_all(
                    user_id=user_id,
                    limit=candidate_count,
                    offset=0,
                    search=query,
                )

            filtered_journals: list[Journal] = []
            results = []
            requested_types = set(type_filters)
            for journal in journals:
                if journal.id is None:
                    continue
                journal_types, _ = await _fetch_types_for_journal(journal.id, repos)
                if requested_types.isdisjoint(journal_types):
                    continue
                filtered_journals.append(journal)
                results.append(
                    _journal_to_search_result(
                        journal,
                        types=journal_types,
                    )
                )

            total_hits = len(filtered_journals)
            results = results[:limit]

        response = JournalSearchResponse(
            results=results,
            query=query,
            total_hits=total_hits,
            processing_time_ms=0,
            summary=f"Found {total_hits} journal(s)",
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
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

    @mcp.tool
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
            elevation_gain=int(
                getattr(overall_stats_row, "total_elevation_gain", 0) or 0
            ),
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

    @mcp.tool
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

    @mcp.tool
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

        history_rows = await _fetch_route_history_rows(
            db_connection, user_id, route_uuid
        )
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
            {
                entry.activity_type
                for entry in entries
                if entry.activity_type is not None
            }
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

    @mcp.tool
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

        Args:
            journal_id: The unique identifier of the journal to delete
            delete_children: Optional flag to delete child journals

        Returns:
            JSON string containing deletion confirmation

        Raises:
            JournalNotFoundError: If the journal with the given ID does not exist
        """
        # Explicitly reject unsupported delete_children behavior to avoid silent misuse
        if delete_children:
            raise NotImplementedError(
                "The 'delete_children' flag is not yet supported. "
                "Child journals are not deleted automatically."
            )

        # Create repositories
        journal_repo = SqlJournalRepository(db_connection)
        journal_service = JournalService(journal_repo, event_publisher)

        # Delete journal
        await journal_service.delete_journal(journal_id, db_connection)

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

    @mcp.tool
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

    @mcp.tool
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
            Field(
                description="Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)"
            ),
        ],
        db_connection: AsyncConnection = mcp_depends(get_async_connection),
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
            JournalNotFoundError: If the journal with the given ID does not exist
            ContactNotFoundError: If the contact with the given ID does not exist
            ValueError: If relationship_type is invalid
        """
        # Validate relationship type
        try:
            rel_type = JournalContactRelationshipType(relationship_type.upper())
        except ValueError as e:
            raise ValueError(
                f"Invalid relationship type: {relationship_type}. "
                f"Must be one of: PARTICIPANT, INVITEE, MENTION, ABOUT"
            ) from e

        # Create repositories
        contact_rel_repo = SqlJournalContactRelationshipRepository(db_connection)
        journal_repo = SqlJournalRepository(db_connection)
        contact_repo = SqlContactRepository(db_connection)

        # Verify journal exists
        journal = await journal_repo.find_by_id(journal_id)
        if not journal:
            raise JournalNotFoundError(journal_id)

        # Verify contact exists
        contact = await contact_repo.find_by_id(contact_id)
        if not contact:
            raise ContactNotFoundError(contact_id)

        # Create relationship
        relationship = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=rel_type,
        )
        await contact_rel_repo.create(relationship)

        class LinkResponse(BaseModel):
            journal_id: int
            contact_id: int
            relationship_type: str
            linked: bool
            summary: str

        response = LinkResponse(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=relationship_type,
            linked=True,
            summary=f"Successfully linked journal {journal_id} to contact {contact_id} as {relationship_type}",
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
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

    @mcp.tool
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
    ) -> str:
        """
        Create a new calendar to be used with EVENT journals.
        """
        user_id = await get_current_user_id()
        calendar_repo = SqlCalendarRepository(db_connection)

        new_calendar = Calendar(
            user_id=user_id,
            name=name,
            description=description,
            color=color or "#3B82F6",
            is_synced_to_google=False,
            google_calendar_id=None,
        )

        saved_calendar = await calendar_repo.save(new_calendar)

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

    @mcp.tool
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
    ) -> str:
        """
        Update an existing calendar.
        """
        user_id = await get_current_user_id()
        calendar_repo = SqlCalendarRepository(db_connection)

        calendar_uuid = _parse_calendar_id(calendar_id)
        if calendar_uuid is None:
            raise ValueError(
                f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID."
            )

        calendar = await calendar_repo.find_by_id(calendar_uuid)
        if not calendar or calendar.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response("Calendar", calendar_id)

        if name is not None:
            calendar.name = name
        if description is not None:
            calendar.description = description
        if color is not None:
            calendar.color = color

        saved_calendar = await calendar_repo.save(calendar)

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

    @mcp.tool
    @mcp_unified_error_handler("delete_calendar", "journal")
    async def delete_calendar(
        calendar_id: Annotated[str, Field(description="Calendar UUID")],
        db_connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Delete a calendar. Will fail if the calendar is in use.
        """
        user_id = await get_current_user_id()
        calendar_repo = SqlCalendarRepository(db_connection)

        calendar_uuid = _parse_calendar_id(calendar_id)
        if calendar_uuid is None:
            raise ValueError(
                f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID."
            )

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
        result = await db_connection.execute(
            check_query, {"calendar_id": str(calendar.id)}
        )
        usage_count = int(result.scalar_one())

        if usage_count > 0:
            return MCPResponseBuilder.error_response(
                "CONFLICT",
                f"Calendar is in use by {usage_count} journal(s)",
            )

        if calendar.id is not None:
            await calendar_repo.delete(calendar.id)

        class DeleteCalendarResponse(BaseModel):
            summary: str

        return MCPResponseBuilder.success_response(
            DeleteCalendarResponse(summary=f"Deleted calendar '{calendar.name}'")
        )

    @mcp.tool
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
                    'Optional key: "overrides" (object) — explicit conflict resolution '
                    'with keys: "title" (str), "content" (str), '
                    '"event_date_range" ({start, end}), '
                    '"type_data" ({TYPE: {field: value}})'
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

        Call get_merge_candidates first to find suitable merge targets.

        Args:
            target_journal_id: ID of the journal to keep
            merge_data: JSON string containing source_journal_id and optional overrides

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

        merge_service = JournalMergeService(repos.journal_repo, event_publisher)

        merged_journal = await merge_service.merge_journals(
            target_id=target_journal_id,
            source_id=merge_request.source_journal_id,
            transaction=db_connection,
            overrides=merge_request.overrides,
        )

        # Fetch enriched target
        types, type_data = await _fetch_journal_types_and_data(
            target_journal_id,
            repos.calendar_info_repo,
            repos.mood_data_repo,
            repos.plan_data_repo,
            repos.travel_data_repo,
            repos.photo_album_data_repo,
            repos.fitness_data_repo,
            repos.outdoor_activity_data_repo,
            repos.bushwalking_data_repo,
            repos.jogging_data_repo,
            repos.abseiling_data_repo,
            repos.canyoning_data_repo,
            repos.climbing_data_repo,
            repos.kayaking_data_repo,
            repos.cross_country_skiing_data_repo,
        )

        contacts = await _fetch_contact_relationships_with_names(
            target_journal_id,
            repos.contact_relationship_repo,
            repos.contact_repo,
        )

        journal_tags = await repos.tag_repo.get_tags_for_journal(target_journal_id)

        response = JournalConverter.to_response(
            journal=merged_journal,
            types=types,
            type_data=type_data,
            contacts=contacts,
            tags=journal_tags,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
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

        target = await repos.journal_repo.find_by_id(journal_id)
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
                "user_id": target.user_id,
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
            c_types, _ = await _fetch_journal_types_and_data(
                candidate_id,
                repos.calendar_info_repo,
                repos.mood_data_repo,
                repos.plan_data_repo,
                repos.travel_data_repo,
                repos.photo_album_data_repo,
                repos.fitness_data_repo,
                repos.outdoor_activity_data_repo,
                repos.bushwalking_data_repo,
                repos.jogging_data_repo,
                repos.abseiling_data_repo,
                repos.canyoning_data_repo,
                repos.climbing_data_repo,
                repos.kayaking_data_repo,
                repos.cross_country_skiing_data_repo,
            )
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

    @mcp.tool
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
        end_iso = datetime.combine(
            window_end, dt_time(23, 59, 59), tzinfo=UTC
        ).isoformat()

        type_filters = _parse_type_filters(types)
        journal_type = type_filters[0] if len(type_filters) == 1 else None

        total_count = await repos.journal_repo.count_all(
            user_id=user_id,
            journal_type=journal_type,
            start_date=start_iso,
            end_date=end_iso,
            search=search,
        )

        journals = await repos.journal_repo.get_all(
            user_id=user_id,
            limit=limit,
            offset=offset,
            journal_type=journal_type,
            start_date=start_iso,
            end_date=end_iso,
            search=search,
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
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
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

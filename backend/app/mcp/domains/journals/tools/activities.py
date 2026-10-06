"""MCP tools for activity journals: search, statistics, trends and route usage.

The reads belong to ``ActivityStatsRepository`` and
``RouteRepository.find_usage_history``; these tools validate the arguments
and shape the responses.
"""

from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.activity_stats import (
    ActivityFilters,
    ActivityJournalRow,
    ActivityMetric,
    TrendInterval,
    parse_activity_type,
)
from app.core.journal.models.repositories import (
    ActivityStatsRepository,
)
from app.core.journal.services.journal_enrichment_service import (
    JournalEnrichmentService,
)
from app.mcp.domains.journals.schemas import (
    ActivityPersonalRecord,
    ActivityStatsResponse,
    ActivityTotals,
    ActivityTrendPeriod,
    ActivityTrendsResponse,
    ActivityTypeStats,
    EventDateRangeSchema,
    JournalSearchResponse,
    RouteHistoryEntry,
    RouteHistoryResponse,
    RouteSummary,
)
from app.mcp.domains.journals.tools._shared import (
    build_search_results,
    create_journal_tool_repositories,
    parse_optional_datetime_filter,
)
from app.mcp.shared.annotations import (
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_activity_stats_repository,
    get_async_connection,
    get_current_user_id,
    get_journal_enrichment_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


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
        start_date=parse_optional_datetime_filter(start_date, "start_date"),
        end_date=parse_optional_datetime_filter(end_date, "end_date", is_end=True),
        search_query=search_query,
    )


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
    activity_stats_repo: ActivityStatsRepository = mcp_depends(
        get_activity_stats_repository
    ),
    enrichment_service: JournalEnrichmentService = mcp_depends(
        get_journal_enrichment_service
    ),
) -> str:
    """Search activity journals with effective activity-type filtering."""
    user_id = await get_current_user_id()
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

    results = await build_search_results(
        [activity_row.journal for activity_row in activity_rows],
        enrichment_service,
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
    repos = create_journal_tool_repositories(db_connection)

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


def register_activity_tools(mcp: FastMCP[None]) -> None:
    """Register the activities MCP tools with the FastMCP server."""
    mcp.add_tool(search_activities)
    mcp.add_tool(get_activity_stats)
    mcp.add_tool(analyze_activity_trends)
    mcp.add_tool(get_route_history)

"""SQL implementation of ``ActivityStatsRepository``.

Every read builds on one CTE over the user's journals with fitness data, which
resolves each journal's effective activity type from the subtype rows it carries.
The reads then filter, page or aggregate that CTE, so the counts, totals, records
and trends always agree about which journals are activities and of what type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core_shared.models.journals import EventDateRange, Journal
from sqlalchemy import text

from app.core.journal.models.activity_stats import (
    ActivityFilters,
    ActivityJournalRow,
    ActivityMetric,
    ActivityPersonalRecordRow,
    ActivityTotalsRow,
    ActivityTrendRow,
    ActivityTypeTotalsRow,
    TrendInterval,
)
from app.core.journal.models.repositories import ActivityStatsRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


def _query_filters(
    filters: ActivityFilters,
) -> tuple[dict[str, Any], list[str]]:
    """Bind parameters and WHERE clauses over the activity CTE for ``filters``."""
    params: dict[str, Any] = {"user_id": filters.user_id}
    where_clauses: list[str] = []

    if filters.search_query:
        params["search_pattern"] = f"%{filters.search_query}%"
        where_clauses.append(
            "(title ILIKE :search_pattern OR content ILIKE :search_pattern)"
        )

    if filters.activity_type is not None:
        params["activity_type"] = filters.activity_type
        where_clauses.append("activity_type = :activity_type")

    if filters.start_date is not None:
        params["start_date"] = filters.start_date
        where_clauses.append("event_date_range_end >= :start_date")

    if filters.end_date is not None:
        params["end_date"] = filters.end_date
        where_clauses.append("event_date_range_start <= :end_date")

    return params, where_clauses


def _activity_rows_query_sql(
    where_clauses: list[str],
    *,
    select_sql: str,
    include_ordering: bool,
) -> str:
    """Activity journal SQL with optional shared filters and ordering."""
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


def _journal_from_row(row: Any) -> Journal:
    """Build a journal entity from an activity CTE row."""
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


class SqlActivityStatsRepository(ActivityStatsRepository):
    """SQL implementation of ``ActivityStatsRepository``."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.conn = connection

    async def list_activity_journals(
        self,
        filters: ActivityFilters,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ActivityJournalRow]:
        params, where_clauses = _query_filters(filters)
        query_sql = _activity_rows_query_sql(
            where_clauses,
            select_sql="SELECT *",
            include_ordering=True,
        )

        if limit is not None:
            params["limit"] = limit
            params["offset"] = offset
            query_sql += "\n        LIMIT :limit OFFSET :offset"

        result = await self.conn.execute(text(query_sql), params)
        return [
            ActivityJournalRow(
                journal=_journal_from_row(row),
                activity_type=row.activity_type,
                distance=int(row.distance or 0),
                duration=int(row.duration or 0),
                elevation_gain=int(row.elevation_gain or 0),
                calories=int(row.calories or 0),
            )
            for row in result.fetchall()
        ]

    async def count_activity_journals(self, filters: ActivityFilters) -> int:
        params, where_clauses = _query_filters(filters)
        query_sql = _activity_rows_query_sql(
            where_clauses,
            select_sql="SELECT COUNT(*)",
            include_ordering=False,
        )

        result = await self.conn.execute(text(query_sql), params)
        row = result.fetchone()
        if row is None:
            return 0
        count_value = row[0]
        return int(count_value) if count_value is not None else 0

    async def get_totals(self, filters: ActivityFilters) -> ActivityTotalsRow:
        params, where_clauses = _query_filters(filters)
        query_sql = _activity_rows_query_sql(
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

        result = await self.conn.execute(text(query_sql), params)
        row = result.fetchone()
        return ActivityTotalsRow(
            total_activities=int(getattr(row, "total_activities", 0) or 0),
            total_distance=int(getattr(row, "total_distance", 0) or 0),
            total_duration=int(getattr(row, "total_duration", 0) or 0),
            total_elevation_gain=int(getattr(row, "total_elevation_gain", 0) or 0),
            total_calories=int(getattr(row, "total_calories", 0) or 0),
        )

    async def list_type_totals(
        self, filters: ActivityFilters
    ) -> list[ActivityTypeTotalsRow]:
        params, where_clauses = _query_filters(filters)
        query_sql = _activity_rows_query_sql(
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

        result = await self.conn.execute(text(query_sql), params)
        return [
            ActivityTypeTotalsRow(
                activity_type=row.activity_type,
                # ``row.count`` would be the Row tuple's own count() method.
                count=int(row._mapping["count"] or 0),
                total_distance=int(row.total_distance or 0),
                total_duration=int(row.total_duration or 0),
                total_elevation_gain=int(row.total_elevation_gain or 0),
                total_calories=int(row.total_calories or 0),
            )
            for row in result.fetchall()
        ]

    async def find_personal_record(
        self, filters: ActivityFilters, metric: ActivityMetric
    ) -> ActivityPersonalRecordRow | None:
        # ``metric`` is interpolated as a column name, so only an ActivityMetric
        # member may reach the SQL.
        metric_name = ActivityMetric(metric).value
        params, where_clauses = _query_filters(filters)
        query_sql = _activity_rows_query_sql(
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

        result = await self.conn.execute(text(query_sql), params)
        row = result.fetchone()
        if row is None:
            return None
        return ActivityPersonalRecordRow(
            activity_type=row.activity_type,
            journal_id=int(row.journal_id),
            journal_title=row.journal_title,
            value=int(row.metric_value or 0),
        )

    async def list_trend_buckets(
        self, filters: ActivityFilters, interval: TrendInterval
    ) -> list[ActivityTrendRow]:
        params, where_clauses = _query_filters(filters)
        params["interval_unit"] = TrendInterval(interval).value
        query_sql = _activity_rows_query_sql(
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

        result = await self.conn.execute(text(query_sql), params)
        return [
            ActivityTrendRow(
                period_start=row.period_start,
                activity_count=int(row.activity_count or 0),
                total_distance=int(row.total_distance or 0),
                total_duration=int(row.total_duration or 0),
                total_elevation_gain=int(row.total_elevation_gain or 0),
            )
            for row in result.fetchall()
        ]

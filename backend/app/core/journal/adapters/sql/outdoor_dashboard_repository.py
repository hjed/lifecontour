"""SQL implementation of the outdoor dashboard projections.

Two windowed read queries over ``journals.event_date_range_start/end`` with an
overlap predicate (a multi-day trip straddling a window bound still matches):

- **Upcoming** — journals that are outdoor activities *or* OUTDOOR_PLANNING
  events (both marked purely by data-row presence).
- **Type facts** — outdoor journals only, with per-subtype presence flags the
  service reduces to effective journal types.

The subtype presence flags are generated from the shared ``SUBTYPE_TABLES``
registry (plus OUTDOOR_TRAINING, which carries only a presence flag), so a new
subtype flows into both dashboard queries with no SQL edits. Every joined
table is keyed 1:1 on ``journal_id``, so the LEFT JOINs cannot fan out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core_shared.models.journals import (
    SUBTYPE_FACTS_FIELDS,
    EventDateRange,
    OutdoorActivitySubtype,
    OutdoorActivityTypeFacts,
    UpcomingOutdoorActivity,
)
from sqlalchemy import text

from app.core.journal.adapters.sql.incomplete_outdoor_activity_repository import (
    SUBTYPE_TABLES,
)
from app.core.journal.models.repositories import OutdoorDashboardRepository

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.engine import RowMapping
    from sqlalchemy.ext.asyncio import AsyncConnection

# Presence-flag column per subtype (``has_<facts_attr>``), OUTDOOR_TRAINING
# included: it has no rule-1 attributes but is an outdoor subtype for the
# dashboard's type grouping, mirroring ``OutdoorActivityFacts``.
_SUBTYPE_FLAG_COLUMNS: dict[OutdoorActivitySubtype, str] = {
    subtype: f"has_{facts_attr}"
    for subtype, (facts_attr, _model) in SUBTYPE_FACTS_FIELDS.items()
} | {OutdoorActivitySubtype.OUTDOOR_TRAINING: "has_outdoor_training"}

_FLAG_SELECT_SQL = ",\n        ".join(
    f"({facts_attr}.journal_id IS NOT NULL) AS has_{facts_attr}"
    for facts_attr in SUBTYPE_TABLES
)

_FLAG_JOIN_SQL = "\n    ".join(
    f"LEFT JOIN {table} {facts_attr} ON {facts_attr}.journal_id = j.id"
    for facts_attr, table in SUBTYPE_TABLES.items()
)

_WINDOW_PREDICATE_SQL = """j.user_id = :user_id
        AND j.event_date_range_end >= :window_start
        AND j.event_date_range_start <= :window_end"""

_UPCOMING_QUERY = text(
    f"""
    SELECT
        j.id AS journal_id,
        j.title AS title,
        j.event_date_range_start AS event_start,
        j.event_date_range_end AS event_end,
        (outdoor_planning.journal_id IS NOT NULL) AS is_planning,
        {_FLAG_SELECT_SQL},
        (outdoor_training.journal_id IS NOT NULL) AS has_outdoor_training
    FROM journals j
    LEFT JOIN journal_outdoor_activity_data outdoor_activity
        ON outdoor_activity.journal_id = j.id
    LEFT JOIN journal_outdoor_planning_data outdoor_planning
        ON outdoor_planning.journal_id = j.id
    {_FLAG_JOIN_SQL}
    LEFT JOIN journal_outdoor_training_data outdoor_training
        ON outdoor_training.journal_id = j.id
    WHERE {_WINDOW_PREDICATE_SQL}
        AND (
            outdoor_activity.journal_id IS NOT NULL
            OR outdoor_planning.journal_id IS NOT NULL
        )
    """
)

_TYPE_FACTS_QUERY = text(
    f"""
    SELECT
        j.id AS journal_id,
        j.event_date_range_start AS event_start,
        j.event_date_range_end AS event_end,
        {_FLAG_SELECT_SQL},
        (outdoor_training.journal_id IS NOT NULL) AS has_outdoor_training
    FROM journals j
    JOIN journal_outdoor_activity_data outdoor_activity
        ON outdoor_activity.journal_id = j.id
    {_FLAG_JOIN_SQL}
    LEFT JOIN journal_outdoor_training_data outdoor_training
        ON outdoor_training.journal_id = j.id
    WHERE {_WINDOW_PREDICATE_SQL}
    """
)


def _row_subtypes(row: RowMapping) -> list[OutdoorActivitySubtype]:
    return [
        subtype
        for subtype, flag_column in _SUBTYPE_FLAG_COLUMNS.items()
        if row[flag_column]
    ]


class SqlOutdoorDashboardRepository(OutdoorDashboardRepository):
    """Windowed dashboard projections over the user's outdoor journals."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def list_upcoming_journals(
        self, user_id: str, *, window_start: datetime, window_end: datetime
    ) -> list[UpcomingOutdoorActivity]:
        """Outdoor and OUTDOOR_PLANNING journals overlapping the window."""
        result = await self.connection.execute(
            _UPCOMING_QUERY,
            {
                "user_id": user_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        return [
            UpcomingOutdoorActivity(
                journal_id=int(row["journal_id"]),
                title=str(row["title"]),
                event_date_range=EventDateRange(
                    start=row["event_start"], end=row["event_end"]
                ),
                subtypes=_row_subtypes(row),
                is_planning=bool(row["is_planning"]),
            )
            for row in result.mappings()
        ]

    async def list_outdoor_type_facts(
        self, user_id: str, *, window_start: datetime, window_end: datetime
    ) -> list[OutdoorActivityTypeFacts]:
        """Per-journal subtype facts for outdoor journals in the window."""
        result = await self.connection.execute(
            _TYPE_FACTS_QUERY,
            {
                "user_id": user_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        return [
            OutdoorActivityTypeFacts(
                journal_id=int(row["journal_id"]),
                event_date_range=EventDateRange(
                    start=row["event_start"], end=row["event_end"]
                ),
                subtypes=_row_subtypes(row),
            )
            for row in result.mappings()
        ]

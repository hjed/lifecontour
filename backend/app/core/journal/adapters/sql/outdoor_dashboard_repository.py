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

Two per-row facts queries feed the remaining widgets:

- **Gear checkout facts** — GEAR_USAGE rows with the checkout window
  *resolved* (buffer overrides falling back to the journal's event range,
  the same ``COALESCE`` the Snipe-IT check-in sweep uses) and a flag for an
  already-recorded ``snipeit_checkin``; ``is_currently_checked_out``
  (core_shared) applies the actual determination.
- **Template references** — one row per abseiling-derived journal whose
  consolidated ``abseiling_data.template_id`` is set; the service aggregates
  the per-template done-counts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core_shared.models.journals import (
    SUBTYPE_FACTS_FIELDS,
    EventDateRange,
    GearCheckoutFacts,
    OutdoorActivitySubtype,
    OutdoorActivityTypeFacts,
    TemplateReferenceFacts,
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

# Resolved checkout window: buffer overrides fall back to the journal's event
# range, mirroring the Snipe-IT worker's check-in sweep. ``ending_after``
# excludes already-ended windows as a cheap bound; the checked-out
# determination itself lives in ``is_currently_checked_out`` (core_shared).
_GEAR_CHECKOUT_QUERY = text(
    """
    SELECT
        j.id AS journal_id,
        g.id AS gear_item_id,
        g.name AS gear_name,
        COALESCE(u.checkout_date, j.event_date_range_start) AS checkout_date,
        COALESCE(u.checkin_date, j.event_date_range_end) AS checkin_date,
        (ci.id IS NOT NULL) AS snipeit_checked_in
    FROM journal_gear_usage_data u
    JOIN journals j ON j.id = u.journal_id
    JOIN gear_items g ON g.id = u.gear_item_id AND g.user_id = :user_id
    LEFT JOIN sync_metadata ci
        ON ci.integration_source = 'snipeit_checkin'
        AND ci.internal_uuid = CAST(j.id AS TEXT)
        AND ci.sync_status = 'success'
    WHERE j.user_id = :user_id
        AND COALESCE(u.checkin_date, j.event_date_range_end) > :ending_after
    """
)

_TEMPLATE_REFERENCES_QUERY = text(
    """
    SELECT
        j.id AS journal_id,
        t.id AS template_id,
        t.name AS template_name,
        t.template_type AS template_type
    FROM journal_abseiling_data abseiling
    JOIN journals j ON j.id = abseiling.journal_id
    JOIN activity_templates t ON t.id = abseiling.template_id
    WHERE j.user_id = :user_id
        AND t.user_id = :user_id
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

    async def list_gear_checkout_facts(
        self, user_id: str, *, ending_after: datetime
    ) -> list[GearCheckoutFacts]:
        """Gear-usage rows whose resolved check-in falls after ``ending_after``."""
        result = await self.connection.execute(
            _GEAR_CHECKOUT_QUERY,
            {"user_id": user_id, "ending_after": ending_after},
        )
        return [
            GearCheckoutFacts(
                journal_id=int(row["journal_id"]),
                gear_item_id=str(row["gear_item_id"]),
                gear_name=str(row["gear_name"]),
                checkout_date=row["checkout_date"],
                checkin_date=row["checkin_date"],
                snipeit_checked_in=bool(row["snipeit_checked_in"]),
            )
            for row in result.mappings()
        ]

    async def list_template_references(
        self, user_id: str
    ) -> list[TemplateReferenceFacts]:
        """One row per abseiling-derived journal referencing a template."""
        result = await self.connection.execute(
            _TEMPLATE_REFERENCES_QUERY, {"user_id": user_id}
        )
        return [
            TemplateReferenceFacts(
                journal_id=int(row["journal_id"]),
                template_id=str(row["template_id"]),
                template_name=str(row["template_name"]),
                template_type=str(row["template_type"]),
            )
            for row in result.mappings()
        ]

"""SQL implementation of JournalRepository."""

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalNotFoundError,
    JournalType,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.link_sources import (
    JOURNAL_LINK_SOURCES,
    SNIPEIT_MAINTENANCE_IMPORT_LINK,
    SNIPEIT_MAINTENANCE_NOT_IMPORTED,
)
from app.core.journal.adapters.sql.journal_touch import touch_journal
from app.core.journal.models.repositories import JournalRepository

# The type-data table behind every table-backed journal type. NOTE is the
# absence of any typed row; PHOTO_ALBUM is integration-managed (see below). Every
# type-detection and type-filter query in this module is generated from this
# single map, and tests/unit/journal/test_journal_type_coverage.py fails if a
# JournalType is missing from it.
TYPE_TABLES: dict[JournalType, str] = {
    JournalType.EVENT: "journal_calendar_info",
    JournalType.MOOD_RATING: "journal_mood_data",
    JournalType.PLAN: "journal_plan_data",
    JournalType.TRAVEL: "journal_travel_data",
    JournalType.FITNESS: "journal_fitness_data",
    JournalType.OUTDOOR_ACTIVITY: "journal_outdoor_activity_data",
    JournalType.BUSHWALKING: "journal_bushwalking_data",
    JournalType.JOGGING: "journal_jogging_data",
    JournalType.ABSEILING_TRIP: "journal_abseiling_data",
    JournalType.CANYONING: "journal_canyoning_data",
    JournalType.CLIMBING: "journal_climbing_data",
    JournalType.KAYAKING: "journal_kayaking_data",
    JournalType.CROSS_COUNTRY_SKIING: "journal_skiing_data",
    JournalType.CAVING: "journal_caving_data",
    JournalType.CANOEING: "journal_canoeing_data",
    JournalType.SNORKELLING: "journal_snorkelling_data",
    JournalType.DIVING: "journal_diving_data",
    JournalType.DOWNHILL_SKIING: "journal_downhill_skiing_data",
    JournalType.OUTDOOR_PLANNING: "journal_outdoor_planning_data",
    JournalType.OUTDOOR_TRAINING: "journal_outdoor_training_data",
    JournalType.GEAR_MAINTENANCE: "journal_gear_maintenance_data",
    JournalType.GEAR_USAGE: "journal_gear_usage_data",
}

# Type name (uppercase and lowercase) -> table, for callers passing strings.
_JOURNAL_TYPE_TABLE_MAP: dict[str, str] = {
    key: table
    for journal_type, table in TYPE_TABLES.items()
    for key in (journal_type.name, journal_type.value)
}


def _type_alias(journal_type: JournalType) -> str:
    """Stable SQL alias for a type-data table join."""
    return f"t_{journal_type.value}"


# PHOTO_ALBUM is integration-managed: a journal is a PHOTO_ALBUM when it has a
# sync_metadata row with integration_source='immich_album' (set by Immich album
# sync), rather than a row in a dedicated type-data table.
_IMMICH_ALBUM_SOURCE = "immich_album"


def _journal_link_sql(integration_source: str, *, by_external_id: bool) -> str | None:
    """UNION of every store for ``integration_source``, user-scoped.

    Each branch yields ``journal_id``; with ``by_external_id`` it is further
    restricted to rows whose exposed external id equals ``:external_id``.
    """
    source = JOURNAL_LINK_SOURCES.get(integration_source)
    if source is None:
        return None
    branches = []
    for store in source.stores:
        conditions = [store.where_sql] if store.where_sql else []
        conditions.append("j.user_id = :user_id")
        if by_external_id:
            conditions.append(f"{store.external_id_sql} = :external_id")
        branches.append(
            f"SELECT {store.journal_id_sql} AS journal_id FROM {store.from_sql} "
            f"WHERE {' AND '.join(conditions)}"
        )
    return " UNION ".join(branches)


_PHOTO_ALBUM_LEFT_JOIN = (
    "LEFT JOIN sync_metadata sm_pa "
    "ON sm_pa.internal_id = j.id "
    "AND sm_pa.integration_source = 'immich_album'"
)
_PHOTO_ALBUM_INNER_JOIN = (
    "INNER JOIN sync_metadata sm_pa "
    "ON sm_pa.internal_id = j.id "
    "AND sm_pa.integration_source = 'immich_album'"
)

# Type-detection projection: ``j.id AS journal_id`` followed by one column per
# type-data table holding the type name when its row exists (plus the
# PHOTO_ALBUM sync_metadata marker). Every type-detection query in the app —
# single journal, batch (logbook export), and search indexing — is built from
# this so no type can be missing from one of them.
TYPE_PROJECTION_SQL: str = (
    "SELECT j.id AS journal_id, "
    + ", ".join(
        [
            f"CASE WHEN {_type_alias(jt)}.journal_id IS NOT NULL "
            f"THEN '{jt.name}' END AS {_type_alias(jt)}_type"
            for jt in TYPE_TABLES
        ]
        + [
            "CASE WHEN sm_pa.internal_id IS NOT NULL THEN 'PHOTO_ALBUM' END AS photo_type"
        ]
    )
    + " FROM journals j "
    + " ".join(
        f"LEFT JOIN {table} {_type_alias(jt)} ON j.id = {_type_alias(jt)}.journal_id"
        for jt, table in TYPE_TABLES.items()
    )
    + f" {_PHOTO_ALBUM_LEFT_JOIN}"
)
GET_TYPES_SQL: str = TYPE_PROJECTION_SQL + " WHERE j.id = :journal_id"
GET_TYPES_BATCH_SQL: str = TYPE_PROJECTION_SQL + " WHERE j.id = ANY(:journal_ids)"


def type_names_from_projection_row(row: Any) -> list[str]:
    """Type names present in a ``TYPE_PROJECTION_SQL`` row (column 0 is the id)."""
    return [value for value in tuple(row)[1:] if value]


@dataclass(frozen=True)
class _JournalFilterSql:
    """The JOIN/WHERE fragments and bound parameters for one filtered query.

    Built once by :meth:`SqlJournalRepository._build_journal_filters` and shared
    by every query over the journal list filters, so the rows, the count and the
    id set can never drift apart.
    """

    joins: list[str]
    where_clauses: list[str]
    params: dict[str, Any]
    needs_distinct: bool
    matches_nothing: bool
    """The caller asked for an explicitly empty candidate id set, which no SQL
    can satisfy; each caller returns its own empty value rather than querying."""

    def assemble(self, select_from: str) -> str:
        """Append this filter's joins and WHERE clause to a SELECT ... FROM."""
        sql = select_from
        if self.joins:
            sql += "\n" + "\n".join(self.joins)
        return sql + "\nWHERE " + " AND ".join(self.where_clauses)


class SqlJournalRepository(JournalRepository):
    """SQL implementation of JournalRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_journal(self, row: Any) -> Journal:
        """Convert a database row to a Journal entity."""
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
            order=row.order,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _build_type_filter_joins(
        self, journal_type: str | None
    ) -> tuple[list[str], list[str]]:
        """Build JOIN clauses and WHERE conditions for journal type filtering.

        Args:
            journal_type: The journal type to filter by (e.g., "MOOD_RATING", "NOTE")

        Returns:
            Tuple of (joins, where_clauses) to add to the query
        """
        joins: list[str] = []
        where_clauses: list[str] = []

        if not journal_type:
            return joins, where_clauses

        # Handle NOTE type - journals with no type-specific data
        if journal_type.upper() == "NOTE":
            for jt, table in TYPE_TABLES.items():
                alias = _type_alias(jt)
                joins.append(f"LEFT JOIN {table} {alias} ON j.id = {alias}.journal_id")
                where_clauses.append(f"{alias}.journal_id IS NULL")
            joins.append(_PHOTO_ALBUM_LEFT_JOIN)
            where_clauses.append("sm_pa.internal_id IS NULL")
            return joins, where_clauses

        # PHOTO_ALBUM is integration-managed (Immich albums): filter via a
        # sync_metadata join rather than a dedicated type-data table.
        if journal_type.upper() == "PHOTO_ALBUM":
            joins.append(_PHOTO_ALBUM_INNER_JOIN)
            return joins, where_clauses

        # Handle other types with explicit table mapping
        if journal_type not in _JOURNAL_TYPE_TABLE_MAP:
            return joins, where_clauses

        type_table = _JOURNAL_TYPE_TABLE_MAP[journal_type]
        join_clause = self._get_type_table_join(type_table)
        if join_clause:
            joins.append(join_clause)

        return joins, where_clauses

    def _get_type_table_join(self, type_table: str) -> str:
        """Get the JOIN clause for a specific type table.

        Args:
            type_table: The table name to join

        Returns:
            The JOIN clause string

        Raises:
            ValueError: If the table name is not supported
        """
        if type_table not in TYPE_TABLES.values():
            msg = f"Unsupported table name: {type_table}"
            raise ValueError(msg)

        return f"INNER JOIN {type_table} t ON j.id = t.journal_id"

    def _add_relationship_filters(
        self,
        joins: list[str],
        where_clauses: list[str],
        params: dict[str, Any],
        contact_id: str | None,
        tag_ids: list[str] | None,
        calendar_id: str | None,
        journal_type: str | None,
    ) -> bool:
        """Add JOIN and WHERE clauses for relationship filters.

        Args:
            joins: List to append JOIN clauses to
            where_clauses: List to append WHERE conditions to
            params: Dictionary to add query parameters to
            contact_id: Optional contact ID filter
            tag_ids: Optional tag IDs to filter by (matches any of them)
            calendar_id: Optional calendar ID filter
            journal_type: Optional journal type (affects calendar join logic)

        Returns:
            True if DISTINCT is needed (due to many-to-many relationships)
        """
        needs_distinct = False

        # Contact filter (many-to-many relationship)
        if contact_id is not None:
            joins.append(
                "INNER JOIN journal_contact_relationships jcr ON j.id = jcr.journal_id"
            )
            where_clauses.append("jcr.contact_id = :contact_id")
            params["contact_id"] = int(contact_id)
            needs_distinct = True

        # Tag filter (many-to-many relationship). Multiple tags combine as a
        # logical OR over a single JOIN, matching the contacts list filter.
        if tag_ids:
            joins.append(
                "INNER JOIN journal_tag_assignments jta ON j.id = jta.journal_id"
            )
            placeholders = []
            for tag_index, tag_id_value in enumerate(tag_ids):
                param_name = f"tag_id_param_{tag_index}"
                placeholders.append(f":{param_name}")
                params[param_name] = tag_id_value
            where_clauses.append(f"jta.tag_id IN ({', '.join(placeholders)})")
            needs_distinct = True

        # Calendar filter.
        #
        # A calendar holds a journal either by being the one it is displayed
        # in (journal_calendar_info) or by holding the same event under its
        # own external link — which is how a de-duplicated event appears in
        # both the calendar that invited and the one that was invited.
        # Matching only the former would make a shared event vanish from
        # every calendar but the first one to sync it.
        #
        # EXISTS rather than a join: a journal linked to two calendars would
        # otherwise come back once per link, and the filter must not change
        # how many rows a journal contributes.
        if calendar_id is not None:
            calendar_holds_journal = """(
                EXISTS (
                    SELECT 1 FROM journal_calendar_info jci_cal
                    WHERE jci_cal.journal_id = j.id
                      AND jci_cal.calendar_id = :calendar_id
                )
                OR EXISTS (
                    SELECT 1 FROM journal_external_event_links jeel_cal
                    WHERE jeel_cal.journal_id = j.id
                      AND jeel_cal.calendar_id = :calendar_id
                      AND jeel_cal.sync_status <> 'cancelled'
                )
            )"""
            if not (journal_type and journal_type.upper() == "EVENT"):
                where_clauses.append(calendar_holds_journal)
            else:
                where_clauses.append(
                    f"(t.calendar_id = :calendar_id OR {calendar_holds_journal})"
                )
            params["calendar_id"] = calendar_id

        return needs_distinct

    def _build_journal_filters(
        self,
        *,
        user_id: str,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_ids: list[str] | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
        journal_ids: list[int] | None = None,
    ) -> _JournalFilterSql:
        """Build the JOIN/WHERE fragments shared by every filtered journal query.

        ``get_all``, ``count_all`` and ``find_ids_by_filters`` differ only in
        what they project, so the filter logic lives here once.
        """
        joins: list[str] = []
        where_clauses: list[str] = ["j.user_id = :user_id"]
        params: dict[str, Any] = {"user_id": user_id}

        type_joins, type_where = self._build_type_filter_joins(journal_type)
        joins.extend(type_joins)
        where_clauses.extend(type_where)

        needs_distinct = self._add_relationship_filters(
            joins, where_clauses, params, contact_id, tag_ids, calendar_id, journal_type
        )

        self._add_date_filters(where_clauses, params, start_date, end_date)

        if parent_id is not None:
            where_clauses.append("j.parent_id = :parent_id")
            params["parent_id"] = parent_id

        if search is not None:
            where_clauses.append("(j.title ILIKE :search OR j.content ILIKE :search)")
            params["search"] = f"%{search}%"

        matches_nothing = False
        if journal_ids is not None:
            if journal_ids:
                where_clauses.append("j.id = ANY(:journal_ids)")
                params["journal_ids"] = journal_ids
            else:
                matches_nothing = True

        return _JournalFilterSql(
            joins=joins,
            where_clauses=where_clauses,
            params=params,
            needs_distinct=needs_distinct,
            matches_nothing=matches_nothing,
        )

    def _add_date_filters(
        self,
        where_clauses: list[str],
        params: dict[str, Any],
        start_date: str | None,
        end_date: str | None,
    ) -> None:
        """Add date range filter conditions.

        Args:
            where_clauses: List to append WHERE conditions to
            params: Dictionary to add query parameters to
            start_date: Optional start date (ISO format)
            end_date: Optional end date (ISO format)
        """
        if start_date is not None:
            where_clauses.append("j.event_date_range_end >= :start_date")
            dt = datetime.fromisoformat(start_date)
            params["start_date"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)

        if end_date is not None:
            where_clauses.append("j.event_date_range_start <= :end_date")
            dt = datetime.fromisoformat(end_date)
            # If the user only provided a date (no time component), include the entire day up to 23:59:59.999
            if "T" not in end_date:
                dt = datetime.combine(dt.date(), time(23, 59, 59, 999999))
            params["end_date"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    async def find_by_id(self, journal_id: int) -> Journal | None:
        """Find a journal by ID, **without** scoping it to an owner.

        For callers that have no acting user — integration workers and stream
        consumers. Anything serving a request on a user's behalf wants
        :meth:`find_by_id_for_user` instead; see the port for why.
        """
        query = text(
            """
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM journals
            WHERE id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_journal(row)

    async def find_by_id_for_user(
        self, journal_id: int, user_id: str
    ) -> Journal | None:
        """Find a journal by ID, scoped to its owner.

        The ``user_id`` predicate lives in the statement rather than in a
        comparison above it, so a caller cannot hold the journal before deciding
        whether it was allowed to — the ``TaskRepository`` stance, and what
        issue #1267 was: eleven endpoints that read first and never compared.
        """
        query = text(
            """
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM journals
            WHERE id = :journal_id AND user_id = :user_id
            """
        )
        result = await self.conn.execute(
            query, {"journal_id": journal_id, "user_id": user_id}
        )
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_journal(row)

    async def touch(self, journal_id: int) -> None:
        """Record that a journal changed; see the port for why."""
        await touch_journal(self.conn, journal_id)

    async def lock_and_get_updated_at(self, journal_id: int) -> datetime | None:
        """Lock the journal row and return its last-write timestamp.

        ``FOR UPDATE`` rather than a plain read: see the port for the
        lost-update window this closes.
        """
        query = text(
            """
            SELECT updated_at
            FROM journals
            WHERE id = :journal_id
            FOR UPDATE
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        return row.updated_at if row else None

    async def get_types(self, journal_id: int) -> list[str]:
        """Get the types of a journal."""
        query = text(GET_TYPES_SQL)
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return []

        return ["NOTE", *type_names_from_projection_row(row)]

    async def get_concrete_types(self, journal_id: int) -> list[str]:
        """Types as the read paths report them: NOTE only when nothing else is.

        :meth:`get_types` always leads with NOTE (every journal can act as a
        note); the MCP/API read paths and the ``types`` search filter instead
        treat NOTE as the absence of typed rows. The search index uses this
        form so ``types=NOTE`` means the same thing with or without a query.
        """
        result = await self.conn.execute(
            text(GET_TYPES_SQL), {"journal_id": journal_id}
        )
        row = result.fetchone()
        if not row:
            return []
        return type_names_from_projection_row(row) or ["NOTE"]

    async def find_overlapping_for_user(
        self,
        user_id: str,
        *,
        exclude_journal_id: int,
        date_range: EventDateRange,
        limit: int,
    ) -> list[Journal]:
        """The user's other journals overlapping ``date_range``, by event start."""
        query = text(
            """
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM journals
            WHERE user_id = :user_id
              AND id != :journal_id
              AND event_date_range_start <= :end_date
              AND event_date_range_end >= :start_date
            ORDER BY event_date_range_start
            LIMIT :limit
            """
        )
        result = await self.conn.execute(
            query,
            {
                "user_id": user_id,
                "journal_id": exclude_journal_id,
                "start_date": date_range.start,
                "end_date": date_range.end,
                "limit": limit,
            },
        )
        return [self._row_to_journal(row) for row in result.fetchall()]

    async def find_by_ids_for_user(
        self, user_id: str, journal_ids: list[int]
    ) -> list[Journal]:
        """Find journals by IDs, scoped to a user."""
        if not journal_ids:
            return []

        query = text(
            """
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM journals
            WHERE user_id = :user_id AND id = ANY(:journal_ids)
            """
        )
        result = await self.conn.execute(
            query, {"user_id": user_id, "journal_ids": journal_ids}
        )
        return [self._row_to_journal(row) for row in result.fetchall()]

    async def find_and_lock_by_ids_for_user(
        self, user_id: str, journal_ids: list[int]
    ) -> list[Journal]:
        """Lock the user's journals among ``journal_ids``, low to high, and return them.

        One statement per id rather than one ``id = ANY(...)`` over the lot: a
        row lock is not promised in the order a query returns its rows, so a
        single statement would leave the acquisition order to the plan and the
        ordering claim would be intended rather than true. Ascending id is the
        order ``SqlTaskAnchorRepository._lock_journals`` uses, and agreeing with
        it is the whole point — see the port for what the two operations were
        deadlocking over.

        ``FOR KEY SHARE`` and the owner predicate both sit in the statement, so a
        journal belonging to somebody else is not locked and not returned.
        """
        query = text(
            """
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM journals
            WHERE id = :journal_id AND user_id = :user_id
            FOR KEY SHARE
            """
        )
        locked: list[Journal] = []
        for journal_id in sorted(set(journal_ids)):
            result = await self.conn.execute(
                query, {"journal_id": journal_id, "user_id": user_id}
            )
            row = result.fetchone()
            if row is not None:
                locked.append(self._row_to_journal(row))
        return locked

    async def get_by_ids_for_user(
        self,
        user_id: str,
        journal_ids: list[int],
        limit: int = 100,
        offset: int = 0,
    ) -> list[Journal]:
        """Get journals by IDs for a user with ordering + pagination."""
        if not journal_ids:
            return []

        query = text(
            """
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM journals
            WHERE user_id = :user_id AND id = ANY(:journal_ids)
            ORDER BY event_date_range_start DESC, created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )
        result = await self.conn.execute(
            query,
            {
                "user_id": user_id,
                "journal_ids": journal_ids,
                "limit": limit,
                "offset": offset,
            },
        )
        return [self._row_to_journal(row) for row in result.fetchall()]

    async def count_by_ids_for_user(self, user_id: str, journal_ids: list[int]) -> int:
        """Count journals by IDs for a user."""
        if not journal_ids:
            return 0

        query = text(
            """
            SELECT COUNT(*) as count
            FROM journals
            WHERE user_id = :user_id AND id = ANY(:journal_ids)
            """
        )
        result = await self.conn.execute(
            query, {"user_id": user_id, "journal_ids": journal_ids}
        )
        row = result.fetchone()
        if row is None:
            return 0
        return int(row[0] or 0)

    async def count_children_for_parents(
        self, user_id: str, parent_ids: list[int]
    ) -> dict[int, int]:
        """Count direct children for each parent journal ID for a user."""
        if not parent_ids:
            return {}

        query = text(
            """
            SELECT parent_id, COUNT(*) as count
            FROM journals
            WHERE user_id = :user_id AND parent_id = ANY(:parent_ids)
            GROUP BY parent_id
            """
        )
        result = await self.conn.execute(
            query, {"user_id": user_id, "parent_ids": parent_ids}
        )

        counts: dict[int, int] = {}
        for row in result.fetchall():
            # row.parent_id / row.count may not be attribute-accessible depending on driver
            parent_id = int(row[0])
            count_value = int(row[1] or 0)
            counts[parent_id] = count_value
        return counts

    async def find_descendants_for_user(
        self,
        user_id: str,
        ancestor_ids: list[int],
        max_depth: int = 5,
    ) -> list[Journal]:
        """Find all descendants of the given ancestor journals for a user.

        Uses a recursive CTE and is tenant-safe via user_id filtering.
        """
        if not ancestor_ids:
            return []

        query = text(
            """
            WITH RECURSIVE descendants AS (
                -- Base case: direct children of the provided ancestors
                SELECT j.id, j.user_id, j.title, j.content,
                       j.event_date_range_start, j.event_date_range_end,
                       j.parent_id, j."order", j.created_at, j.updated_at,
                       1 as depth
                FROM journals j
                WHERE j.user_id = :user_id AND j.parent_id = ANY(:ancestor_ids)

                UNION ALL

                -- Recursive case: children of already-found descendants
                SELECT j.id, j.user_id, j.title, j.content,
                       j.event_date_range_start, j.event_date_range_end,
                       j.parent_id, j."order", j.created_at, j.updated_at,
                       d.depth + 1 as depth
                FROM journals j
                JOIN descendants d ON j.parent_id = d.id
                WHERE j.user_id = :user_id AND d.depth < :max_depth
            )
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM descendants
            """
        )

        result = await self.conn.execute(
            query,
            {
                "user_id": user_id,
                "ancestor_ids": ancestor_ids,
                "max_depth": max_depth,
            },
        )
        return [self._row_to_journal(row) for row in result.fetchall()]

    async def save(self, journal: Journal) -> Journal:
        """Save a journal (insert or update)."""
        if journal.id is None:
            return await self._insert(journal)
        else:
            return await self._update(journal)

    async def _insert(self, journal: Journal) -> Journal:
        """Insert a new journal."""
        query = text(
            """
            INSERT INTO journals (
                user_id, title, content,
                event_date_range_start, event_date_range_end,
                parent_id, "order"
            )
            VALUES (
                :user_id, :title, :content,
                :start, :end,
                :parent_id, :order
            )
            RETURNING id, user_id, title, content,
                      event_date_range_start, event_date_range_end,
                      parent_id, "order", created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "user_id": journal.user_id,
                "title": journal.title,
                "content": journal.content,
                "start": journal.event_date_range.start,
                "end": journal.event_date_range.end,
                "parent_id": journal.parent_id,
                "order": journal.order,
            },
        )
        row = result.fetchone()
        return self._row_to_journal(row)

    async def _update(self, journal: Journal) -> Journal:
        """Update an existing journal."""
        query = text(
            """
            UPDATE journals
            SET user_id = :user_id,
                title = :title,
                content = :content,
                event_date_range_start = :start,
                event_date_range_end = :end,
                parent_id = :parent_id,
                "order" = :order,
                updated_at = now()
            WHERE id = :id
            RETURNING id, user_id, title, content,
                      event_date_range_start, event_date_range_end,
                      parent_id, "order", created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "id": journal.id,
                "user_id": journal.user_id,
                "title": journal.title,
                "content": journal.content,
                "start": journal.event_date_range.start,
                "end": journal.event_date_range.end,
                "parent_id": journal.parent_id,
                "order": journal.order,
            },
        )
        row = result.fetchone()

        if not row:
            # Journal ID must be set for update operations
            assert journal.id is not None, "Journal ID must be set for update"
            raise JournalNotFoundError(journal.id)

        return self._row_to_journal(row)

    async def delete(self, journal_id: int) -> None:
        """Delete a journal by ID."""
        query = text("DELETE FROM journals WHERE id = :journal_id")
        result = await self.conn.execute(query, {"journal_id": journal_id})

        if result.rowcount == 0:
            raise JournalNotFoundError(journal_id)

    async def get_children(self, parent_id: int) -> list[Journal]:
        """Get child journals of a parent, ordered by date then order field."""
        query = text(
            """
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM journals
            WHERE parent_id = :parent_id
            ORDER BY event_date_range_start ASC, "order" ASC NULLS LAST
            """
        )
        result = await self.conn.execute(query, {"parent_id": parent_id})
        return [self._row_to_journal(row) for row in result.fetchall()]

    async def get_ancestors(self, journal_id: int) -> list[Journal]:
        """Get all ancestor journals from parent to root using recursive CTE."""
        query = text(
            """
            WITH RECURSIVE ancestors AS (
                -- Base case: get the parent of the given journal
                SELECT j.id, j.user_id, j.title, j.content,
                       j.event_date_range_start, j.event_date_range_end,
                       j.parent_id, j."order", j.created_at, j.updated_at,
                       1 as depth
                FROM journals j
                WHERE j.id = (SELECT parent_id FROM journals WHERE id = :journal_id)

                UNION ALL

                -- Recursive case: get parent of current ancestor
                SELECT j.id, j.user_id, j.title, j.content,
                       j.event_date_range_start, j.event_date_range_end,
                       j.parent_id, j."order", j.created_at, j.updated_at,
                       a.depth + 1
                FROM journals j
                INNER JOIN ancestors a ON j.id = a.parent_id
            )
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM ancestors
            ORDER BY depth ASC
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        return [self._row_to_journal(row) for row in result.fetchall()]

    async def get_depth(self, journal_id: int) -> int:
        """Get the depth of a journal in the hierarchy (1 for root)."""
        query = text(
            """
            WITH RECURSIVE ancestors AS (
                -- Base case: start with the journal itself
                SELECT id, parent_id, 1 as depth
                FROM journals
                WHERE id = :journal_id

                UNION ALL

                -- Recursive case: go up to parent
                SELECT j.id, j.parent_id, a.depth + 1
                FROM journals j
                INNER JOIN ancestors a ON j.id = a.parent_id
            )
            SELECT MAX(depth) as max_depth FROM ancestors
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()
        return row.max_depth if row and row.max_depth else 0

    async def get_depth_bulk(self, journal_ids: list[int]) -> dict[int, int]:
        """Get the depth of multiple journals in the hierarchy (1 for root)."""
        if not journal_ids:
            return {}

        query = text(
            """
            WITH RECURSIVE ancestors AS (
                -- Base case: start with the journals
                SELECT id as origin_id, id, parent_id, 1 as depth
                FROM journals
                WHERE id = ANY(:journal_ids)

                UNION ALL

                -- Recursive case: go up to parent
                SELECT a.origin_id, j.id, j.parent_id, a.depth + 1
                FROM journals j
                INNER JOIN ancestors a ON j.id = a.parent_id
            )
            SELECT origin_id, MAX(depth) as max_depth
            FROM ancestors
            GROUP BY origin_id
            """
        )
        result = await self.conn.execute(query, {"journal_ids": journal_ids})
        rows = result.fetchall()
        return {row.origin_id: row.max_depth for row in rows}

    async def get_all(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_ids: list[str] | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
        journal_ids: list[int] | None = None,
    ) -> list[Journal]:
        """Get all journals for a user with pagination and filtering.

        Args:
            user_id: The user ID to filter by
            limit: Maximum number of journals to return
            offset: Number of journals to skip
            journal_type: Optional journal type to filter by (e.g., "MOOD_RATING", "EVENT")
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)
            contact_id: Optional contact ID to filter journals by
            tag_ids: Optional tag IDs to filter journals by (matches any of them)
            calendar_id: Optional calendar ID to filter journals by
            parent_id: Optional parent journal ID to filter by (None for root journals)
            search: Optional search query for full-text search

        Returns:
            List of journals matching the filter criteria
        """
        filters = self._build_journal_filters(
            user_id=user_id,
            journal_type=journal_type,
            start_date=start_date,
            end_date=end_date,
            contact_id=contact_id,
            tag_ids=tag_ids,
            calendar_id=calendar_id,
            parent_id=parent_id,
            search=search,
            journal_ids=journal_ids,
        )
        if filters.matches_nothing:
            return []

        distinct_keyword = "DISTINCT " if filters.needs_distinct else ""
        base_query = filters.assemble(
            f"""
            SELECT {distinct_keyword}j.id, j.user_id, j.title, j.content,
                   j.event_date_range_start, j.event_date_range_end,
                   j.parent_id, j."order", j.created_at, j.updated_at
            FROM journals j
        """
        )
        base_query += "\nORDER BY j.event_date_range_start DESC, j.created_at DESC"
        base_query += "\nLIMIT :limit OFFSET :offset"

        query = text(base_query)
        result = await self.conn.execute(
            query, {**filters.params, "limit": limit, "offset": offset}
        )
        return [self._row_to_journal(row) for row in result.fetchall()]

    async def count_all(
        self,
        user_id: str,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_ids: list[str] | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
        journal_ids: list[int] | None = None,
    ) -> int:
        """Count journals for a user with filtering.

        Uses the same filter logic as get_all() but returns only the count.
        This is more efficient than fetching all records when only the count is needed.

        Args:
            user_id: The user ID to filter by
            journal_type: Optional journal type to filter by
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)
            contact_id: Optional contact ID to filter journals by
            tag_ids: Optional tag IDs to filter journals by (matches any of them)
            calendar_id: Optional calendar ID to filter journals by
            parent_id: Optional parent journal ID to filter by
            search: Optional search query for full-text search

        Returns:
            Count of journals matching the filter criteria
        """
        filters = self._build_journal_filters(
            user_id=user_id,
            journal_type=journal_type,
            start_date=start_date,
            end_date=end_date,
            contact_id=contact_id,
            tag_ids=tag_ids,
            calendar_id=calendar_id,
            parent_id=parent_id,
            search=search,
            journal_ids=journal_ids,
        )
        if filters.matches_nothing:
            return 0

        query = text(
            filters.assemble("""
            SELECT COUNT(DISTINCT j.id)
            FROM journals j
        """)
        )
        result = await self.conn.execute(query, filters.params)
        row = result.fetchone()
        if row is None:
            return 0
        count_value = row[0]
        return int(count_value) if count_value is not None else 0

    async def find_ids_by_filters(
        self,
        user_id: str,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_ids: list[str] | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
        journal_ids: list[int] | None = None,
    ) -> set[int]:
        """Ids of the user's journals matching the same filters as :meth:`get_all`.

        For callers that need the filters as a *set to intersect with* rather
        than as rows: MCP ``search_journals`` resolves the relational filters
        here and hands the ids to MeiliSearch as an ``id IN [...]`` filter,
        because Meili indexes the event dates as ISO strings and its range
        operators are numeric-only. Unpaginated by design — the whole matching
        set is the point — so keep the filters narrow.

        Args:
            user_id: The user ID to filter by
            journal_type: Optional journal type to filter by
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)
            contact_id: Optional contact ID to filter journals by
            tag_ids: Optional tag IDs to filter journals by (matches any of them)
            calendar_id: Optional calendar ID to filter journals by
            parent_id: Optional parent journal ID to filter by
            search: Optional search query for full-text search
            journal_ids: Optional candidate ids to intersect with

        Returns:
            The ids of every journal matching the filter criteria
        """
        filters = self._build_journal_filters(
            user_id=user_id,
            journal_type=journal_type,
            start_date=start_date,
            end_date=end_date,
            contact_id=contact_id,
            tag_ids=tag_ids,
            calendar_id=calendar_id,
            parent_id=parent_id,
            search=search,
            journal_ids=journal_ids,
        )
        if filters.matches_nothing:
            return set()

        query = text(
            filters.assemble("""
            SELECT DISTINCT j.id
            FROM journals j
        """)
        )
        result = await self.conn.execute(query, filters.params)
        return {int(row[0]) for row in result}

    async def get_root_journals(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        """Get root journals (no parent) for a user."""
        query = text(
            """
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM journals
            WHERE user_id = :user_id AND parent_id IS NULL
            ORDER BY event_date_range_start DESC, created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )
        result = await self.conn.execute(
            query, {"user_id": user_id, "limit": limit, "offset": offset}
        )
        return [self._row_to_journal(row) for row in result.fetchall()]

    async def count_by_user(self, user_id: str) -> int:
        """Count total journals for a user."""
        query = text(
            """
            SELECT COUNT(*) as count FROM journals WHERE user_id = :user_id
            """
        )
        result = await self.conn.execute(query, {"user_id": user_id})
        row = result.fetchone()
        if row is None:
            return 0
        # row.count is a Callable-like object in SQLAlchemy
        # We need to access it safely
        count_value = row[0]  # Access by index instead of attribute
        return int(count_value) if count_value is not None else 0

    async def get_external_event_links(self, journal_id: int) -> list[dict[str, Any]]:
        """Get Google Calendar external event links for a journal."""
        query = text(
            "SELECT l.external_event_id, c.google_calendar_id, l.calendar_id "
            "FROM journal_external_event_links l "
            "LEFT JOIN calendars c ON l.calendar_id = c.id "
            "WHERE l.journal_id = :journal_id"
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        links = []
        for row in result.fetchall():
            links.append(
                {
                    "external_event_id": row[0],
                    "calendar_id": str(row[1]) if row[1] else None,
                    "internal_calendar_id": str(row[2]) if row[2] else None,
                }
            )
        return links

    async def find_ids_by_integration_source(
        self, user_id: str, integration_source: str
    ) -> set[int]:
        """Ids of the user's journals linked to ``integration_source``.

        Built from :data:`JOURNAL_LINK_SOURCES`; every store is scoped to
        ``user_id`` so a count of the result never leaks another user's links.
        """
        sql = _journal_link_sql(integration_source, by_external_id=False)
        if sql is None:
            return set()
        result = await self.conn.execute(text(sql), {"user_id": user_id})
        return {int(row[0]) for row in result}

    async def find_id_by_external_id(
        self, user_id: str, integration_source: str, external_id: str
    ) -> int | None:
        """The user's journal linked to ``(integration_source, external_id)``.

        The id is matched as the journal's external links expose it (see the
        store definitions in :data:`JOURNAL_LINK_SOURCES`).
        """
        sql = _journal_link_sql(integration_source, by_external_id=True)
        if sql is None:
            return None
        result = await self.conn.execute(
            text(f"{sql} ORDER BY journal_id LIMIT 1"),
            {"user_id": user_id, "external_id": external_id},
        )
        row = result.fetchone()
        return int(row[0]) if row and row[0] is not None else None

    async def get_snipeit_links(
        self, journal_id: int, user_id: str
    ) -> list[dict[str, Any]]:
        """Get Snipe-IT external links for a journal."""
        snipeit_links = []

        # Maintenance links: an imported journal's import link, otherwise the
        # push rows of a journal a user wrote (see SNIPEIT_MAINTENANCE_NOT_IMPORTED)
        snipeit_maintenance_query = await self.conn.execute(
            text(
                f"""
                SELECT 'snipeit_maintenance' AS integration_source, l.external_event_id, s.base_url
                FROM {SNIPEIT_MAINTENANCE_IMPORT_LINK}
                JOIN snipeit_settings s ON s.user_id = :user_id
                WHERE l.journal_id = :journal_id
                UNION ALL
                SELECT 'snipeit_maintenance' AS integration_source, m.external_id, s.base_url
                FROM sync_metadata m
                JOIN journals j ON j.id = :journal_id
                JOIN snipeit_settings s ON s.user_id = :user_id
                WHERE m.internal_uuid = :journal_uuid
                AND m.integration_source = 'snipeit_maintenance'
                AND {SNIPEIT_MAINTENANCE_NOT_IMPORTED}
                """  # noqa: S608 - interpolates only a module constant
            ),
            {
                "journal_id": journal_id,
                "journal_uuid": str(journal_id),
                "user_id": user_id,
            },
        )
        for row in snipeit_maintenance_query.fetchall():
            snipeit_links.append(
                {
                    "integration_source": row[0],
                    "external_id": row[1],
                    "base_url": row[2],
                }
            )

        # Checkout/Usage links
        snipeit_checkout_query = await self.conn.execute(
            text(
                """
                SELECT 'snipeit' AS integration_source, m_asset.external_id, s.base_url
                FROM sync_metadata m_checkout
                JOIN journal_gear_usage_data gud ON gud.journal_id = :journal_id
                JOIN sync_metadata m_asset ON m_asset.internal_uuid = CAST(gud.gear_item_id AS VARCHAR)
                    AND m_asset.integration_source = 'snipeit'
                JOIN snipeit_settings s ON s.user_id = :user_id
                WHERE m_checkout.internal_uuid = :journal_uuid
                AND m_checkout.integration_source = 'snipeit_checkout'
                """
            ),
            {
                "journal_id": journal_id,
                "journal_uuid": str(journal_id),
                "user_id": user_id,
            },
        )
        for row in snipeit_checkout_query.fetchall():
            snipeit_links.append(
                {
                    "integration_source": row[0],
                    "external_id": row[1],
                    "base_url": row[2],
                }
            )

        return snipeit_links

    async def get_strava_activity_ids(self, journal_id: int) -> list[str]:
        """Get every Strava activity linked to a journal, oldest link first.

        A journal usually has one, but an additive fitness merge leaves it with
        several: two activities making up one outing both stay linked to the
        survivor. Only one of them fits in ``journal_fitness_data``, so the
        canonical ``sync_metadata`` link store is the source of truth here, with
        the fitness column folded in for activities imported before sync
        metadata was recorded for them.
        """
        result = await self.conn.execute(
            text(
                """
                SELECT external_id, created_at
                FROM sync_metadata
                WHERE integration_source = 'strava'
                  AND internal_entity_type = 'journal'
                  AND internal_id = :journal_id
                UNION
                SELECT strava_activity_id, created_at
                FROM journal_fitness_data
                WHERE journal_id = :journal_id
                  AND strava_activity_id IS NOT NULL
                ORDER BY created_at, external_id
                """
            ),
            {"journal_id": journal_id},
        )
        # UNION already drops the duplicate when both stores name the same
        # activity with the same timestamp; dedupe again for differing ones.
        activity_ids: list[str] = []
        for row in result:
            if row[0] not in activity_ids:
                activity_ids.append(row[0])
        return activity_ids

    async def get_immich_album_links(self, journal_id: int) -> list[dict[str, Any]]:
        """Get Immich album links for a journal.

        Returns one entry per linked Immich album with the album UUID and the
        public shared-link URL (when one has been created). The album URL itself
        is built by the external-link helper from the user's Immich server URL.

        Delegates to ``AlbumSyncReadRepository``, which owns all SQL for the
        album ``external_references`` link and its reference_data decoding.
        """
        from app.core.journal.adapters.sql.album_sync_read_repository import (
            AlbumSyncReadRepository,
        )

        return await AlbumSyncReadRepository(self.conn).find_external_links(journal_id)

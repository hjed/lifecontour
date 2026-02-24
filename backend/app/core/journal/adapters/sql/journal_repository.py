"""SQL implementation of JournalRepository."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.entities import Journal
from app.core.journal.models.exceptions import JournalNotFoundError
from app.core.journal.models.repositories import JournalRepository
from app.core.journal.models.value_objects import EventDateRange

# Module-level constant for journal type to table mapping
# Supports both uppercase (MOOD_RATING) and lowercase (mood_rating) type names
_JOURNAL_TYPE_TABLE_MAP = {
    "MOOD_RATING": "journal_mood_data",
    "mood_rating": "journal_mood_data",
    "EVENT": "journal_calendar_info",
    "event": "journal_calendar_info",
    "PLAN": "journal_plan_data",
    "plan": "journal_plan_data",
    "TRAVEL": "journal_travel_data",
    "travel": "journal_travel_data",
    "PHOTO_ALBUM": "journal_photo_album_data",
    "photo_album": "journal_photo_album_data",
    "FITNESS": "journal_fitness_data",
    "fitness": "journal_fitness_data",
    "OUTDOOR_ACTIVITY": "journal_outdoor_activity_data",
    "outdoor_activity": "journal_outdoor_activity_data",
    "BUSHWALKING": "journal_bushwalking_data",
    "bushwalking": "journal_bushwalking_data",
    "JOGGING": "journal_jogging_data",
    "jogging": "journal_jogging_data",
    "ABSEILING_TRIP": "journal_abseiling_data",
    "abseiling_trip": "journal_abseiling_data",
    "CANYONING": "journal_canyoning_data",
    "canyoning": "journal_canyoning_data",
    "CLIMBING": "journal_climbing_data",
    "climbing": "journal_climbing_data",
    "KAYAKING": "journal_kayaking_data",
    "kayaking": "journal_kayaking_data",
    "CROSS_COUNTRY_SKIING": "journal_skiing_data",
    "cross_country_skiing": "journal_skiing_data",
}


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
        if journal_type.upper() in ("NOTE", "note"):
            joins.extend(
                [
                    "LEFT JOIN journal_calendar_info jci ON j.id = jci.journal_id",
                    "LEFT JOIN journal_mood_data jmd ON j.id = jmd.journal_id",
                    "LEFT JOIN journal_plan_data jpd ON j.id = jpd.journal_id",
                    "LEFT JOIN journal_travel_data jtd ON j.id = jtd.journal_id",
                    "LEFT JOIN journal_photo_album_data jpad ON j.id = jpad.journal_id",
                    "LEFT JOIN journal_fitness_data jfd ON j.id = jfd.journal_id",
                    "LEFT JOIN journal_outdoor_activity_data joad ON j.id = joad.journal_id",
                    "LEFT JOIN journal_bushwalking_data jbwd ON j.id = jbwd.journal_id",
                    "LEFT JOIN journal_jogging_data jjd ON j.id = jjd.journal_id",
                    "LEFT JOIN journal_abseiling_data jabd ON j.id = jabd.journal_id",
                    "LEFT JOIN journal_canyoning_data jcyd ON j.id = jcyd.journal_id",
                    "LEFT JOIN journal_climbing_data jcld ON j.id = jcld.journal_id",
                    "LEFT JOIN journal_kayaking_data jkyd ON j.id = jkyd.journal_id",
                    "LEFT JOIN journal_skiing_data jskid ON j.id = jskid.journal_id",
                ]
            )
            where_clauses.extend(
                [
                    "jci.journal_id IS NULL",
                    "jmd.journal_id IS NULL",
                    "jpd.journal_id IS NULL",
                    "jtd.journal_id IS NULL",
                    "jpad.journal_id IS NULL",
                    "jfd.journal_id IS NULL",
                    "joad.journal_id IS NULL",
                    "jbwd.journal_id IS NULL",
                    "jjd.journal_id IS NULL",
                    "jabd.journal_id IS NULL",
                    "jcyd.journal_id IS NULL",
                    "jcld.journal_id IS NULL",
                    "jkyd.journal_id IS NULL",
                    "jskid.journal_id IS NULL",
                ]
            )
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
        table_joins = {
            "journal_mood_data": "INNER JOIN journal_mood_data t ON j.id = t.journal_id",
            "journal_calendar_info": "INNER JOIN journal_calendar_info t ON j.id = t.journal_id",
            "journal_plan_data": "INNER JOIN journal_plan_data t ON j.id = t.journal_id",
            "journal_travel_data": "INNER JOIN journal_travel_data t ON j.id = t.journal_id",
            "journal_photo_album_data": "INNER JOIN journal_photo_album_data t ON j.id = t.journal_id",
            "journal_fitness_data": "INNER JOIN journal_fitness_data t ON j.id = t.journal_id",
            "journal_outdoor_activity_data": "INNER JOIN journal_outdoor_activity_data t ON j.id = t.journal_id",
            "journal_bushwalking_data": "INNER JOIN journal_bushwalking_data t ON j.id = t.journal_id",
            "journal_jogging_data": "INNER JOIN journal_jogging_data t ON j.id = t.journal_id",
            "journal_abseiling_data": "INNER JOIN journal_abseiling_data t ON j.id = t.journal_id",
            "journal_canyoning_data": "INNER JOIN journal_canyoning_data t ON j.id = t.journal_id",
            "journal_climbing_data": "INNER JOIN journal_climbing_data t ON j.id = t.journal_id",
            "journal_kayaking_data": "INNER JOIN journal_kayaking_data t ON j.id = t.journal_id",
            "journal_skiing_data": "INNER JOIN journal_skiing_data t ON j.id = t.journal_id",
        }

        if type_table not in table_joins:
            msg = f"Unsupported table name: {type_table}"
            raise ValueError(msg)

        return table_joins[type_table]

    def _add_relationship_filters(
        self,
        joins: list[str],
        where_clauses: list[str],
        params: dict[str, Any],
        contact_id: str | None,
        tag_id: str | None,
        calendar_id: str | None,
        journal_type: str | None,
    ) -> bool:
        """Add JOIN and WHERE clauses for relationship filters.

        Args:
            joins: List to append JOIN clauses to
            where_clauses: List to append WHERE conditions to
            params: Dictionary to add query parameters to
            contact_id: Optional contact ID filter
            tag_id: Optional tag ID filter
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

        # Tag filter (many-to-many relationship)
        if tag_id is not None:
            joins.append(
                "INNER JOIN journal_tag_assignments jta ON j.id = jta.journal_id"
            )
            where_clauses.append("jta.tag_id = :tag_id")
            params["tag_id"] = tag_id
            needs_distinct = True

        # Calendar filter
        if calendar_id is not None:
            if not (journal_type and journal_type.upper() == "EVENT"):
                joins.append(
                    "INNER JOIN journal_calendar_info jci_cal ON j.id = jci_cal.journal_id"
                )
                where_clauses.append("jci_cal.calendar_id = :calendar_id")
            else:
                where_clauses.append("t.calendar_id = :calendar_id")
            params["calendar_id"] = calendar_id

        return needs_distinct

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
            params["end_date"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    async def find_by_id(self, journal_id: int) -> Journal | None:
        """Find a journal by ID."""
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

    async def get_all(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_id: str | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
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
            tag_id: Optional tag ID to filter journals by
            calendar_id: Optional calendar ID to filter journals by
            parent_id: Optional parent journal ID to filter by (None for root journals)
            search: Optional search query for full-text search

        Returns:
            List of journals matching the filter criteria
        """
        # Initialize query building components
        base_query_select = """
            SELECT {distinct}j.id, j.user_id, j.title, j.content,
                   j.event_date_range_start, j.event_date_range_end,
                   j.parent_id, j."order", j.created_at, j.updated_at
            FROM journals j
        """

        joins = []
        where_clauses = ["j.user_id = :user_id"]
        params: dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}

        # Build type filter joins and conditions
        type_joins, type_where = self._build_type_filter_joins(journal_type)
        joins.extend(type_joins)
        where_clauses.extend(type_where)

        # Add relationship filters (contacts, tags, calendars)
        needs_distinct = self._add_relationship_filters(
            joins, where_clauses, params, contact_id, tag_id, calendar_id, journal_type
        )

        # Add date range filters
        self._add_date_filters(where_clauses, params, start_date, end_date)

        # Add parent filter
        if parent_id is not None:
            where_clauses.append("j.parent_id = :parent_id")
            params["parent_id"] = parent_id

        # Add search filter
        if search is not None:
            where_clauses.append("(j.title ILIKE :search OR j.content ILIKE :search)")
            params["search"] = f"%{search}%"

        # Assemble the complete query
        distinct_keyword = "DISTINCT " if needs_distinct else ""
        base_query = base_query_select.format(distinct=distinct_keyword)

        if joins:
            base_query += "\n" + "\n".join(joins)

        base_query += "\nWHERE " + " AND ".join(where_clauses)
        base_query += "\nORDER BY j.event_date_range_start DESC, j.created_at DESC"
        base_query += "\nLIMIT :limit OFFSET :offset"

        query = text(base_query)
        result = await self.conn.execute(query, params)
        return [self._row_to_journal(row) for row in result.fetchall()]

    async def count_all(
        self,
        user_id: str,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_id: str | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
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
            tag_id: Optional tag ID to filter journals by
            calendar_id: Optional calendar ID to filter journals by
            parent_id: Optional parent journal ID to filter by
            search: Optional search query for full-text search

        Returns:
            Count of journals matching the filter criteria
        """
        # Initialize query building components
        base_query = """
            SELECT COUNT(DISTINCT j.id)
            FROM journals j
        """

        joins = []
        where_clauses = ["j.user_id = :user_id"]
        params: dict[str, Any] = {"user_id": user_id}

        # Build type filter joins and conditions (reuse helper method)
        type_joins, type_where = self._build_type_filter_joins(journal_type)
        joins.extend(type_joins)
        where_clauses.extend(type_where)

        # Add relationship filters (reuse helper method)
        self._add_relationship_filters(
            joins, where_clauses, params, contact_id, tag_id, calendar_id, journal_type
        )

        # Add date range filters (reuse helper method)
        self._add_date_filters(where_clauses, params, start_date, end_date)

        # Add parent filter
        if parent_id is not None:
            where_clauses.append("j.parent_id = :parent_id")
            params["parent_id"] = parent_id

        # Add search filter
        if search is not None:
            where_clauses.append("(j.title ILIKE :search OR j.content ILIKE :search)")
            params["search"] = f"%{search}%"

        # Assemble the complete query
        if joins:
            base_query += "\n" + "\n".join(joins)

        base_query += "\nWHERE " + " AND ".join(where_clauses)

        query = text(base_query)
        result = await self.conn.execute(query, params)
        row = result.fetchone()
        if row is None:
            return 0
        count_value = row[0]
        return int(count_value) if count_value is not None else 0

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

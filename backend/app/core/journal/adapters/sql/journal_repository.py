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
        # Build the base query with all necessary joins
        # Note: We'll conditionally add DISTINCT only if needed (when joins might produce duplicates)
        base_query_select = """
            SELECT {distinct}j.id, j.user_id, j.title, j.content,
                   j.event_date_range_start, j.event_date_range_end,
                   j.parent_id, j."order", j.created_at, j.updated_at
            FROM journals j
        """

        # Track which joins we need and whether DISTINCT is needed
        joins = []
        where_clauses = ["j.user_id = :user_id"]
        params: dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}
        needs_distinct = False  # Only use DISTINCT when joins might produce duplicates

        # Handle NOTE type filtering specially - NOTE journals have no other type data
        if journal_type and journal_type.upper() in ("NOTE", "note"):
            # Filter for journals that have NO type-specific data tables
            joins.extend(
                [
                    "LEFT JOIN journal_calendar_info jci ON j.id = jci.journal_id",
                    "LEFT JOIN journal_mood_data jmd ON j.id = jmd.journal_id",
                    "LEFT JOIN journal_plan_data jpd ON j.id = jpd.journal_id",
                    "LEFT JOIN journal_travel_data jtd ON j.id = jtd.journal_id",
                    "LEFT JOIN journal_photo_album_data jpad ON j.id = jpad.journal_id",
                ]
            )
            where_clauses.extend(
                [
                    "jci.journal_id IS NULL",
                    "jmd.journal_id IS NULL",
                    "jpd.journal_id IS NULL",
                    "jtd.journal_id IS NULL",
                    "jpad.journal_id IS NULL",
                ]
            )
        # Add JOIN if filtering by other types
        elif journal_type and journal_type in _JOURNAL_TYPE_TABLE_MAP:
            type_table = _JOURNAL_TYPE_TABLE_MAP[journal_type]

            # Use explicit if-elif chain instead of f-string interpolation
            # This prevents any possibility of SQL injection
            if type_table == "journal_mood_data":
                joins.append("INNER JOIN journal_mood_data t ON j.id = t.journal_id")
            elif type_table == "journal_calendar_info":
                joins.append(
                    "INNER JOIN journal_calendar_info t ON j.id = t.journal_id"
                )
            elif type_table == "journal_plan_data":
                joins.append("INNER JOIN journal_plan_data t ON j.id = t.journal_id")
            elif type_table == "journal_travel_data":
                joins.append("INNER JOIN journal_travel_data t ON j.id = t.journal_id")
            elif type_table == "journal_photo_album_data":
                joins.append(
                    "INNER JOIN journal_photo_album_data t ON j.id = t.journal_id"
                )
            else:
                msg = f"Unsupported table name: {type_table}"
                raise ValueError(msg)

        # Add contact filter
        # Note: A journal can have multiple contacts, so this join might produce duplicates
        if contact_id is not None:
            joins.append(
                "INNER JOIN journal_contact_relationships jcr ON j.id = jcr.journal_id"
            )
            where_clauses.append("jcr.contact_id = :contact_id")
            params["contact_id"] = int(contact_id)
            needs_distinct = True  # Multiple contacts per journal possible

        # Add tag filter
        # Note: A journal can have multiple tags, so this join might produce duplicates
        if tag_id is not None:
            joins.append(
                "INNER JOIN journal_tag_assignments jta ON j.id = jta.journal_id"
            )
            where_clauses.append("jta.tag_id = :tag_id")
            params["tag_id"] = tag_id
            needs_distinct = True  # Multiple tags per journal possible

        # Add calendar filter (via journal_calendar_info)
        if calendar_id is not None:
            # Only join if not already joined for EVENT type
            if not (journal_type and journal_type.upper() == "EVENT"):
                joins.append(
                    "INNER JOIN journal_calendar_info jci_cal ON j.id = jci_cal.journal_id"
                )
                where_clauses.append("jci_cal.calendar_id = :calendar_id")
            else:
                where_clauses.append("t.calendar_id = :calendar_id")
            params["calendar_id"] = calendar_id

            # Debug logging
            import structlog

            logger = structlog.get_logger()
            logger.debug(
                "Calendar filter applied",
                calendar_id=calendar_id,
                journal_type=journal_type,
                joins_count=len(joins),
                where_clauses_count=len(where_clauses),
            )

        # Add date range filters (overlap logic: journal overlaps with [start_date, end_date])
        # A journal overlaps if: journal.start <= end_date AND journal.end >= start_date
        if start_date is not None:
            where_clauses.append("j.event_date_range_end >= :start_date")
            # Convert ISO string to timezone-aware datetime for PostgreSQL
            # Ensure timezone awareness to avoid environment-dependent comparisons
            dt = datetime.fromisoformat(start_date)
            params["start_date"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)

        if end_date is not None:
            where_clauses.append("j.event_date_range_start <= :end_date")
            # Convert ISO string to timezone-aware datetime for PostgreSQL
            # Ensure timezone awareness to avoid environment-dependent comparisons
            dt = datetime.fromisoformat(end_date)
            params["end_date"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)

        # Add parent filter
        if parent_id is not None:
            where_clauses.append("j.parent_id = :parent_id")
            params["parent_id"] = parent_id

        # Add search filter (simple ILIKE for now, can be enhanced with full-text search later)
        if search is not None:
            where_clauses.append("(j.title ILIKE :search OR j.content ILIKE :search)")
            params["search"] = f"%{search}%"

        # Assemble the complete query
        # Apply DISTINCT only if needed (when joins might produce duplicates)
        distinct_keyword = "DISTINCT " if needs_distinct else ""
        base_query = base_query_select.format(distinct=distinct_keyword)

        if joins:
            base_query += "\n" + "\n".join(joins)

        base_query += "\nWHERE " + " AND ".join(where_clauses)
        base_query += "\nORDER BY j.event_date_range_start DESC, j.created_at DESC"
        base_query += "\nLIMIT :limit OFFSET :offset"

        # Debug logging
        import structlog

        logger = structlog.get_logger()
        logger.debug(
            "Executing journal query",
            query=base_query,
            params=params,
            user_id=user_id,
        )

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
        # Build the count query with the same filter logic as get_all()
        base_query = """
            SELECT COUNT(DISTINCT j.id)
            FROM journals j
        """

        # Track which joins we need (same logic as get_all())
        joins = []
        where_clauses = ["j.user_id = :user_id"]
        params: dict[str, Any] = {"user_id": user_id}

        # Handle NOTE type filtering (same as get_all())
        if journal_type and journal_type.upper() in ("NOTE", "note"):
            joins.extend(
                [
                    "LEFT JOIN journal_calendar_info jci ON j.id = jci.journal_id",
                    "LEFT JOIN journal_mood_data jmd ON j.id = jmd.journal_id",
                    "LEFT JOIN journal_plan_data jpd ON j.id = jpd.journal_id",
                    "LEFT JOIN journal_travel_data jtd ON j.id = jtd.journal_id",
                    "LEFT JOIN journal_photo_album_data jpad ON j.id = jpad.journal_id",
                ]
            )
            where_clauses.extend(
                [
                    "jci.journal_id IS NULL",
                    "jmd.journal_id IS NULL",
                    "jpd.journal_id IS NULL",
                    "jtd.journal_id IS NULL",
                    "jpad.journal_id IS NULL",
                ]
            )
        elif journal_type and journal_type in _JOURNAL_TYPE_TABLE_MAP:
            type_table = _JOURNAL_TYPE_TABLE_MAP[journal_type]
            if type_table == "journal_mood_data":
                joins.append("INNER JOIN journal_mood_data t ON j.id = t.journal_id")
            elif type_table == "journal_calendar_info":
                joins.append(
                    "INNER JOIN journal_calendar_info t ON j.id = t.journal_id"
                )
            elif type_table == "journal_plan_data":
                joins.append("INNER JOIN journal_plan_data t ON j.id = t.journal_id")
            elif type_table == "journal_travel_data":
                joins.append("INNER JOIN journal_travel_data t ON j.id = t.journal_id")
            elif type_table == "journal_photo_album_data":
                joins.append(
                    "INNER JOIN journal_photo_album_data t ON j.id = t.journal_id"
                )
            else:
                msg = f"Unsupported table name: {type_table}"
                raise ValueError(msg)

        # Add contact filter
        if contact_id is not None:
            joins.append(
                "INNER JOIN journal_contact_relationships jcr ON j.id = jcr.journal_id"
            )
            where_clauses.append("jcr.contact_id = :contact_id")
            params["contact_id"] = int(contact_id)

        # Add tag filter
        if tag_id is not None:
            joins.append(
                "INNER JOIN journal_tag_assignments jta ON j.id = jta.journal_id"
            )
            where_clauses.append("jta.tag_id = :tag_id")
            params["tag_id"] = tag_id

        # Add calendar filter
        if calendar_id is not None:
            if not (journal_type and journal_type.upper() == "EVENT"):
                joins.append(
                    "INNER JOIN journal_calendar_info jci_cal ON j.id = jci_cal.journal_id"
                )
                where_clauses.append("jci_cal.calendar_id = :calendar_id")
            else:
                where_clauses.append("t.calendar_id = :calendar_id")
            params["calendar_id"] = calendar_id

        # Add date range filters
        if start_date is not None:
            where_clauses.append("j.event_date_range_end >= :start_date")
            # Convert ISO string to timezone-aware datetime for PostgreSQL
            dt = datetime.fromisoformat(start_date)
            params["start_date"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)

        if end_date is not None:
            where_clauses.append("j.event_date_range_start <= :end_date")
            # Convert ISO string to timezone-aware datetime for PostgreSQL
            dt = datetime.fromisoformat(end_date)
            params["end_date"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)

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

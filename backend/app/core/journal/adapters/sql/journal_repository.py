"""SQL implementation of JournalRepository."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.entities import Journal
from app.core.journal.models.exceptions import JournalNotFoundError
from app.core.journal.models.repositories import JournalRepository
from app.core.journal.models.value_objects import EventDateRange


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
            raise JournalNotFoundError(journal.id)  # type: ignore[arg-type]

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
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        """Get all journals for a user with pagination."""
        query = text(
            """
            SELECT id, user_id, title, content,
                   event_date_range_start, event_date_range_end,
                   parent_id, "order", created_at, updated_at
            FROM journals
            WHERE user_id = :user_id
            ORDER BY event_date_range_start DESC, created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )
        result = await self.conn.execute(
            query, {"user_id": user_id, "limit": limit, "offset": offset}
        )
        return [self._row_to_journal(row) for row in result.fetchall()]

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

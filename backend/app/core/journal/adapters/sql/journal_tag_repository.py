"""SQL implementation of JournalTagRepository."""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.repositories import JournalTagRepository

# Every query selects the same columns in the same order, so declaring them
# once keeps the column list and the row -> entity mapper in step.
_TAG_COLUMN_NAMES = (
    "id",
    "name",
    "parent_id",
    "color",
    "description",
    "created_at",
    "updated_at",
)


def _tag_columns(alias: str = "") -> str:
    """Render the tag column list, optionally qualified by a table alias."""
    prefix = f"{alias}." if alias else ""
    return ", ".join(f"{prefix}{column}" for column in _TAG_COLUMN_NAMES)


_TAG_COLUMNS = _tag_columns()


def _row_to_tag(row: Any) -> JournalTag:
    """Map a journal_tags row to a JournalTag entity."""
    return JournalTag(
        id=row.id,
        name=row.name,
        parent_id=row.parent_id,
        color=row.color,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlJournalTagRepository(JournalTagRepository):
    """SQL implementation of journal tag repository."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    async def find_by_id(self, tag_id: UUID) -> JournalTag | None:
        """Find a tag by ID."""
        query = text(
            f"""
            SELECT {_TAG_COLUMNS}
            FROM journal_tags
            WHERE id = :tag_id
        """
        )
        result = await self.conn.execute(query, {"tag_id": tag_id})
        row = result.fetchone()

        if not row:
            return None

        return _row_to_tag(row)

    async def find_by_name(self, name: str) -> JournalTag | None:
        """Find a tag by name."""
        query = text(
            f"""
            SELECT {_TAG_COLUMNS}
            FROM journal_tags
            WHERE LOWER(name) = LOWER(:name)
        """
        )
        result = await self.conn.execute(query, {"name": name})
        row = result.fetchone()

        if not row:
            return None

        return _row_to_tag(row)

    async def save(self, tag: JournalTag) -> JournalTag:
        """Save a tag (insert or update)."""
        if tag.id is None:
            # Insert
            query = text(
                """
                INSERT INTO journal_tags (name, parent_id, color, description)
                VALUES (:name, :parent_id, :color, :description)
                RETURNING id, created_at, updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "name": tag.name,
                    "parent_id": tag.parent_id,
                    "color": tag.color,
                    "description": tag.description,
                },
            )
            row = result.fetchone()
            if row is not None:
                tag.id = row.id
                tag.created_at = row.created_at
                tag.updated_at = row.updated_at
        else:
            # Update
            query = text(
                """
                UPDATE journal_tags
                SET name = :name,
                    parent_id = :parent_id,
                    color = :color,
                    description = :description,
                    updated_at = now()
                WHERE id = :id
                RETURNING updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "id": tag.id,
                    "name": tag.name,
                    "parent_id": tag.parent_id,
                    "color": tag.color,
                    "description": tag.description,
                },
            )
            row = result.fetchone()
            if row is not None:
                tag.updated_at = row.updated_at

        return tag

    async def delete(self, tag_id: UUID) -> None:
        """Delete a tag by ID."""
        query = text("DELETE FROM journal_tags WHERE id = :tag_id")
        await self.conn.execute(query, {"tag_id": tag_id})

    async def get_all(self) -> list[JournalTag]:
        """Get all tags."""
        query = text(
            f"""
            SELECT {_TAG_COLUMNS}
            FROM journal_tags
            ORDER BY name
        """
        )
        result = await self.conn.execute(query)
        rows = result.fetchall()

        return [_row_to_tag(row) for row in rows]

    async def get_children(self, parent_id: UUID) -> list[JournalTag]:
        """Get child tags of a parent tag."""
        query = text(
            f"""
            SELECT {_TAG_COLUMNS}
            FROM journal_tags
            WHERE parent_id = :parent_id
            ORDER BY name
        """
        )
        result = await self.conn.execute(query, {"parent_id": parent_id})
        rows = result.fetchall()

        return [_row_to_tag(row) for row in rows]

    async def get_root_tags(self) -> list[JournalTag]:
        """Get all root tags (no parent)."""
        query = text(
            f"""
            SELECT {_TAG_COLUMNS}
            FROM journal_tags
            WHERE parent_id IS NULL
            ORDER BY name
        """
        )
        result = await self.conn.execute(query)
        rows = result.fetchall()

        return [_row_to_tag(row) for row in rows]

    async def get_tags_for_journal(self, journal_id: int) -> list[JournalTag]:
        """Get all tags assigned to a journal."""
        query = text(
            f"""
            SELECT {_tag_columns("t")}
            FROM journal_tags t
            JOIN journal_tag_assignments jta ON t.id = jta.tag_id
            WHERE jta.journal_id = :journal_id
            ORDER BY t.name
        """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        rows = result.fetchall()

        return [_row_to_tag(row) for row in rows]

    async def assign_tag(self, journal_id: int, tag_id: UUID) -> None:
        """Assign a tag to a journal."""
        query = text(
            """
            INSERT INTO journal_tag_assignments (journal_id, tag_id)
            VALUES (:journal_id, :tag_id)
            ON CONFLICT (journal_id, tag_id) DO NOTHING
        """
        )
        await self.conn.execute(query, {"journal_id": journal_id, "tag_id": tag_id})

    async def remove_tag(self, journal_id: int, tag_id: UUID) -> None:
        """Remove a tag from a journal."""
        query = text(
            """
            DELETE FROM journal_tag_assignments
            WHERE journal_id = :journal_id AND tag_id = :tag_id
        """
        )
        await self.conn.execute(query, {"journal_id": journal_id, "tag_id": tag_id})

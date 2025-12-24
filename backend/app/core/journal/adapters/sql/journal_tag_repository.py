"""SQL implementation of JournalTagRepository."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.repositories import JournalTagRepository


class SqlJournalTagRepository(JournalTagRepository):
    """SQL implementation of journal tag repository."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    async def find_by_id(self, tag_id: UUID) -> JournalTag | None:
        """Find a tag by ID."""
        query = text(
            """
            SELECT id, name, parent_id, color, created_at, updated_at
            FROM journal_tags
            WHERE id = :tag_id
        """
        )
        result = await self.conn.execute(query, {"tag_id": tag_id})
        row = result.fetchone()

        if not row:
            return None

        return JournalTag(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            color=row.color,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_name(self, name: str) -> JournalTag | None:
        """Find a tag by name."""
        query = text(
            """
            SELECT id, name, parent_id, color, created_at, updated_at
            FROM journal_tags
            WHERE name = :name
        """
        )
        result = await self.conn.execute(query, {"name": name})
        row = result.fetchone()

        if not row:
            return None

        return JournalTag(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            color=row.color,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, tag: JournalTag) -> JournalTag:
        """Save a tag (insert or update)."""
        if tag.id is None:
            # Insert
            query = text(
                """
                INSERT INTO journal_tags (name, parent_id, color)
                VALUES (:name, :parent_id, :color)
                RETURNING id, created_at, updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "name": tag.name,
                    "parent_id": tag.parent_id,
                    "color": tag.color,
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
                SET name = :name, parent_id = :parent_id, color = :color, updated_at = now()
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
            """
            SELECT id, name, parent_id, color, created_at, updated_at
            FROM journal_tags
            ORDER BY name
        """
        )
        result = await self.conn.execute(query)
        rows = result.fetchall()

        return [
            JournalTag(
                id=row.id,
                name=row.name,
                parent_id=row.parent_id,
                color=row.color,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def get_children(self, parent_id: UUID) -> list[JournalTag]:
        """Get child tags of a parent tag."""
        query = text(
            """
            SELECT id, name, parent_id, color, created_at, updated_at
            FROM journal_tags
            WHERE parent_id = :parent_id
            ORDER BY name
        """
        )
        result = await self.conn.execute(query, {"parent_id": parent_id})
        rows = result.fetchall()

        return [
            JournalTag(
                id=row.id,
                name=row.name,
                parent_id=row.parent_id,
                color=row.color,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def get_root_tags(self) -> list[JournalTag]:
        """Get all root tags (no parent)."""
        query = text(
            """
            SELECT id, name, parent_id, color, created_at, updated_at
            FROM journal_tags
            WHERE parent_id IS NULL
            ORDER BY name
        """
        )
        result = await self.conn.execute(query)
        rows = result.fetchall()

        return [
            JournalTag(
                id=row.id,
                name=row.name,
                parent_id=row.parent_id,
                color=row.color,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

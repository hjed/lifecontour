"""SQL implementation of TagRepository."""

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import Tag
from app.core.contacts.models.exceptions import DuplicateTagNameError, TagNotFoundError
from app.core.contacts.models.repositories import TagRepository
from app.core.contacts.models.value_objects import TagName


class SqlTagRepository(TagRepository):
    """SQL implementation of TagRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    async def find_by_id(self, tag_id: int) -> Tag | None:
        """Find a tag by ID."""
        query = text(
            """
            SELECT id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE id = :tag_id
        """
        )
        result = await self.conn.execute(query, {"tag_id": tag_id})
        row = result.fetchone()

        if not row:
            return None

        return Tag(
            id=row.id,
            name=TagName(row.name),
            parent_id=row.parent_id,
            color=row.color,
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_name(self, name: TagName) -> Tag | None:
        """Find a tag by name."""
        query = text(
            """
            SELECT id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE name = :name
        """
        )
        result = await self.conn.execute(query, {"name": str(name)})
        row = result.fetchone()

        if not row:
            return None

        return Tag(
            id=row.id,
            name=TagName(row.name),
            parent_id=row.parent_id,
            color=row.color,
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_all(self) -> list[Tag]:
        """Get all tags."""
        query = text(
            """
            SELECT id, name, parent_id, color, description, created_at, updated_at
            FROM tags ORDER BY name
        """
        )
        result = await self.conn.execute(query)

        tags = []
        for row in result.fetchall():
            tag = Tag(
                id=row.id,
                name=TagName(row.name),
                parent_id=row.parent_id,
                color=row.color,
                description=row.description,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            tags.append(tag)

        return tags

    async def get_children(self, parent_id: int) -> list[Tag]:
        """Get child tags of a parent tag."""
        query = text(
            """
            SELECT id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE parent_id = :parent_id ORDER BY name
        """
        )
        result = await self.conn.execute(query, {"parent_id": parent_id})

        tags = []
        for row in result.fetchall():
            tag = Tag(
                id=row.id,
                name=TagName(row.name),
                parent_id=row.parent_id,
                color=row.color,
                description=row.description,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            tags.append(tag)

        return tags

    async def get_root_tags(self) -> list[Tag]:
        """Get all root tags (no parent)."""
        query = text(
            """
            SELECT id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE parent_id IS NULL ORDER BY name
        """
        )
        result = await self.conn.execute(query)

        tags = []
        for row in result.fetchall():
            tag = Tag(
                id=row.id,
                name=TagName(row.name),
                parent_id=row.parent_id,
                color=row.color,
                description=row.description,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            tags.append(tag)

        return tags

    async def search(self, query: str, limit: int = 50) -> list[Tag]:
        """Search tags by name pattern."""
        search_query = text(
            """
            SELECT id, name, parent_id, color, description, created_at, updated_at
            FROM tags
            WHERE name ILIKE :pattern
            ORDER BY name
            LIMIT :limit
        """
        )
        result = await self.conn.execute(
            search_query, {"pattern": f"%{query}%", "limit": limit}
        )

        tags = []
        for row in result.fetchall():
            tag = Tag(
                id=row.id,
                name=TagName(row.name),
                parent_id=row.parent_id,
                color=row.color,
                description=row.description,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            tags.append(tag)

        return tags

    async def save(self, tag: Tag) -> Tag:
        """Save a tag (insert or update)."""
        try:
            if tag.id is None:
                # Insert new tag
                query = text(
                    """
                    INSERT INTO tags (name, parent_id, color, description)
                    VALUES (:name, :parent_id, :color, :description)
                    RETURNING id, created_at, updated_at
                """
                )
                result = await self.conn.execute(
                    query,
                    {
                        "name": str(tag.name),
                        "parent_id": tag.parent_id,
                        "color": tag.color,
                        "description": tag.description,
                    },
                )
                row = result.fetchone()
                tag.id = row.id
                tag.created_at = row.created_at
                tag.updated_at = row.updated_at
            else:
                # Update existing tag
                query = text(
                    """
                    UPDATE tags
                    SET name = :name, parent_id = :parent_id, color = :color,
                        description = :description, updated_at = NOW()
                    WHERE id = :id
                    RETURNING updated_at
                """
                )
                result = await self.conn.execute(
                    query,
                    {
                        "id": tag.id,
                        "name": str(tag.name),
                        "parent_id": tag.parent_id,
                        "color": tag.color,
                        "description": tag.description,
                    },
                )
                row = result.fetchone()
                tag.updated_at = row.updated_at

            return tag

        except IntegrityError as e:
            if "unique" in str(e).lower() and "name" in str(e).lower():
                raise DuplicateTagNameError(str(tag.name)) from e
            raise

    async def delete(self, tag_id: int) -> None:
        """Delete a tag."""
        query = text("DELETE FROM tags WHERE id = :tag_id")
        result = await self.conn.execute(query, {"tag_id": tag_id})

        if result.rowcount == 0:
            raise TagNotFoundError(tag_id)

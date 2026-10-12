"""SQL implementation of TagRepository."""

from typing import Any

from core_shared.models.contacts.entities import Tag
from core_shared.models.contacts.value_objects import TagName
from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import DuplicateTagNameError, TagNotFoundError
from app.core.contacts.models.repositories import TagRepository


def _row_to_tag(row: Row[Any]) -> Tag:
    return Tag(
        id=row.id,
        user_id=row.user_id,
        name=TagName(row.name),
        parent_id=row.parent_id,
        color=row.color,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlTagRepository(TagRepository):
    """SQL implementation of TagRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    async def find_by_id(self, tag_id: int, *, user_id: str) -> Tag | None:
        """Find ``user_id``'s tag by ID."""
        query = text(
            """
            SELECT id, user_id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE id = :tag_id AND user_id = :user_id
        """
        )
        result = await self.conn.execute(query, {"tag_id": tag_id, "user_id": user_id})
        row = result.fetchone()

        if not row:
            return None

        return _row_to_tag(row)

    async def find_by_name(self, name: str, *, user_id: str) -> Tag | None:
        """Find ``user_id``'s tag by name, case-insensitively."""
        query = text(
            """
            SELECT id, user_id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE LOWER(name) = LOWER(:name) AND user_id = :user_id
        """
        )
        result = await self.conn.execute(query, {"name": name, "user_id": user_id})
        row = result.fetchone()

        if not row:
            return None

        return _row_to_tag(row)

    async def find_by_names(self, names: list[str], *, user_id: str) -> dict[str, Tag]:
        """Find ``user_id``'s tags by name, returned as a dict keyed by requested name."""
        if not names:
            return {}

        lower_names = [n.lower() for n in names]
        query = text(
            """
            SELECT id, user_id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE LOWER(name) = ANY(:names) AND user_id = :user_id
        """
        )
        result = await self.conn.execute(
            query, {"names": lower_names, "user_id": user_id}
        )

        lower_to_tag = {}
        for row in result:
            lower_to_tag[row.name.lower()] = _row_to_tag(row)

        tags_dict = {}
        for name in names:
            lower_name = name.lower()
            if lower_name in lower_to_tag:
                tags_dict[name] = lower_to_tag[lower_name]

        return tags_dict

    async def get_all(self, *, user_id: str) -> list[Tag]:
        """Get all of ``user_id``'s tags."""
        query = text(
            """
            SELECT id, user_id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE user_id = :user_id ORDER BY name
        """
        )
        result = await self.conn.execute(query, {"user_id": user_id})

        return [_row_to_tag(row) for row in result.fetchall()]

    async def get_children(self, parent_id: int, *, user_id: str) -> list[Tag]:
        """Get ``user_id``'s child tags of a parent tag."""
        query = text(
            """
            SELECT id, user_id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE parent_id = :parent_id AND user_id = :user_id ORDER BY name
        """
        )
        result = await self.conn.execute(
            query, {"parent_id": parent_id, "user_id": user_id}
        )

        return [_row_to_tag(row) for row in result.fetchall()]

    async def get_descendants_for_tags(
        self, tag_ids: list[int], *, user_id: str
    ) -> list[Tag]:
        """Get ``user_id``'s descendant tags (recursive) of a list of tag IDs.

        Every level is filtered, so the walk never steps into another owner's tags.
        """
        if not tag_ids:
            return []

        query = text(
            """
            WITH RECURSIVE descendants AS (
                SELECT id, user_id, name, parent_id, color, description, created_at, updated_at
                FROM tags
                WHERE parent_id = ANY(:tag_ids) AND user_id = :user_id

                UNION ALL

                SELECT t.id, t.user_id, t.name, t.parent_id, t.color, t.description, t.created_at, t.updated_at
                FROM tags t
                INNER JOIN descendants d ON t.parent_id = d.id
                WHERE t.user_id = :user_id
            )
            SELECT DISTINCT id, user_id, name, parent_id, color, description, created_at, updated_at
            FROM descendants
            ORDER BY name
            """
        )
        result = await self.conn.execute(
            query, {"tag_ids": tag_ids, "user_id": user_id}
        )

        return [_row_to_tag(row) for row in result.fetchall()]

    async def get_root_tags(self, *, user_id: str) -> list[Tag]:
        """Get ``user_id``'s root tags (no parent)."""
        query = text(
            """
            SELECT id, user_id, name, parent_id, color, description, created_at, updated_at
            FROM tags WHERE parent_id IS NULL AND user_id = :user_id ORDER BY name
        """
        )
        result = await self.conn.execute(query, {"user_id": user_id})

        return [_row_to_tag(row) for row in result.fetchall()]

    async def search(self, query: str, limit: int = 50, *, user_id: str) -> list[Tag]:
        """Search ``user_id``'s tags by name pattern."""
        search_query = text(
            """
            SELECT id, user_id, name, parent_id, color, description, created_at, updated_at
            FROM tags
            WHERE name ILIKE :pattern AND user_id = :user_id
            ORDER BY name
            LIMIT :limit
        """
        )
        result = await self.conn.execute(
            search_query, {"pattern": f"%{query}%", "limit": limit, "user_id": user_id}
        )

        return [_row_to_tag(row) for row in result.fetchall()]

    async def save(self, tag: Tag, *, user_id: str) -> Tag:
        """Save a tag: an insert is owned by ``user_id``; an update never re-owns."""
        try:
            if tag.id is None:
                # Insert new tag
                query = text(
                    """
                    INSERT INTO tags (user_id, name, parent_id, color, description)
                    VALUES (:user_id, :name, :parent_id, :color, :description)
                    RETURNING id, user_id, created_at, updated_at
                """
                )
                result = await self.conn.execute(
                    query,
                    {
                        "user_id": user_id,
                        "name": str(tag.name),
                        "parent_id": tag.parent_id,
                        "color": tag.color,
                        "description": tag.description,
                    },
                )
                row = result.fetchone()
                if row is None:
                    raise RuntimeError("Failed to insert tag")
                tag.id = row.id
                tag.user_id = row.user_id
                tag.created_at = row.created_at
                tag.updated_at = row.updated_at
            else:
                # Update existing tag
                query = text(
                    """
                    UPDATE tags
                    SET name = :name, parent_id = :parent_id, color = :color,
                        description = :description, updated_at = NOW()
                    WHERE id = :id AND user_id = :user_id
                    RETURNING updated_at
                """
                )
                result = await self.conn.execute(
                    query,
                    {
                        "id": tag.id,
                        "user_id": user_id,
                        "name": str(tag.name),
                        "parent_id": tag.parent_id,
                        "color": tag.color,
                        "description": tag.description,
                    },
                )
                row = result.fetchone()
                if row is None:
                    # Missing, or another user's: either way not this user's tag.
                    raise TagNotFoundError(tag.id)
                tag.updated_at = row.updated_at

            return tag

        except IntegrityError as e:
            if "unique" in str(e).lower() and "name" in str(e).lower():
                raise DuplicateTagNameError(str(tag.name)) from e
            raise

    async def delete(self, tag_id: int, *, user_id: str) -> bool:
        """Delete ``user_id``'s tag; return whether one was deleted."""
        result = await self.conn.execute(
            text("DELETE FROM tags WHERE id = :tag_id AND user_id = :user_id"),
            {"tag_id": tag_id, "user_id": user_id},
        )
        return bool(result.rowcount)

    async def merge_into(self, source_id: int, target_id: int, *, user_id: str) -> bool:
        """Move the user's source tag's contacts and children onto their target.

        The source itself is left for the caller to delete. Nothing moves unless
        the user owns both tags, so another user's assignments and hierarchy are
        never rewritten; returns whether it moved them.
        """
        owned = await self.conn.execute(
            text(
                "SELECT count(*) FROM tags "
                "WHERE id IN (:source_id, :target_id) AND user_id = :user_id"
            ),
            {"source_id": source_id, "target_id": target_id, "user_id": user_id},
        )
        if source_id == target_id or owned.scalar_one() != 2:
            return False

        params = {"source_id": source_id, "target_id": target_id}
        # 1. Drop source assignments a contact already holds for the target, so
        #    the re-point below cannot violate the composite primary key.
        await self.conn.execute(
            text(
                """
                DELETE FROM contact_tags ct
                WHERE ct.tag_id = :source_id
                AND EXISTS (
                    SELECT 1 FROM contact_tags ct2
                    WHERE ct2.contact_id = ct.contact_id
                    AND ct2.tag_id = :target_id
                )
                """
            ),
            params,
        )
        # 2. Re-point the remaining assignments onto the target.
        await self.conn.execute(
            text(
                "UPDATE contact_tags SET tag_id = :target_id WHERE tag_id = :source_id"
            ),
            params,
        )
        # 3. The target adopts the source's children (the user's only).
        await self.conn.execute(
            text(
                "UPDATE tags SET parent_id = :target_id "
                "WHERE parent_id = :source_id AND user_id = :user_id"
            ),
            {**params, "user_id": user_id},
        )
        return True

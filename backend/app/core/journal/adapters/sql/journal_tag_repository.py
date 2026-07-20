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

    async def merge_into(self, source_id: UUID, target_id: UUID) -> None:
        """Fold the source tag into the target tag and delete the source."""
        # Merging a tag into itself would delete every one of its assignments
        # (step 1's EXISTS matches the row against itself) and then delete the
        # tag — silent data loss from what reads like a no-op. The service
        # rejects it before reaching here, so this is a precondition failure
        # rather than user input, and a bare ValueError is the right shape.
        if source_id == target_id:
            raise ValueError(
                "merge_into requires distinct source and target tags; "
                f"both were {source_id}"
            )

        params = {"source_id": source_id, "target_id": target_id}

        # 1. Drop source assignments the journal already holds for the target,
        #    so the re-point below cannot violate the composite primary key.
        await self.conn.execute(
            text(
                """
                DELETE FROM journal_tag_assignments src
                WHERE src.tag_id = :source_id
                AND EXISTS (
                    SELECT 1 FROM journal_tag_assignments tgt
                    WHERE tgt.journal_id = src.journal_id
                    AND tgt.tag_id = :target_id
                )
                """
            ),
            params,
        )

        # 2. Re-point the remaining assignments onto the target.
        await self.conn.execute(
            text(
                """
                UPDATE journal_tag_assignments
                SET tag_id = :target_id
                WHERE tag_id = :source_id
                """
            ),
            params,
        )

        # 3. Adopt the source's children so deleting it does not send them to
        #    the root via the ON DELETE SET NULL FK. The target is excluded:
        #    when it is itself a child of the source it would otherwise become
        #    its own parent, and a self-cycle would poison every later
        #    ancestry walk. Its parent is cleared instead, promoting it to the
        #    root — the position the source it replaces would have vacated.
        await self.conn.execute(
            text(
                """
                UPDATE journal_tags
                SET parent_id = CASE WHEN id = :target_id THEN NULL
                                     ELSE :target_id END,
                    updated_at = now()
                WHERE parent_id = :source_id
                """
            ),
            params,
        )

        await self.delete(source_id)

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

    async def get_descendants_for_tags(self, tag_ids: list[UUID]) -> list[JournalTag]:
        """Get all descendant tags (recursively) for a list of tag IDs."""
        if not tag_ids:
            return []

        query = text(
            f"""
            WITH RECURSIVE descendants AS (
                SELECT {_TAG_COLUMNS}
                FROM journal_tags
                WHERE parent_id = ANY(:tag_ids)

                UNION ALL

                SELECT {_tag_columns("t")}
                FROM journal_tags t
                INNER JOIN descendants d ON t.parent_id = d.id
            )
            SELECT DISTINCT {_TAG_COLUMNS}
            FROM descendants
            ORDER BY name
        """
        )
        result = await self.conn.execute(query, {"tag_ids": tag_ids})
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

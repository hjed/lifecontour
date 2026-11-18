"""SQL implementation of :class:`TaskListRepository`.

Follows :mod:`.task_repository`'s conventions: every query selects
``_TASK_LIST_COLUMNS`` and every row goes through ``_row_to_task_list``, and
every statement filters on ``user_id`` so another user's list is never reached.
"""

from typing import Any

from core_shared.models.tasks import (
    TaskIcon,
    TaskList,
    TaskListArchiveFilter,
    TaskListNotFoundError,
)
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.repositories import TaskListRepository

# Declared once so the column list and the row -> entity mapper stay in step.
_TASK_LIST_COLUMNS = ", ".join(
    (
        "id",
        "user_id",
        "name",
        "icon",
        "position",
        "archived_at",
        "created_at",
        "updated_at",
    )
)

# The new list's position is computed in the INSERT itself, over every list the
# owner has — archived ones included, so an unarchived list returns to its old
# place. Two concurrent inserts can take the same position; ``(position, id)``
# keeps the order total, which is why positions are not unique.
_INSERT = text(
    f"""
    INSERT INTO task_lists (user_id, name, icon, position, archived_at)
    VALUES (
        :user_id,
        :name,
        :icon,
        (
            SELECT COALESCE(MAX(position) + 1, 0)
            FROM task_lists
            -- asyncpg deduces one type per parameter; the comparison alone
            -- would deduce ``text`` beside the column's ``varchar``.
            WHERE user_id = CAST(:user_id AS VARCHAR)
        ),
        :archived_at
    )
    RETURNING {_TASK_LIST_COLUMNS}
    """
)

# ``position`` and ``created_at`` are deliberately absent: only reordering moves
# a list, so a rename racing a reorder cannot undo it.
_UPDATE = text(
    f"""
    UPDATE task_lists
    SET name = :name,
        icon = :icon,
        archived_at = :archived_at,
        updated_at = now()
    WHERE id = :id AND user_id = :user_id
    RETURNING {_TASK_LIST_COLUMNS}
    """
)

_FIND = text(
    f"""
    SELECT {_TASK_LIST_COLUMNS}
    FROM task_lists
    WHERE id = :id AND user_id = :user_id
    """
)

# ``FOR NO KEY UPDATE``, as for tasks: it excludes other writers of the list
# without blocking the ``FOR KEY SHARE`` a foreign-key check against it takes.
_FIND_FOR_UPDATE = text(
    f"""
    SELECT {_TASK_LIST_COLUMNS}
    FROM task_lists
    WHERE id = :id AND user_id = :user_id
    FOR NO KEY UPDATE
    """
)

_IN_USER_ORDER = "ORDER BY position, id"

_LIST_QUERIES = {
    TaskListArchiveFilter.ACTIVE: text(
        f"""
        SELECT {_TASK_LIST_COLUMNS}
        FROM task_lists
        WHERE user_id = :user_id AND archived_at IS NULL
        {_IN_USER_ORDER}
        """
    ),
    TaskListArchiveFilter.ARCHIVED: text(
        f"""
        SELECT {_TASK_LIST_COLUMNS}
        FROM task_lists
        WHERE user_id = :user_id AND archived_at IS NOT NULL
        ORDER BY archived_at DESC, id DESC
        """
    ),
    TaskListArchiveFilter.ALL: text(
        f"""
        SELECT {_TASK_LIST_COLUMNS}
        FROM task_lists
        WHERE user_id = :user_id
        {_IN_USER_ORDER}
        """
    ),
}

_DELETE = text("DELETE FROM task_lists WHERE id = :id AND user_id = :user_id")


def _row_to_task_list(row: Any) -> TaskList:
    """Map a ``task_lists`` row to a :class:`TaskList` entity."""
    return TaskList(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        icon=None if row.icon is None else TaskIcon(row.icon),
        position=row.position,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _write_params(task_list: TaskList) -> dict[str, Any]:
    """The columns a caller may set, as statement parameters."""
    return {
        "user_id": task_list.user_id,
        "name": task_list.name,
        "icon": None if task_list.icon is None else task_list.icon.value,
        "archived_at": task_list.archived_at,
    }


class SqlTaskListRepository(TaskListRepository):
    """SQL implementation of the task list repository."""

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize with database connection."""
        self.conn = conn

    async def save(self, task_list: TaskList) -> TaskList:
        """Insert a new list at the bottom, or update an existing one."""
        if task_list.id is None:
            result = await self.conn.execute(_INSERT, _write_params(task_list))
            return _row_to_task_list(result.one())

        result = await self.conn.execute(
            _UPDATE, {"id": task_list.id, **_write_params(task_list)}
        )
        row = result.fetchone()
        if row is None:
            # The id may exist and belong to somebody else; saying so would
            # leak its existence, so an unowned list is simply not found.
            raise TaskListNotFoundError(task_list.id)
        return _row_to_task_list(row)

    async def find_by_id(self, task_list_id: int, user_id: str) -> TaskList | None:
        """Find one of the user's lists by id."""
        return await self._find_one(_FIND, task_list_id, user_id)

    async def find_by_id_for_update(
        self, task_list_id: int, user_id: str
    ) -> TaskList | None:
        """Find one of the user's lists and lock its row against other writers."""
        return await self._find_one(_FIND_FOR_UPDATE, task_list_id, user_id)

    async def list_for_user(
        self,
        user_id: str,
        archived: TaskListArchiveFilter = TaskListArchiveFilter.ACTIVE,
    ) -> list[TaskList]:
        """List the user's lists, filtered by archived state."""
        result = await self.conn.execute(_LIST_QUERIES[archived], {"user_id": user_id})
        return [_row_to_task_list(row) for row in result.fetchall()]

    async def delete(self, task_list_id: int, user_id: str) -> None:
        """Hard-delete one of the user's lists."""
        result = await self.conn.execute(
            _DELETE, {"id": task_list_id, "user_id": user_id}
        )
        if result.rowcount == 0:
            raise TaskListNotFoundError(task_list_id)

    async def _find_one(
        self, query: TextClause, task_list_id: int, user_id: str
    ) -> TaskList | None:
        result = await self.conn.execute(
            query, {"id": task_list_id, "user_id": user_id}
        )
        row = result.fetchone()
        return None if row is None else _row_to_task_list(row)

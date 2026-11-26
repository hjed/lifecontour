"""SQL implementation of :class:`TaskListRepository`.

Follows :mod:`.task_repository`'s conventions: every query selects
``_TASK_LIST_COLUMNS`` and every row goes through ``_row_to_task_list``, and
every statement filters on ``user_id`` so another user's list is never reached.
"""

from collections.abc import Sequence
from typing import Any

from core_shared.models.tasks import (
    TaskIcon,
    TaskList,
    TaskListArchiveFilter,
    TaskListBusyError,
    TaskListNotFoundError,
)
from sqlalchemy import TextClause, text
from sqlalchemy.exc import DBAPIError
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
        "associated_journal_id",
        "created_at",
        "updated_at",
    )
)

# The new list's position is computed in the INSERT itself, over every list the
# owner has — archived ones included, so an unarchived list returns to its old
# place. ``save`` takes ``_LOCK_OWNER_LISTS`` first, so the INSERT's snapshot is
# taken after any move holding them has committed. Two first-ever lists can
# still share position 0 (there is nothing to lock yet); ``(position, id)``
# keeps the order total, which is why positions are not unique.
_INSERT = text(
    f"""
    INSERT INTO task_lists (
        user_id, name, icon, position, archived_at, associated_journal_id
    )
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
        :archived_at,
        :associated_journal_id
    )
    RETURNING {_TASK_LIST_COLUMNS}
    """
)

# ``position`` and ``created_at`` are deliberately absent: only reordering moves
# a list, so a rename racing a reorder cannot undo it. Every other column is
# written as given, the association included, so callers update from the row
# they read under its lock.
_UPDATE = text(
    f"""
    UPDATE task_lists
    SET name = :name,
        icon = :icon,
        archived_at = :archived_at,
        associated_journal_id = :associated_journal_id,
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

# ``FOR SHARE``, for a *task* write that must hold its list writable until it
# commits. It conflicts with the ``FOR NO KEY UPDATE`` every list write takes —
# so an archive waits for an in-flight task write, and a task write waits for an
# in-flight archive and then reads the archived row — but not with another task
# write's share lock, so writes to different tasks on one list never queue.
_FIND_FOR_SHARE = text(
    f"""
    SELECT {_TASK_LIST_COLUMNS}
    FROM task_lists
    WHERE id = :id AND user_id = :user_id
    FOR SHARE
    """
)

_IN_USER_ORDER = "ORDER BY position, id"

# Locks every list the owner has against other position writers: a move, and
# the create that appends below them. The rows are locked in ``id`` order —
# which no move changes — rather than in ``(position, id)``, so two of them
# always take the locks in the same order and cannot deadlock.
#
# It is a statement of its own, run before the positions are read, because
# under READ COMMITTED a statement that waited on a lock still reads with the
# snapshot it started with: it would miss the positions the holder committed,
# and a list the holder created. The read that follows takes a fresh snapshot.
_LOCK_OWNER_LISTS = text(
    """
    SELECT id
    FROM task_lists
    WHERE user_id = :user_id
    ORDER BY id
    FOR NO KEY UPDATE
    """
)

# Every list the owner has, archived ones included — a move renumbers them too,
# keeping each where it was relative to its neighbours.
_LIST_ALL = text(
    f"""
    SELECT {_TASK_LIST_COLUMNS}
    FROM task_lists
    WHERE user_id = :user_id
    {_IN_USER_ORDER}
    """
)

# Positions from each id's place in the given order, 0 at the top. A row
# already in place is skipped (``IS DISTINCT FROM``), so a no-op move writes
# nothing. ``updated_at`` is left alone: a reorder is not an edit of the list.
_REPOSITION = text(
    """
    UPDATE task_lists AS lists
    SET position = ordered.new_position
    FROM (
        SELECT id, (ordinality - 1)::integer AS new_position
        FROM unnest(CAST(:ordered_ids AS integer[])) WITH ORDINALITY AS t(id)
    ) AS ordered
    WHERE lists.id = ordered.id
      AND lists.user_id = :user_id
      AND lists.position IS DISTINCT FROM ordered.new_position
    """
)

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

# A delete's exclusive lock on the list, taken without waiting: the caller
# already holds the list ``FOR SHARE`` and every task on it, so another holder
# of the list now may be queued behind one of those tasks and waiting could
# deadlock. See ``TaskRepository``'s lock order.
_LOCK_FOR_DELETE = text(
    "SELECT id FROM task_lists WHERE id = :id AND user_id = :user_id FOR UPDATE NOWAIT"
)
_DELETE = text("DELETE FROM task_lists WHERE id = :id AND user_id = :user_id")
# PostgreSQL's ``lock_not_available``, raised by ``NOWAIT``.
_LOCK_NOT_AVAILABLE = "55P03"

_FIND_BY_IDS = text(
    f"""
    SELECT {_TASK_LIST_COLUMNS}
    FROM task_lists
    WHERE id = ANY(:ids) AND user_id = :user_id
    """
)

# Both owners are checked: a task row naming another owner's list must not
# reveal that list's name.
_FIND_FOR_TASKS = text(
    f"""
    SELECT tasks.id AS task_id,
           {", ".join(f"task_lists.{column}" for column in _TASK_LIST_COLUMNS.split(", "))}
    FROM tasks
    JOIN task_lists ON task_lists.id = tasks.task_list_id
    WHERE tasks.id = ANY(:task_ids)
      AND tasks.user_id = :user_id
      AND task_lists.user_id = :user_id
    """
)


# The owner's lists on a journal, locked in ``id`` order — the order
# ``_LOCK_OWNER_LISTS`` takes — before a journal delete or merge rewrites their
# association, so it cannot cross a create or reorder holding some of them. A
# bare UPDATE would lock them in scan order instead.
_LOCK_ASSOCIATED_WITH_JOURNAL = text(
    """
    SELECT id
    FROM task_lists
    WHERE associated_journal_id = :journal_id AND user_id = :user_id
    ORDER BY id
    FOR NO KEY UPDATE
    """
)

# A system write on behalf of a journal delete: no archived check, every one of
# the owner's lists on the journal.
_UNASSOCIATE_JOURNAL = text(
    """
    UPDATE task_lists
    SET associated_journal_id = NULL,
        updated_at = now()
    WHERE associated_journal_id = :journal_id AND user_id = :user_id
    RETURNING id
    """
)

# The merge's counterpart: the association follows the surviving journal.
_REASSOCIATE_JOURNAL = text(
    """
    UPDATE task_lists
    SET associated_journal_id = :target_journal_id,
        updated_at = now()
    WHERE associated_journal_id = :source_journal_id AND user_id = :user_id
    RETURNING id
    """
)

_COUNT_ASSOCIATED_WITH_JOURNAL = text(
    """
    SELECT COUNT(*)
    FROM task_lists
    WHERE associated_journal_id = :journal_id AND user_id = :user_id
    """
)


def _row_to_task_list(row: Any) -> TaskList:
    """Map a ``task_lists`` row to a :class:`TaskList` entity."""
    return TaskList(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        icon=None if row.icon is None else TaskIcon(row.icon),
        position=row.position,
        archived_at=row.archived_at,
        associated_journal_id=row.associated_journal_id,
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
        "associated_journal_id": task_list.associated_journal_id,
    }


class SqlTaskListRepository(TaskListRepository):
    """SQL implementation of the task list repository."""

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize with database connection."""
        self.conn = conn

    async def save(self, task_list: TaskList) -> TaskList:
        """Insert a new list at the bottom, or update an existing one.

        An insert first locks the owner's lists, as a move does, so the bottom
        it computes is the one a concurrent move leaves behind.
        """
        if task_list.id is None:
            await self._lock_owner_lists(task_list.user_id)
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

    async def find_by_id_for_share(
        self, task_list_id: int, user_id: str
    ) -> TaskList | None:
        """Find one of the user's lists and hold it against list writers."""
        return await self._find_one(_FIND_FOR_SHARE, task_list_id, user_id)

    async def find_by_ids(
        self, task_list_ids: Sequence[int], user_id: str
    ) -> dict[int, TaskList]:
        """The user's lists among ``task_list_ids``, keyed by id."""
        if not task_list_ids:
            return {}
        result = await self.conn.execute(
            _FIND_BY_IDS, {"ids": list(task_list_ids), "user_id": user_id}
        )
        found = [_row_to_task_list(row) for row in result.fetchall()]
        return {
            task_list.id: task_list for task_list in found if task_list.id is not None
        }

    async def find_for_tasks(
        self, task_ids: Sequence[int], user_id: str
    ) -> dict[int, TaskList]:
        """The list each of the user's tasks sits on, keyed by task id."""
        if not task_ids:
            return {}
        result = await self.conn.execute(
            _FIND_FOR_TASKS, {"task_ids": list(task_ids), "user_id": user_id}
        )
        return {row.task_id: _row_to_task_list(row) for row in result.fetchall()}

    async def list_for_user(
        self,
        user_id: str,
        archived: TaskListArchiveFilter = TaskListArchiveFilter.ACTIVE,
    ) -> list[TaskList]:
        """List the user's lists, filtered by archived state."""
        result = await self.conn.execute(_LIST_QUERIES[archived], {"user_id": user_id})
        return [_row_to_task_list(row) for row in result.fetchall()]

    async def list_for_user_for_update(self, user_id: str) -> list[TaskList]:
        """Every one of the user's lists, archived included, locked against
        other writers, in ``(position, id)`` order."""
        await self._lock_owner_lists(user_id)
        result = await self.conn.execute(_LIST_ALL, {"user_id": user_id})
        return [_row_to_task_list(row) for row in result.fetchall()]

    async def reposition(self, user_id: str, ordered_ids: Sequence[int]) -> None:
        """Number the user's lists densely in the given order."""
        if not ordered_ids:
            return
        await self.conn.execute(
            _REPOSITION, {"user_id": user_id, "ordered_ids": list(ordered_ids)}
        )

    async def serialize_deletes(self, task_list_id: int) -> None:
        """A transaction-scoped advisory lock keyed on the list, not a row lock."""
        await self.conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"task_list_delete:{task_list_id}"},
        )

    async def delete(self, task_list_id: int, user_id: str) -> None:
        """Hard-delete one of the user's lists, locking it without waiting."""
        params = {"id": task_list_id, "user_id": user_id}
        try:
            locked = (await self.conn.execute(_LOCK_FOR_DELETE, params)).fetchone()
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == _LOCK_NOT_AVAILABLE:
                raise TaskListBusyError(task_list_id) from error
            raise
        if locked is None:
            raise TaskListNotFoundError(task_list_id)
        await self.conn.execute(_DELETE, params)

    async def unassociate_journal(self, journal_id: int, user_id: str) -> list[int]:
        """Clear every one of the owner's lists on the journal; their ids, ascending."""
        await self._lock_associated_with_journal(journal_id, user_id)
        result = await self.conn.execute(
            _UNASSOCIATE_JOURNAL, {"journal_id": journal_id, "user_id": user_id}
        )
        return sorted(int(row.id) for row in result.fetchall())

    async def reassociate_journal(
        self, *, source_journal_id: int, target_journal_id: int, user_id: str
    ) -> list[int]:
        """Move the owner's lists on the source journal to the target; ids, ascending."""
        await self._lock_associated_with_journal(source_journal_id, user_id)
        result = await self.conn.execute(
            _REASSOCIATE_JOURNAL,
            {
                "source_journal_id": source_journal_id,
                "target_journal_id": target_journal_id,
                "user_id": user_id,
            },
        )
        return sorted(int(row.id) for row in result.fetchall())

    async def count_associated_with_journal(self, journal_id: int, user_id: str) -> int:
        """How many of the owner's lists name the journal."""
        result = await self.conn.execute(
            _COUNT_ASSOCIATED_WITH_JOURNAL,
            {"journal_id": journal_id, "user_id": user_id},
        )
        return int(result.scalar_one())

    async def _lock_associated_with_journal(
        self, journal_id: int, user_id: str
    ) -> None:
        await self.conn.execute(
            _LOCK_ASSOCIATED_WITH_JOURNAL,
            {"journal_id": journal_id, "user_id": user_id},
        )

    async def _lock_owner_lists(self, user_id: str) -> None:
        await self.conn.execute(_LOCK_OWNER_LISTS, {"user_id": user_id})

    async def _find_one(
        self, query: TextClause, task_list_id: int, user_id: str
    ) -> TaskList | None:
        result = await self.conn.execute(
            query, {"id": task_list_id, "user_id": user_id}
        )
        row = result.fetchone()
        return None if row is None else _row_to_task_list(row)

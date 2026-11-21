"""SQL implementation of :class:`TaskRepository`.

Two conventions carry most of the weight here.

**One row mapper.** Every query selects ``_TASK_COLUMNS`` and every row goes
through ``_row_to_task``, so a new column cannot be added to one query and
forgotten in another — the ``_row_to_tag`` lesson from ITER17-001 Phase 1.

**Owner scoping in the SQL, not above it.** Every statement filters on
``user_id``. The link statements reach the owner through the task they belong
to via ``_require_task_owned``, so a caller holding someone else's task id
cannot read, attach to, detach from or destroy it. Because the guard runs
first, the ``bool`` the link methods return only ever means "was there a change"
and never "was that your task".
"""

from datetime import datetime
from typing import Any

from core_shared.models.tasks import (
    Task,
    TaskIcon,
    TaskListChangedConcurrentlyError,
    TaskListNotFoundError,
    TaskNotFoundError,
    TaskPage,
    TaskStatus,
    reorder_open_tasks,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.repositories import TaskRepository

# Declared once so the column list and the row -> entity mapper stay in step.
_TASK_COLUMN_NAMES = (
    "id",
    "user_id",
    "text",
    "status",
    "creating_journal_id",
    "due_journal_id",
    "task_list_id",
    "position",
    "due_date",
    "flagged",
    "icon",
    "created_at",
    "updated_at",
)

_TASK_COLUMNS = ", ".join(_TASK_COLUMN_NAMES)

# The same list qualified for the two statements that join ``journals``, where
# an unqualified ``id`` or ``user_id`` would be ambiguous.
_TASK_COLUMNS_PREFIXED = ", ".join(f"t.{column}" for column in _TASK_COLUMN_NAMES)


# The journal list's indicator. Built once at module level, with the status
# bound here rather than passed per call: it is the statement's own definition
# of a live commitment, not something a caller chooses.
_COUNT_DUE_BY_JOURNAL = text(
    """
    SELECT due_journal_id, COUNT(*) AS due_count
    FROM tasks
    WHERE due_journal_id = ANY(:ids)
      AND user_id = :user_id
      AND status = :status
    GROUP BY due_journal_id
    """
).bindparams(status=TaskStatus.NOT_DONE.value)


# The daily summary's past-day read. Built once at module level like the
# indicator above, and — unlike it — with **no status bound at all**: reporting
# how a day resolved means reporting the done and cancelled tasks too, so the
# absence of that predicate is the statement's whole point rather than an
# omission. Journal-only (``task_list_id IS NULL``): the summary leaves list
# tasks out until it learns to describe them.
_TASKS_DUE_IN_JOURNALS = text(
    f"""
    SELECT {_TASK_COLUMNS_PREFIXED}
    FROM tasks t
    JOIN journals j ON j.id = t.due_journal_id
    WHERE t.due_journal_id = ANY(:ids)
      AND t.user_id = :user_id
      AND t.task_list_id IS NULL
    ORDER BY j.event_date_range_start, t.id
    """
)


# ``closed_at`` orders a list's Completed group, most recently closed first, and
# is not on the entity. ``save`` is the only writer of a task's status, so it is
# where the close time is kept: stamped when a task enters a closed status
# (done -> cancelled included, a fresh close), cleared when it is reopened, and
# left alone by any other edit. In the UPDATE the bare ``status`` and
# ``closed_at`` on the right-hand side are the row's values *before* the write.
# ``:status`` is cast because asyncpg deduces one type per parameter, and the
# column comparison alone would deduce ``varchar`` beside the literal's ``text``.
_CLOSED_AT_ON_INSERT = (
    "CASE WHEN CAST(:status AS VARCHAR) = 'not_done' THEN NULL ELSE now() END"
)
_CLOSED_AT_ON_UPDATE = """CASE
                    WHEN CAST(:status AS VARCHAR) = 'not_done' THEN NULL
                    WHEN status IS DISTINCT FROM CAST(:status AS VARCHAR) THEN now()
                    ELSE closed_at
                END"""


# --- List membership and list reads ------------------------------------------
#
# Every statement below scopes the *tasks* to the owner as well as naming the
# list: the list foreign key is single-column, so the table would let a task
# reference another owner's list, and such a row must never be read, counted or
# moved on this owner's behalf.

# The first lock of every membership write (see the port's lock order). ``FOR
# NO KEY UPDATE``, as list renames take: joins and moves on one list queue on
# it, while a foreign-key check against the list (``KEY SHARE``) is not blocked.
_LOCK_LIST = text(
    """
    SELECT 1 FROM task_lists
    WHERE id = :task_list_id AND user_id = :user_id
    FOR NO KEY UPDATE
    """
)

# The bottom of a list: one past the owner's highest position on it, closed
# tasks included so a reopened task keeps its slot. Shared with the list-task
# insert. The casts are there because asyncpg deduces one type per parameter,
# and the parameters appear again in the statements that embed this.
_BOTTOM_OF_LIST = """(
        SELECT COALESCE(MAX(bottom.position) + 1, 0)
        FROM tasks bottom
        WHERE bottom.task_list_id = CAST(:task_list_id AS INTEGER)
          AND bottom.user_id = CAST(:user_id AS VARCHAR)
    )"""

_ADD_TO_LIST = text(
    f"""
    UPDATE tasks
    SET task_list_id = CAST(:task_list_id AS INTEGER),
        position = {_BOTTOM_OF_LIST},
        updated_at = now()
    WHERE id = :task_id AND user_id = CAST(:user_id AS VARCHAR)
    RETURNING {_TASK_COLUMNS}
    """
)

_FIND_MEMBERSHIP = text(
    "SELECT task_list_id FROM tasks WHERE id = :task_id AND user_id = :user_id"
)

# Locked in id order — the port's lock order — and sorted into display order
# afterwards, because ``FOR NO KEY UPDATE`` takes its locks in the order rows
# are returned.
_LOCK_OPEN_POSITIONS = text(
    """
    SELECT id, position FROM tasks
    WHERE task_list_id = :task_list_id
      AND user_id = :user_id
      AND status = :status
    ORDER BY id
    FOR NO KEY UPDATE
    """
).bindparams(status=TaskStatus.NOT_DONE.value)

# One statement for every moved row, as two arrays rather than a parameter per
# row. ``updated_at`` is deliberately untouched: reordering is not an edit.
_WRITE_POSITIONS = text(
    """
    UPDATE tasks
    SET position = moved.position
    FROM unnest(
        CAST(:ids AS integer[]), CAST(:positions AS integer[])
    ) AS moved(id, position)
    WHERE tasks.id = moved.id AND tasks.user_id = :user_id
    """
)

# All three list columns at once: every CHECK is row-level, and a due date may
# only sit on a list task.
_REMOVE_FROM_LIST = text(
    f"""
    UPDATE tasks
    SET task_list_id = NULL,
        position = NULL,
        due_date = NULL,
        updated_at = now()
    WHERE id = :task_id AND user_id = :user_id AND task_list_id = :task_list_id
    RETURNING {_TASK_COLUMNS}
    """
)

# Every list read requires the list to be the caller's as well as the task. The
# foreign key is single-column, so a task can point at another owner's list; a
# read of that list must still come back empty, as a read of any unowned list.
_ON_OWN_LIST = """EXISTS (
        SELECT 1 FROM task_lists owned
        WHERE owned.id = tasks.task_list_id AND owned.user_id = :user_id
    )"""

_OPEN_TASKS_ON_LIST = text(
    f"""
    SELECT {_TASK_COLUMNS}
    FROM tasks
    WHERE task_list_id = :task_list_id
      AND user_id = :user_id
      AND {_ON_OWN_LIST}
      AND status = :status
    ORDER BY position, id
    """
).bindparams(status=TaskStatus.NOT_DONE.value)

# Served by ``ix_tasks_task_list_id_closed_at``. ``closed_at`` is set on every
# closed task (``ck_tasks_closed_at_matches_status``), so it is the filter too.
_CLOSED_TASKS_ON_LIST = text(
    f"""
    SELECT {_TASK_COLUMNS}
    FROM tasks
    WHERE task_list_id = :task_list_id
      AND user_id = :user_id
      AND {_ON_OWN_LIST}
      AND closed_at IS NOT NULL
    ORDER BY closed_at DESC, id DESC
    LIMIT :limit OFFSET :offset
    """
)

# Counted separately rather than with ``COUNT(*) OVER ()``: a page past the end
# returns no rows to carry a window total, and must still report it.
_COUNT_CLOSED_TASKS_ON_LIST = text(
    f"""
    SELECT COUNT(*)
    FROM tasks
    WHERE task_list_id = :task_list_id
      AND user_id = :user_id
      AND {_ON_OWN_LIST}
      AND closed_at IS NOT NULL
    """
)

_COUNT_OPEN_BY_LIST = text(
    f"""
    SELECT task_list_id, COUNT(*) AS open_count
    FROM tasks
    WHERE task_list_id = ANY(CAST(:ids AS integer[]))
      AND user_id = :user_id
      AND {_ON_OWN_LIST}
      AND status = :status
    GROUP BY task_list_id
    """
).bindparams(status=TaskStatus.NOT_DONE.value)


def _row_to_task(row: Any) -> Task:
    """Map a ``tasks`` row to a :class:`Task` entity."""
    return Task(
        id=row.id,
        user_id=row.user_id,
        text=row.text,
        status=TaskStatus(row.status),
        creating_journal_id=row.creating_journal_id,
        due_journal_id=row.due_journal_id,
        task_list_id=row.task_list_id,
        position=row.position,
        due_date=row.due_date,
        flagged=row.flagged,
        icon=None if row.icon is None else TaskIcon(row.icon),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _icon_value(task: Task) -> str | None:
    """The stored form of a task's icon: its stable key."""
    return None if task.icon is None else task.icon.value


class SqlTaskRepository(TaskRepository):
    """SQL implementation of the task repository."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    async def save(self, task: Task) -> Task:
        """Insert a new task or update an existing one.

        Writes the task's own values — text, status, anchors, due date, flag and
        icon — but never its **list membership** (``task_list_id``,
        ``position``). Joining, leaving, moving and reordering are operations of
        their own, as ``TaskList.position`` is, so an edit carrying a stale
        position cannot undo a reorder that landed after the caller's read.

        Raises:
            ValueError: When inserting a task on a list. A list task is placed at
                the bottom of its list by the list-task creation path; inserting
                one here would store it as a journal-only task or fail a CHECK.
        """
        if task.id is None:
            return await self._insert(task)
        return await self._update(task, task.id)

    async def _insert(self, task: Task) -> Task:
        """Insert a new task, letting the database assign id and timestamps.

        Only a journal-only task reaches the INSERT. The entity allows a
        position or a due date only on a list task, so refusing list tasks
        refuses those too.
        """
        if task.task_list_id is not None:
            raise ValueError(
                "save() cannot insert a task on a list; list membership is "
                "written by the list-task operations"
            )
        query = text(
            f"""
            INSERT INTO tasks (
                user_id, text, status, creating_journal_id, due_journal_id,
                flagged, icon, closed_at
            )
            VALUES (
                :user_id, :text, :status, :creating_journal_id, :due_journal_id,
                :flagged, :icon, {_CLOSED_AT_ON_INSERT}
            )
            RETURNING {_TASK_COLUMNS}
            """
        )
        result = await self.conn.execute(
            query,
            {
                "user_id": task.user_id,
                "text": task.text,
                "status": task.status.value,
                "creating_journal_id": task.creating_journal_id,
                "due_journal_id": task.due_journal_id,
                "flagged": task.flagged,
                "icon": _icon_value(task),
            },
        )
        return _row_to_task(result.fetchone())

    async def _update(self, task: Task, task_id: int) -> Task:
        """Update an existing task in place.

        ``created_at`` is deliberately not in the SET list: when the commitment
        arose does not change because its text or status did. The creating
        anchor is likewise immutable in the product model, but it is set here
        anyway so that a caller cannot silently disagree with the stored row —
        the service layer is what refuses to change it.

        ``task_list_id`` and ``position`` are not in the SET list either, for the
        reason ``save`` gives. The due date, flag and icon are: their CHECKs are
        row-level, and the entity guarantees them against *its* view of the
        task's list — so callers save a row they read under lock, and a stale
        entity whose task has since left its list fails a CHECK rather than
        writing a shape the table forbids.

        ``closed_at`` is derived from the status change (see
        ``_CLOSED_AT_ON_UPDATE``), so an edit that leaves the status alone keeps
        a closed task's place in its list's Completed group.

        The id is passed alongside the task because ``save`` has already
        established it is not ``None``.
        """
        query = text(
            f"""
            UPDATE tasks
            SET text = :text,
                closed_at = {_CLOSED_AT_ON_UPDATE},
                status = :status,
                creating_journal_id = :creating_journal_id,
                due_journal_id = :due_journal_id,
                due_date = :due_date,
                flagged = :flagged,
                icon = :icon,
                updated_at = now()
            WHERE id = :id AND user_id = :user_id
            RETURNING {_TASK_COLUMNS}
            """
        )
        result = await self.conn.execute(
            query,
            {
                "id": task_id,
                "user_id": task.user_id,
                "text": task.text,
                "status": task.status.value,
                "creating_journal_id": task.creating_journal_id,
                "due_journal_id": task.due_journal_id,
                "due_date": task.due_date,
                "flagged": task.flagged,
                "icon": _icon_value(task),
            },
        )
        row = result.fetchone()
        if row is None:
            # The id may exist and belong to somebody else. Saying so would leak
            # its existence, so an unowned task is simply not found.
            raise TaskNotFoundError(task_id)
        return _row_to_task(row)

    async def find_by_id(self, task_id: int, user_id: str) -> Task | None:
        """Find one of the user's tasks by id."""
        query = text(
            f"""
            SELECT {_TASK_COLUMNS}
            FROM tasks
            WHERE id = :task_id AND user_id = :user_id
            """
        )
        result = await self.conn.execute(
            query, {"task_id": task_id, "user_id": user_id}
        )
        row = result.fetchone()
        return None if row is None else _row_to_task(row)

    async def find_by_id_for_update(self, task_id: int, user_id: str) -> Task | None:
        """Find one of the user's tasks and lock the row against other writers.

        ``FOR NO KEY UPDATE`` rather than ``FOR UPDATE``: it blocks the other
        writers this is here to exclude, but not the ``FOR KEY SHARE`` that a
        link insert's foreign-key check takes on this same row — so attaching a
        contact to a task never queues behind somebody marking it done.

        The lock is released when the transaction ends, which is why callers
        must already be inside their unit of work when they call this. A read
        outside one would take the lock and drop it immediately, leaving the
        window it exists to close.
        """
        query = text(
            f"""
            SELECT {_TASK_COLUMNS}
            FROM tasks
            WHERE id = :task_id AND user_id = :user_id
            FOR NO KEY UPDATE
            """
        )
        result = await self.conn.execute(
            query, {"task_id": task_id, "user_id": user_id}
        )
        row = result.fetchone()
        return None if row is None else _row_to_task(row)

    async def delete(self, task_id: int, user_id: str) -> int | None:
        """Hard-delete one of the user's tasks, answering the list it was on.

        Both link tables cascade from ``task_id``, so the links go with it and
        the journals and contacts they pointed at are untouched.
        """
        query = text(
            "DELETE FROM tasks WHERE id = :task_id AND user_id = :user_id "
            "RETURNING task_list_id"
        )
        result = await self.conn.execute(
            query, {"task_id": task_id, "user_id": user_id}
        )
        row = result.one_or_none()
        if row is None:
            raise TaskNotFoundError(task_id)
        return None if row.task_list_id is None else int(row.task_list_id)

    async def add_intermediate_journal(
        self, task_id: int, journal_id: int, user_id: str
    ) -> bool:
        """Link a journal to the task as an intermediate journal."""
        await self._require_task_owned(task_id, user_id)
        return await self._add_link(
            table="task_intermediate_journals",
            column="journal_id",
            task_id=task_id,
            linked_id=journal_id,
        )

    async def remove_intermediate_journal(
        self, task_id: int, journal_id: int, user_id: str
    ) -> bool:
        """Remove an intermediate-journal link."""
        await self._require_task_owned(task_id, user_id)
        return await self._remove_link(
            table="task_intermediate_journals",
            column="journal_id",
            task_id=task_id,
            linked_id=journal_id,
        )

    async def list_intermediate_journal_ids(
        self, task_id: int, user_id: str
    ) -> list[int]:
        """List the ids of the task's intermediate journals."""
        return await self._list_links(
            table="task_intermediate_journals",
            column="journal_id",
            task_id=task_id,
            user_id=user_id,
        )

    async def add_contacts(
        self, task_id: int, contact_ids: list[int], user_id: str
    ) -> list[int]:
        """Link contacts to the task, with one guard and one insert.

        The guard runs even for an empty list: the port promises
        ``TaskNotFoundError`` for a task that is not the caller's, and an empty
        request is still a claim of ownership.
        """
        await self._require_task_owned(task_id, user_id)
        return await self._add_contact_links(task_id, contact_ids)

    async def remove_contact(self, task_id: int, contact_id: int, user_id: str) -> bool:
        """Remove a contact link."""
        await self._require_task_owned(task_id, user_id)
        return await self._remove_link(
            table="task_contacts",
            column="contact_id",
            task_id=task_id,
            linked_id=contact_id,
        )

    async def list_contact_ids(self, task_id: int, user_id: str) -> list[int]:
        """List the ids of the contacts the task references."""
        return await self._list_links(
            table="task_contacts",
            column="contact_id",
            task_id=task_id,
            user_id=user_id,
        )

    async def find_tasks_for_journal(self, journal_id: int, user_id: str) -> list[Task]:
        """Find every one of the user's tasks linked to a journal, in any role.

        One statement for all three link shapes. The mention arm is an
        ``EXISTS`` rather than a join precisely so a task that is both an anchor
        and a mention — which a retarget onto an already-attached journal
        produces — comes back as one row instead of two; a join would duplicate
        it and the read model would be assembled twice for the same task.

        Owner scoping is on ``tasks`` itself, which is the only table here that
        carries a ``user_id``. The journal id is not checked for ownership: a
        journal that is not the caller's anchors none of the caller's tasks, so
        the filter is redundant, and the surfaces resolve the journal separately
        anyway to tell "no tasks here" from "not your journal".
        """
        query = text(
            f"""
            SELECT {_TASK_COLUMNS}
            FROM tasks t
            WHERE t.user_id = :user_id
              AND (
                    t.creating_journal_id = :journal_id
                 OR t.due_journal_id = :journal_id
                 OR EXISTS (
                        SELECT 1
                        FROM task_intermediate_journals link
                        WHERE link.task_id = t.id
                          AND link.journal_id = :journal_id
                    )
              )
            ORDER BY t.id
            """
        )
        result = await self.conn.execute(
            query, {"journal_id": journal_id, "user_id": user_id}
        )
        return [_row_to_task(row) for row in result.fetchall()]

    async def find_upcoming_tasks(
        self,
        user_id: str,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> list[Task]:
        """Find the user's not-done journal-only tasks due inside a window.

        **Journal-only** (``task_list_id IS NULL``): the dashboard, the
        ``list_upcoming_tasks`` tool and the daily summary leave list tasks out
        until they learn to show them, even a list task due in a journal inside
        the window.

        One of two joins to ``journals`` in this repository, and an inner one on
        the due anchor. A journal-only task always has its due journal — a
        ``CHECK`` requires both anchors without a list — and the foreign key is
        ``ON DELETE RESTRICT``, so every row selected has exactly one journal to
        match and the join can neither drop a task nor duplicate one.

        The journal is not owner-scoped, matching ``find_tasks_for_journal``'s
        reasoning: the task already is, and a task of the caller's cannot be
        anchored to somebody else's journal — the service refuses to write one.
        Adding the predicate would suggest it were load-bearing.

        ``BETWEEN`` is inclusive at both ends, which is what makes a task due at
        any hour of the last day part of the window; the caller supplies that
        day's final microsecond for exactly that reason.

        The order is the due journal's start, then the task id. The second term
        is what makes it **total**: a day's journal commonly holds several
        tasks, all sharing one start, and without a tie-break the same request
        could come back in a different order between runs.
        """
        query = text(
            f"""
            SELECT {_TASK_COLUMNS_PREFIXED}
            FROM tasks t
            JOIN journals j ON j.id = t.due_journal_id
            WHERE t.user_id = :user_id
              AND t.status = :status
              AND t.task_list_id IS NULL
              AND j.event_date_range_start BETWEEN :window_start AND :window_end
            ORDER BY j.event_date_range_start, t.id
            """
        )
        result = await self.conn.execute(
            query,
            {
                "user_id": user_id,
                "status": TaskStatus.NOT_DONE.value,
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        return [_row_to_task(row) for row in result.fetchall()]

    async def find_tasks_due_in_journals(
        self, journal_ids: list[int], user_id: str
    ) -> list[Task]:
        """The user's journal-only tasks due in any of these journals, in every status.

        **Journal-only** (``task_list_id IS NULL``), as :meth:`find_upcoming_tasks`
        is: the daily summary reads this and leaves list tasks out.

        The second join to ``journals`` in this repository and, like
        :meth:`find_upcoming_tasks`'s, an inner one on the due anchor, which
        every row it selects has (the ids name it). Here it earns its place for the
        **order** rather than for the filter — the ids alone already select the
        rows — so that a day's tasks come back in the day's own sequence.

        The ids go in as a single ``integer[]`` rather than a bind parameter
        each, following :data:`_COUNT_DUE_BY_JOURNAL`: the parameter count stays
        at one whatever the day holds.
        """
        if not journal_ids:
            return []

        result = await self.conn.execute(
            _TASKS_DUE_IN_JOURNALS, {"ids": journal_ids, "user_id": user_id}
        )
        return [_row_to_task(row) for row in result.fetchall()]

    async def list_intermediate_journal_ids_for_tasks(
        self, task_ids: list[int], user_id: str
    ) -> dict[int, list[int]]:
        """List several tasks' intermediate journals in one statement."""
        return await self._list_links_for_tasks(
            table="task_intermediate_journals",
            column="journal_id",
            task_ids=task_ids,
            user_id=user_id,
        )

    async def list_contact_ids_for_tasks(
        self, task_ids: list[int], user_id: str
    ) -> dict[int, list[int]]:
        """List several tasks' contact links in one statement."""
        return await self._list_links_for_tasks(
            table="task_contacts",
            column="contact_id",
            task_ids=task_ids,
            user_id=user_id,
        )

    async def count_not_done_tasks_by_due_journal(
        self, journal_ids: list[int], user_id: str
    ) -> dict[int, int]:
        """How many not-done tasks are due in each of these journals.

        One statement over the whole page. The ids go in as a single
        ``integer[]`` rather than a bind parameter each, following
        ``find_cancelled_journal_ids``: the parameter count stays at one
        whatever the page size, so a listing cannot walk into asyncpg's argument
        limit.

        ``GROUP BY`` is what makes a journal with nothing due absent from the
        result rather than present with a zero — no row is produced for a group
        with no members — which is the contract the port states.
        """
        if not journal_ids:
            return {}

        result = await self.conn.execute(
            _COUNT_DUE_BY_JOURNAL, {"ids": journal_ids, "user_id": user_id}
        )
        return {int(row.due_journal_id): int(row.due_count) for row in result}

    async def add_to_list(self, task_id: int, task_list_id: int, user_id: str) -> Task:
        """Put one of the user's tasks at the bottom of one of their lists.

        The list is locked first and the task's row second, by the ``UPDATE``
        itself — the port's lock order — so the bottom cannot be computed twice
        for one list by overlapping joins.
        """
        await self._lock_list(task_list_id, user_id)
        result = await self.conn.execute(
            _ADD_TO_LIST,
            {"task_id": task_id, "task_list_id": task_list_id, "user_id": user_id},
        )
        row = result.fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        return _row_to_task(row)

    async def move_within_list(
        self, task_id: int, user_id: str, *, after_task_id: int | None
    ) -> list[Task]:
        """Move an open task after another on its list, or to the top.

        Reads which list the task is on without a lock, locks that list, then
        locks its open tasks in id order and re-checks both the task and its
        neighbour among them — either one closed or moved in between is refused
        as a conflict rather than moved.
        """
        task_list_id = await self._require_list_membership(task_id, user_id)
        await self._lock_list(task_list_id, user_id)

        rows = (
            await self.conn.execute(
                _LOCK_OPEN_POSITIONS,
                {"task_list_id": task_list_id, "user_id": user_id},
            )
        ).fetchall()
        order = sorted(
            ((int(row.id), int(row.position)) for row in rows),
            key=lambda pair: (pair[1], pair[0]),
        )
        # Plain edits lock only their task, so either task may have closed or
        # left the list while this waited for the locks: a conflict to re-read
        # and retry, not a caller's bug.
        open_ids = {open_id for open_id, _ in order}
        for named in (task_id, after_task_id):
            if named is not None and named not in open_ids:
                raise TaskListChangedConcurrentlyError(named)

        moved = reorder_open_tasks(order, task_id, after_task_id)
        if moved:
            await self.conn.execute(
                _WRITE_POSITIONS,
                {
                    "ids": list(moved),
                    "positions": list(moved.values()),
                    "user_id": user_id,
                },
            )
        return await self.find_open_tasks_on_list(task_list_id, user_id)

    async def remove_from_list(self, task_id: int, user_id: str) -> Task:
        """Take one of the user's tasks off its list.

        The ``UPDATE`` names the list it locked, so a task that moved to another
        list in between is not taken off that one under the wrong lock.
        """
        task_list_id = await self._require_list_membership(task_id, user_id)
        await self._lock_list(task_list_id, user_id)
        result = await self.conn.execute(
            _REMOVE_FROM_LIST,
            {"task_id": task_id, "user_id": user_id, "task_list_id": task_list_id},
        )
        row = result.fetchone()
        if row is None:
            # It left this list between the unlocked read and the lock.
            raise TaskListChangedConcurrentlyError(task_id)
        return _row_to_task(row)

    async def find_open_tasks_on_list(
        self, task_list_id: int, user_id: str
    ) -> list[Task]:
        """The user's not-done tasks on a list, in ``(position, id)`` order."""
        result = await self.conn.execute(
            _OPEN_TASKS_ON_LIST, {"task_list_id": task_list_id, "user_id": user_id}
        )
        return [_row_to_task(row) for row in result.fetchall()]

    async def find_closed_tasks_on_list(
        self, task_list_id: int, user_id: str, *, limit: int, offset: int = 0
    ) -> TaskPage:
        """One page of a list's closed tasks, most recently closed first."""
        if limit < 1:
            raise ValueError(f"limit must be at least 1, not {limit}")
        if offset < 0:
            raise ValueError(f"offset must be at least 0, not {offset}")

        scope = {"task_list_id": task_list_id, "user_id": user_id}
        rows = (
            await self.conn.execute(
                _CLOSED_TASKS_ON_LIST, {**scope, "limit": limit, "offset": offset}
            )
        ).fetchall()
        total = (
            await self.conn.execute(_COUNT_CLOSED_TASKS_ON_LIST, scope)
        ).scalar_one()
        return TaskPage(tasks=tuple(_row_to_task(row) for row in rows), total=total)

    async def count_open_tasks_by_list(
        self, task_list_ids: list[int], user_id: str
    ) -> dict[int, int]:
        """How many not-done tasks each list holds; lists with none are absent."""
        if not task_list_ids:
            return {}

        result = await self.conn.execute(
            _COUNT_OPEN_BY_LIST,
            {"ids": list(dict.fromkeys(task_list_ids)), "user_id": user_id},
        )
        return {int(row.task_list_id): int(row.open_count) for row in result}

    async def _lock_list(self, task_list_id: int, user_id: str) -> None:
        """Lock one of the user's lists — the first lock of a membership write."""
        result = await self.conn.execute(
            _LOCK_LIST, {"task_list_id": task_list_id, "user_id": user_id}
        )
        if result.fetchone() is None:
            raise TaskListNotFoundError(task_list_id)

    async def _require_list_membership(self, task_id: int, user_id: str) -> int:
        """The list one of the user's tasks is on, read without a lock.

        Unlocked on purpose: the list must be locked before the task (the port's
        lock order), and which list to lock is what this finds out. Callers
        re-check the answer once they hold the list.

        Raises:
            TaskNotFoundError: When the task is not one of the user's.
            ValueError: When the task is on no list.
        """
        row = (
            await self.conn.execute(
                _FIND_MEMBERSHIP, {"task_id": task_id, "user_id": user_id}
            )
        ).fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        if row.task_list_id is None:
            raise ValueError(f"task {task_id} is not on a list")
        return int(row.task_list_id)

    async def _require_task_owned(self, task_id: int, user_id: str) -> None:
        """Fail unless the task exists and belongs to the acting user.

        The link tables carry no ``user_id`` of their own, so this is where
        owner scoping enters every link **write**. It runs before the statement
        it guards, which is what lets those statements report "already linked"
        with a plain ``False``.

        The read methods do not come through here. They scope themselves inside
        their own statement (see :meth:`_list_links`), because the lock below is
        the only thing this adds that a read cannot get from a join — and a read
        has nothing to lock against.

        ``FOR KEY SHARE`` closes the window between this check and the statement
        it guards. Without it a concurrent transaction could delete the task in
        between, and the guarded statement would surface a raw foreign-key
        violation — or a bare ``False``/``[]`` — instead of the
        ``TaskNotFoundError`` the port promises. `FOR KEY SHARE` is the weakest
        lock that blocks a delete: a concurrent update of the task's text or
        status is still free to proceed, and it is the same lock the link
        insert's own foreign-key check takes on the parent row anyway.
        """
        query = text(
            """
            SELECT 1 FROM tasks
            WHERE id = :task_id AND user_id = :user_id
            FOR KEY SHARE
            """
        )
        result = await self.conn.execute(
            query, {"task_id": task_id, "user_id": user_id}
        )
        if result.fetchone() is None:
            raise TaskNotFoundError(task_id)

    async def _add_link(
        self, *, table: str, column: str, task_id: int, linked_id: int
    ) -> bool:
        """Insert a link row idempotently.

        Both link tables have a composite primary key over ``(task_id, <the
        linked id>)``, so ``ON CONFLICT DO NOTHING`` turns a retry into a no-op
        instead of an integrity error, and the ``RETURNING`` clause reports
        whether a row was actually created.

        ``table`` and ``column`` are interpolated rather than bound because
        identifiers cannot be bound parameters; both are literals chosen by this
        module and never derived from a caller's input.
        """
        query = text(
            f"""
            INSERT INTO {table} (task_id, {column})
            VALUES (:task_id, :linked_id)
            ON CONFLICT (task_id, {column}) DO NOTHING
            RETURNING task_id
            """
        )
        result = await self.conn.execute(
            query, {"task_id": task_id, "linked_id": linked_id}
        )
        return result.fetchone() is not None

    async def _add_contact_links(
        self, task_id: int, contact_ids: list[int]
    ) -> list[int]:
        """Insert every contact link in one statement, idempotently.

        The same ``ON CONFLICT (task_id, contact_id) DO NOTHING`` the singular
        insert used, so *N* contacts cost one round trip instead of *N*, and
        ``RETURNING`` reports which rows were actually created — how a caller
        tells a fresh link from one that was already there.

        **The ids travel as one array parameter, not one placeholder each.**
        The first version of this built a multi-row ``VALUES`` list with a bind
        parameter per contact, which is correct right up until there are 32,767
        of them: that is asyncpg's hard limit on query arguments, and exceeding
        it raises an ``InterfaceError`` the caller sees as a 500 — for a request
        that was entirely valid. The specification says a task may reference
        *any number* of contacts, so the mechanism has to mean it rather than
        the surface quietly capping it. ``unnest`` over a single ``integer[]``
        costs two parameters whatever *N* is. Raised by the pull request's
        automated review.

        Duplicate ids are collapsed first: they would be harmless under
        ``DO NOTHING`` but would make the returned list depend on how many times
        an id was named.

        **The ids are inserted in the order given, and that is not an accident
        waiting to happen — yet.** ``ON CONFLICT DO NOTHING`` takes its
        speculative-insert locks in row order, which ``unnest`` takes from the
        array, so two transactions linking overlapping contact sets to the
        *same* task in opposite orders could deadlock. Unreachable today: the
        only batched caller is ``TaskService.create_task``, whose task id was
        assigned a statement earlier and so cannot be the subject of a
        concurrent call, and the single-contact link surface sends one id.
        Sorting would close it and would also break the first-mention order
        ``create_task`` promises, so the trade is left to whichever phase adds a
        second batched caller.
        """
        wanted = list(dict.fromkeys(contact_ids))
        if not wanted:
            return []

        query = text(
            """
            INSERT INTO task_contacts (task_id, contact_id)
            SELECT :task_id, contact_id
            FROM unnest(CAST(:contact_ids AS integer[])) AS contact_id
            ON CONFLICT (task_id, contact_id) DO NOTHING
            RETURNING contact_id
            """
        )
        result = await self.conn.execute(
            query, {"task_id": task_id, "contact_ids": wanted}
        )
        return [int(row[0]) for row in result.fetchall()]

    async def _remove_link(
        self, *, table: str, column: str, task_id: int, linked_id: int
    ) -> bool:
        """Delete a link row, reporting whether one was there."""
        query = text(
            f"""
            DELETE FROM {table}
            WHERE task_id = :task_id AND {column} = :linked_id
            """
        )
        result = await self.conn.execute(
            query, {"task_id": task_id, "linked_id": linked_id}
        )
        return result.rowcount > 0

    async def _list_links(
        self, *, table: str, column: str, task_id: int, user_id: str
    ) -> list[int]:
        """List a task's link ids, oldest link first, in one statement.

        Unlike the methods that *write* a link, this does its own owner scoping
        rather than calling :meth:`_require_task_owned` first. The guard exists
        to hold a window shut with ``FOR KEY SHARE``, and a read has no window:
        it writes nothing, so there is no foreign-key violation for a concurrent
        delete to turn the promised ``TaskNotFoundError`` into.

        What the guard also did here was tell two empty results apart — the link
        tables carry no ``user_id``, so a bare ``WHERE task_id = ?`` returns
        nothing both for a task that is not the caller's and for one of theirs
        with no links, and the port must raise for the first and return ``[]``
        for the second. The ``LEFT JOIN`` answers that from one round trip:
        driving from ``tasks`` means an unowned or absent task produces **no**
        rows, while an owned one with no links produces exactly one, with a null
        id.
        """
        query = text(
            f"""
            SELECT link.{column}
            FROM tasks t
            LEFT JOIN {table} link ON link.task_id = t.id
            WHERE t.id = :task_id AND t.user_id = :user_id
            ORDER BY link.created_at, link.{column}
            """
        )
        result = await self.conn.execute(
            query, {"task_id": task_id, "user_id": user_id}
        )
        rows = result.fetchall()
        if not rows:
            raise TaskNotFoundError(task_id)
        return [int(row[0]) for row in rows if row[0] is not None]

    async def _list_links_for_tasks(
        self,
        *,
        table: str,
        column: str,
        task_ids: list[int],
        user_id: str,
    ) -> dict[int, list[int]]:
        """List many tasks' link ids in one statement, keyed by task.

        An **inner** join, unlike the singular read's ``LEFT JOIN``. That one
        drives from ``tasks`` so it can tell an unowned task from an owned one
        with no links, because it must raise for the first and return ``[]`` for
        the second. This one owes no such distinction: it is given ids an
        owner-scoped query produced, and a task with no links is simply absent
        from the mapping. So the join exists only to reach the owner — the link
        tables carry no ``user_id`` of their own — and an unowned id contributes
        no rows and therefore no key.

        **The ids travel as one array parameter**, for the reason
        ``_add_contact_links`` does: a placeholder per id hits asyncpg's 32,767
        argument limit as an ``InterfaceError``, and a journal's task list has
        no ceiling of its own. ``= ANY`` over a single ``integer[]`` costs two
        parameters whatever the count.

        The order is ``created_at`` then the linked id, matching the singular
        read exactly. The second term is what makes it a **total** order:
        ``created_at`` defaults to ``transaction_timestamp()``, so every link
        written in one request ties, and a batch returning them in whatever
        order PostgreSQL found would let the same read answer differently
        between runs.
        """
        if not task_ids:
            return {}

        query = text(
            f"""
            SELECT link.task_id, link.{column}
            FROM {table} link
            JOIN tasks t ON t.id = link.task_id
            WHERE t.user_id = :user_id
              AND link.task_id = ANY(CAST(:task_ids AS integer[]))
            ORDER BY link.task_id, link.created_at, link.{column}
            """
        )
        result = await self.conn.execute(
            query, {"task_ids": list(dict.fromkeys(task_ids)), "user_id": user_id}
        )

        links: dict[int, list[int]] = {}
        for task_id, linked_id in result.fetchall():
            links.setdefault(int(task_id), []).append(int(linked_id))
        return links

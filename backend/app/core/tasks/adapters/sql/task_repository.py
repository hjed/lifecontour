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

from typing import Any

from core_shared.models.tasks import Task, TaskNotFoundError, TaskStatus
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
    "created_at",
    "updated_at",
)

_TASK_COLUMNS = ", ".join(_TASK_COLUMN_NAMES)


def _row_to_task(row: Any) -> Task:
    """Map a ``tasks`` row to a :class:`Task` entity."""
    return Task(
        id=row.id,
        user_id=row.user_id,
        text=row.text,
        status=TaskStatus(row.status),
        creating_journal_id=row.creating_journal_id,
        due_journal_id=row.due_journal_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlTaskRepository(TaskRepository):
    """SQL implementation of the task repository."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    async def save(self, task: Task) -> Task:
        """Insert a new task or update an existing one."""
        if task.id is None:
            return await self._insert(task)
        return await self._update(task, task.id)

    async def _insert(self, task: Task) -> Task:
        """Insert a new task, letting the database assign id and timestamps."""
        query = text(
            f"""
            INSERT INTO tasks (
                user_id, text, status, creating_journal_id, due_journal_id
            )
            VALUES (
                :user_id, :text, :status, :creating_journal_id, :due_journal_id
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

        The id is passed alongside the task because ``save`` has already
        established it is not ``None``.
        """
        query = text(
            f"""
            UPDATE tasks
            SET text = :text,
                status = :status,
                creating_journal_id = :creating_journal_id,
                due_journal_id = :due_journal_id,
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

    async def delete(self, task_id: int, user_id: str) -> None:
        """Hard-delete one of the user's tasks.

        Both link tables cascade from ``task_id``, so the links go with it and
        the journals and contacts they pointed at are untouched.
        """
        query = text("DELETE FROM tasks WHERE id = :task_id AND user_id = :user_id")
        result = await self.conn.execute(
            query, {"task_id": task_id, "user_id": user_id}
        )
        if result.rowcount == 0:
            raise TaskNotFoundError(task_id)

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

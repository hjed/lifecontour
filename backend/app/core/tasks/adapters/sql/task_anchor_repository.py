"""SQL implementation of :class:`TaskAnchorRepository`.

One statement answers the whole question. Both anchors are matched in a single
``WHERE`` — each is indexed — and both are joined back to ``journals`` under
their own alias, because the journal a blocking task can be actioned from is
whichever anchor is *not* being deleted, and the query cannot know which that is
until the rule has run. Fetching both titles up front is what makes the guard one
query rather than one per task.

The adapter deliberately decides nothing: which roles block, which anchor
supplies the action journal, and whether a row blocks at all are the journal
domain's rule (:mod:`core_shared.models.journals.task_anchor`), applied to each
row here.
"""

from typing import Any

from core_shared.models.journals import BlockingTask, blocking_task_from_anchors
from core_shared.models.tasks import TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.repositories import TaskAnchorRepository

# ORDER BY t.id keeps the enumeration in the failure message stable: without it
# PostgreSQL is free to return the rows in whatever order the plan produces.
_FIND_ANCHORED = text("""
    SELECT
        t.id,
        t.text,
        t.status,
        t.creating_journal_id,
        creating.title AS creating_journal_title,
        t.due_journal_id,
        due.title AS due_journal_title
    FROM tasks t
    JOIN journals creating ON creating.id = t.creating_journal_id
    JOIN journals due ON due.id = t.due_journal_id
    WHERE t.creating_journal_id = :journal_id OR t.due_journal_id = :journal_id
    ORDER BY t.id
""")


class SqlTaskAnchorRepository(TaskAnchorRepository):
    """SQL implementation of the task anchor repository."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    async def find_tasks_anchored_to_journal(
        self, journal_id: int
    ) -> list[BlockingTask]:
        """Find every task this journal is the creating or due journal of."""
        result = await self.conn.execute(_FIND_ANCHORED, {"journal_id": journal_id})
        blockers = (
            self._to_blocking_task(row, journal_id) for row in result.fetchall()
        )
        return [blocker for blocker in blockers if blocker is not None]

    @staticmethod
    def _to_blocking_task(row: Any, journal_id: int) -> BlockingTask | None:
        """Apply the journal domain's rule to one row."""
        return blocking_task_from_anchors(
            deleted_journal_id=journal_id,
            task_id=row.id,
            text=row.text,
            status=TaskStatus(row.status),
            creating_journal_id=row.creating_journal_id,
            creating_journal_title=row.creating_journal_title,
            due_journal_id=row.due_journal_id,
            due_journal_title=row.due_journal_title,
        )

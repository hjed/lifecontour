"""Migration test for 0147 (``tasks.closed_at``).

A list's Completed group shows done and cancelled tasks most recently closed
first, so a task records when it was closed:

- upgrade ``0146 -> 0147`` adds ``closed_at``, its CHECK and the Completed
  index, backfilling ``closed_at`` from ``updated_at`` for every task already
  done or cancelled and leaving not-done tasks null;
- ``ck_tasks_closed_at_matches_status`` refuses a closed task with no close time
  and a not-done task with one;
- downgrade ``0147 -> 0146`` removes all of it, and the upgrade re-runs.

Runs against an isolated throwaway database so the shared session DB is
untouched; each refused statement runs in its own connection, so a failure
cannot poison the next step.
"""

from datetime import datetime

import pytest
from sqlalchemy.engine import URL

from tests.integration.migration_helpers import RunAlembic, execute, index_exists
from tests.integration.migration_helpers import columns as _columns
from tests.integration.tasks.task_seeding import USER_ID

_TABLE = "tasks"
_INDEX = "ix_tasks_task_list_id_closed_at"
_CHECK = "ck_tasks_closed_at_matches_status"

_INSERT_JOURNAL = """
    INSERT INTO journals (title, content, user_id,
        event_date_range_start, event_date_range_end)
    VALUES ('Anchor', '', :owner, '2026-12-01', '2026-12-01')
    RETURNING id
"""
_INSERT_TASK = """
    INSERT INTO tasks (user_id, text, status, creating_journal_id, due_journal_id,
                       updated_at)
    VALUES (:owner, 'Return the book', :status, :journal_id, :journal_id,
            :updated_at)
    RETURNING id
"""
_CLOSED_AT = "SELECT closed_at FROM tasks WHERE id = :id"
_UPDATED_AT = datetime.fromisoformat("2025-03-04T05:06:07+00:00")


async def _seed(url: str, status: str) -> int:
    journal_id = await execute(url, _INSERT_JOURNAL, {"owner": USER_ID})
    task_id: int = await execute(
        url,
        _INSERT_TASK,
        {
            "owner": USER_ID,
            "status": status,
            "journal_id": journal_id,
            "updated_at": _UPDATED_AT,
        },
    )
    return task_id


@pytest.mark.integration
@pytest.mark.slow
class TestTaskClosedAtMigration:
    """0147 records when a task was closed without losing any existing task."""

    async def test_upgrade_backfills_closed_tasks_and_downgrade_removes_it(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        run_alembic(url, "upgrade", "0146")
        assert "closed_at" not in await _columns(url, _TABLE)
        open_id = await _seed(url, "not_done")
        done_id = await _seed(url, "done")
        cancelled_id = await _seed(url, "cancelled")

        run_alembic(url, "upgrade", "0147")
        assert "closed_at" in await _columns(url, _TABLE)
        assert await index_exists(url, _INDEX)
        assert await execute(url, _CLOSED_AT, {"id": open_id}) is None
        assert await execute(url, _CLOSED_AT, {"id": done_id}) == _UPDATED_AT
        assert await execute(url, _CLOSED_AT, {"id": cancelled_id}) == _UPDATED_AT

        run_alembic(url, "downgrade", "0146")
        assert "closed_at" not in await _columns(url, _TABLE)
        assert not await index_exists(url, _INDEX)

        run_alembic(url, "upgrade", "0147")
        assert "closed_at" in await _columns(url, _TABLE)
        # The second upgrade backfills again from the surviving rows.
        assert await execute(url, _CLOSED_AT, {"id": done_id}) == _UPDATED_AT

    async def test_a_closed_task_without_a_close_time_is_refused(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0147")
        task_id = await _seed(url, "not_done")

        with pytest.raises(Exception, match=_CHECK):
            await execute(
                url, "UPDATE tasks SET status = 'done' WHERE id = :id", {"id": task_id}
            )

    async def test_an_open_task_with_a_close_time_is_refused(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0147")
        task_id = await _seed(url, "not_done")

        with pytest.raises(Exception, match=_CHECK):
            await execute(
                url,
                "UPDATE tasks SET closed_at = now() WHERE id = :id",
                {"id": task_id},
            )

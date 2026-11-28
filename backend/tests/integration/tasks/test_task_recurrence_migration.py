"""Migration round-trip test for 0150 (recurrence on tasks).

- upgrade ``0149 -> 0150`` adds the recurrence columns and their two indexes;
- a task stored before the upgrade survives it, not recurring and a copy of
  nothing;
- downgrade ``0150 -> 0149`` removes all of it, and the upgrade re-runs;
- the downgrade **refuses** while any task recurs or records the task it came
  from, rather than silently discarding either.

Constraint behaviour is covered against the session database in
``test_task_recurrence_constraints.py``. Runs against an isolated throwaway
database so the shared session DB is untouched.
"""

import pytest
from sqlalchemy.engine import URL

from tests.integration.migration_helpers import RunAlembic, execute, index_exists
from tests.integration.migration_helpers import columns as _columns
from tests.integration.tasks.task_seeding import USER_ID

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_TABLE = "tasks"
_INDEXES = ("ix_tasks_recurrence_of_task_id", "ix_tasks_recurrence_series_id")
_NEW_COLUMNS = {
    "recurrence_mode",
    "recurrence_interval_count",
    "recurrence_interval_unit",
    "recurrence_series_id",
    "recurrence_of_task_id",
}

_INSERT_LIST = """
    INSERT INTO task_lists (user_id, name, position)
    VALUES (:owner, 'Chores', 0)
    RETURNING id
"""
_INSERT_LIST_TASK = """
    INSERT INTO tasks (user_id, text, task_list_id, position)
    VALUES (:owner, 'Water the plants', :list_id, 0)
    RETURNING id
"""
_RECURRENCE = """
    SELECT ROW(recurrence_mode, recurrence_interval_count,
               recurrence_interval_unit, recurrence_series_id,
               recurrence_of_task_id)::text
    FROM tasks WHERE id = :id
"""


async def _seed_list_task(url: str) -> int:
    list_id = await execute(url, _INSERT_LIST, {"owner": USER_ID})
    task_id: int = await execute(
        url, _INSERT_LIST_TASK, {"owner": USER_ID, "list_id": list_id}
    )
    return task_id


async def _indexes_exist(url: str) -> list[bool]:
    return [await index_exists(url, index) for index in _INDEXES]


class TestTaskRecurrenceMigration:
    """0150 adds recurrence without touching an existing task."""

    async def test_upgrade_adds_the_columns_and_downgrade_removes_them(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        run_alembic(url, "upgrade", "0149")
        assert not _NEW_COLUMNS & await _columns(url, _TABLE)
        task_id = await _seed_list_task(url)

        run_alembic(url, "upgrade", "0150")
        assert _NEW_COLUMNS <= await _columns(url, _TABLE)
        assert await _indexes_exist(url) == [True, True]
        assert await execute(url, _RECURRENCE, {"id": task_id}) == "(,,,,)"

        run_alembic(url, "downgrade", "0149")
        assert not _NEW_COLUMNS & await _columns(url, _TABLE)
        assert await _indexes_exist(url) == [False, False]

        run_alembic(url, "upgrade", "0150")
        assert _NEW_COLUMNS <= await _columns(url, _TABLE)

    async def test_downgrade_is_refused_while_a_task_recurs(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0150")
        task_id = await _seed_list_task(url)
        await execute(
            url,
            "UPDATE tasks SET recurrence_mode = 'no_date' WHERE id = :id",
            {"id": task_id},
        )

        with pytest.raises(RuntimeError, match="cannot be downgraded"):
            run_alembic(url, "downgrade", "0149")

        assert await execute(url, _RECURRENCE, {"id": task_id}) == "(no_date,,,,)"

    async def test_downgrade_is_refused_while_a_task_records_its_original(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """A copy whose own recurrence has since been cleared still has a past."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0150")
        original_id = await _seed_list_task(url)
        copy_id = await _seed_list_task(url)
        await execute(
            url,
            "UPDATE tasks SET recurrence_of_task_id = :original WHERE id = :id",
            {"original": original_id, "id": copy_id},
        )

        with pytest.raises(RuntimeError, match="cannot be downgraded"):
            run_alembic(url, "downgrade", "0149")

        assert (
            await execute(
                url,
                "SELECT recurrence_of_task_id FROM tasks WHERE id = :id",
                {"id": copy_id},
            )
            == original_id
        )

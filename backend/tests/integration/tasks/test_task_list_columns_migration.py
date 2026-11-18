"""Migration round-trip test for 0146 (list columns and relaxed anchors on tasks).

- upgrade ``0145 -> 0146`` adds ``task_list_id``, ``position``, ``due_date``,
  ``flagged`` and ``icon``, relaxes both journal anchors to nullable and adds the
  ``(task_list_id, position)`` index;
- a journal-only task stored before the upgrade survives it unchanged, unflagged
  and on no list;
- downgrade ``0146 -> 0145`` removes all of it and restores ``NOT NULL``;
- re-running the upgrade after the downgrade works (re-runnable);
- the downgrade **refuses** while any task holds something the 0145 schema
  cannot represent, rather than silently discarding it.

Constraint behaviour is covered against the session database in
``test_task_list_columns_constraints.py``. Runs against an isolated throwaway
database so the shared session DB is untouched.
"""

import pytest
from sqlalchemy.engine import URL

from tests.integration.migration_helpers import RunAlembic, execute, index_exists
from tests.integration.migration_helpers import columns as _columns
from tests.integration.tasks.task_seeding import USER_ID

_TABLE = "tasks"
_INDEX = "ix_tasks_task_list_id_position"
_NEW_COLUMNS = {"task_list_id", "position", "due_date", "flagged", "icon"}
_ANCHORS = ("creating_journal_id", "due_journal_id")

_INSERT_JOURNAL = """
    INSERT INTO journals (title, content, user_id,
        event_date_range_start, event_date_range_end)
    VALUES ('Anchor', '', :owner, '2026-12-01', '2026-12-01')
    RETURNING id
"""
_INSERT_JOURNAL_ONLY_TASK = """
    INSERT INTO tasks (user_id, text, creating_journal_id, due_journal_id)
    VALUES (:owner, 'Return the book', :journal_id, :journal_id)
    RETURNING id
"""
_INSERT_LIST = """
    INSERT INTO task_lists (user_id, name, position)
    VALUES (:owner, 'Packing', 0)
    RETURNING id
"""
_NULLABLE = """
    SELECT is_nullable FROM information_schema.columns
    WHERE table_name = 'tasks' AND column_name = :column
"""


async def _is_nullable(url: str, column: str) -> bool:
    return bool(await execute(url, _NULLABLE, {"column": column}) == "YES")


async def _seed_journal_only_task(url: str) -> int:
    journal_id = await execute(url, _INSERT_JOURNAL, {"owner": USER_ID})
    task_id: int = await execute(
        url, _INSERT_JOURNAL_ONLY_TASK, {"owner": USER_ID, "journal_id": journal_id}
    )
    return task_id


@pytest.mark.integration
@pytest.mark.slow
class TestTaskListColumnsMigration:
    """0146 puts tasks on lists without weakening journal-only tasks."""

    async def test_upgrade_adds_the_columns_and_downgrade_removes_them(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        # 1. At 0145 there are no list columns and both anchors are mandatory.
        run_alembic(url, "upgrade", "0145")
        assert not _NEW_COLUMNS & await _columns(url, _TABLE)
        for anchor in _ANCHORS:
            assert not await _is_nullable(url, anchor)
        task_id = await _seed_journal_only_task(url)

        # 2. Upgrade adds the columns and index and relaxes both anchors.
        run_alembic(url, "upgrade", "0146")
        assert _NEW_COLUMNS <= await _columns(url, _TABLE)
        assert await index_exists(url, _INDEX)
        for anchor in _ANCHORS:
            assert await _is_nullable(url, anchor)

        # 3. The pre-existing journal-only task is unflagged and on no list.
        survivor = await execute(
            url,
            """
            SELECT ROW(task_list_id, position, due_date, flagged, icon)::text
            FROM tasks WHERE id = :id
            """,
            {"id": task_id},
        )
        assert survivor == "(,,,f,)"

        # 4. Downgrade removes them and makes both anchors mandatory again.
        run_alembic(url, "downgrade", "0145")
        assert not _NEW_COLUMNS & await _columns(url, _TABLE)
        assert not await index_exists(url, _INDEX)
        for anchor in _ANCHORS:
            assert not await _is_nullable(url, anchor)

        # 5. Re-applying the upgrade works (re-runnable).
        run_alembic(url, "upgrade", "0146")
        assert _NEW_COLUMNS <= await _columns(url, _TABLE)

    async def test_downgrade_is_refused_while_a_task_is_on_a_list(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0146")
        list_id = await execute(url, _INSERT_LIST, {"owner": USER_ID})
        task_id = await execute(
            url,
            """
            INSERT INTO tasks (user_id, text, task_list_id, position)
            VALUES (:owner, 'Pack the tent', :list_id, 0)
            RETURNING id
            """,
            {"owner": USER_ID, "list_id": list_id},
        )

        with pytest.raises(RuntimeError, match="cannot be downgraded"):
            run_alembic(url, "downgrade", "0145")

        # Nothing was discarded: the list task is still there, still listed.
        assert (
            await execute(
                url, "SELECT task_list_id FROM tasks WHERE id = :id", {"id": task_id}
            )
            == list_id
        )

    async def test_downgrade_is_refused_while_a_journal_only_task_is_flagged(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """A flag fits on a journal-only task but not in the 0145 schema."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0146")
        task_id = await _seed_journal_only_task(url)
        await execute(
            url, "UPDATE tasks SET flagged = true WHERE id = :id", {"id": task_id}
        )

        with pytest.raises(RuntimeError, match="cannot be downgraded"):
            run_alembic(url, "downgrade", "0145")

        assert (
            await execute(
                url, "SELECT flagged FROM tasks WHERE id = :id", {"id": task_id}
            )
            is True
        )

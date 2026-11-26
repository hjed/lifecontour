"""Migration round-trip test for 0149 (a list's associated journal).

- upgrade ``0148 -> 0149`` adds ``task_lists.associated_journal_id``, its
  foreign key to ``journals`` with ``ON DELETE RESTRICT`` and its partial index;
- downgrade ``0149 -> 0148`` removes all of it;
- re-running the upgrade after the downgrade works (re-runnable);
- the downgrade **refuses** while any list is associated, rather than silently
  discarding the association.

Constraint behaviour is covered against the session database in
``test_task_list_association_constraints.py``. Runs against an isolated
throwaway database so the shared session DB is untouched.
"""

import pytest
from sqlalchemy.engine import URL

from tests.integration.migration_helpers import RunAlembic, execute, index_exists
from tests.integration.migration_helpers import columns as _columns
from tests.integration.tasks.task_seeding import USER_ID

_TABLE = "task_lists"
_COLUMN = "associated_journal_id"
_INDEX = "ix_task_lists_associated_journal_id"
_FK = "fk_task_lists_associated_journal_id"

_INSERT_JOURNAL = """
    INSERT INTO journals (title, content, user_id,
        event_date_range_start, event_date_range_end)
    VALUES ('Trip', '', :owner, '2026-12-01', '2026-12-01')
    RETURNING id
"""
_INSERT_ASSOCIATED_LIST = """
    INSERT INTO task_lists (user_id, name, position, associated_journal_id)
    VALUES (:owner, 'Packing', 0, :journal_id)
    RETURNING id
"""
# The index definition, so the test pins that it skips unassociated lists.
_INDEX_DEFINITION = "SELECT indexdef FROM pg_indexes WHERE indexname = :name"
# The delete rule as PostgreSQL reports it, so the test pins the action itself
# rather than trusting the migration's source.
_DELETE_RULE = """
    SELECT delete_rule FROM information_schema.referential_constraints
    WHERE constraint_name = :name
"""


@pytest.mark.integration
@pytest.mark.slow
class TestTaskListAssociationMigration:
    """0149 lets a list name one journal."""

    async def test_upgrade_adds_the_column_and_downgrade_removes_it(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        # 1. At 0148 there is no association.
        run_alembic(url, "upgrade", "0148")
        assert _COLUMN not in await _columns(url, _TABLE)

        # 2. Upgrade adds the column, its RESTRICT foreign key and its partial
        #    index.
        run_alembic(url, "upgrade", "0149")
        assert _COLUMN in await _columns(url, _TABLE)
        assert await index_exists(url, _INDEX)
        definition = await execute(url, _INDEX_DEFINITION, {"name": _INDEX})
        assert definition.endswith(f"WHERE ({_COLUMN} IS NOT NULL)")
        assert await execute(url, _DELETE_RULE, {"name": _FK}) == "RESTRICT"

        # 3. Downgrade removes all three.
        run_alembic(url, "downgrade", "0148")
        assert _COLUMN not in await _columns(url, _TABLE)
        assert not await index_exists(url, _INDEX)
        assert await execute(url, _DELETE_RULE, {"name": _FK}) is None

        # 4. Re-applying the upgrade works (re-runnable).
        run_alembic(url, "upgrade", "0149")
        assert _COLUMN in await _columns(url, _TABLE)
        assert await index_exists(url, _INDEX)

    async def test_downgrade_is_refused_while_a_list_is_associated(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0149")
        journal_id = await execute(url, _INSERT_JOURNAL, {"owner": USER_ID})
        list_id = await execute(
            url, _INSERT_ASSOCIATED_LIST, {"owner": USER_ID, "journal_id": journal_id}
        )

        with pytest.raises(RuntimeError, match="cannot be downgraded"):
            run_alembic(url, "downgrade", "0148")

        # Nothing was discarded: the list still names its journal.
        assert (
            await execute(
                url,
                "SELECT associated_journal_id FROM task_lists WHERE id = :id",
                {"id": list_id},
            )
            == journal_id
        )

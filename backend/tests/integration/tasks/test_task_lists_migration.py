"""Migration round-trip test for 0145 (create the task_lists table).

- upgrade ``0144 -> 0145`` creates ``task_lists`` with the expected columns and
  its ``(user_id, position)`` index;
- downgrade ``0145 -> 0144`` drops them;
- re-running the upgrade after the downgrade recreates them (re-runnable).

Constraint behaviour is covered against the session database in
``test_task_list_table_constraints.py``. Runs against an isolated throwaway
database so the shared session DB is untouched.
"""

import pytest
from sqlalchemy.engine import URL

from tests.integration.migration_helpers import RunAlembic, index_exists
from tests.integration.migration_helpers import columns as _columns
from tests.integration.migration_helpers import table_exists as _table_exists

_TABLE = "task_lists"
_INDEX = "ix_task_lists_user_id_position"
_EXPECTED_COLUMNS = {
    "id",
    "user_id",
    "name",
    "icon",
    "position",
    "archived_at",
    "created_at",
    "updated_at",
}


@pytest.mark.integration
@pytest.mark.slow
class TestTaskListsMigration:
    """0145 creates the task_lists table."""

    async def test_upgrade_creates_the_table_and_downgrade_drops_it(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        # 1. At 0144 the table does not exist.
        run_alembic(url, "upgrade", "0144")
        assert not await _table_exists(url, _TABLE)

        # 2. Upgrade creates it with exactly the expected shape and its index.
        run_alembic(url, "upgrade", "0145")
        assert await _columns(url, _TABLE) == _EXPECTED_COLUMNS
        assert await index_exists(url, _INDEX)

        # 3. Downgrade drops both (reversible).
        run_alembic(url, "downgrade", "0144")
        assert not await _table_exists(url, _TABLE)
        assert not await index_exists(url, _INDEX)

        # 4. Re-applying the upgrade recreates them (re-runnable).
        run_alembic(url, "upgrade", "0145")
        assert await _table_exists(url, _TABLE)
        assert await index_exists(url, _INDEX)

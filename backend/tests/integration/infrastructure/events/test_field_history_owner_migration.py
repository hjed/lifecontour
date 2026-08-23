"""Migration round-trip test for 0107 (the field_history ownership column).

Verifies the additive migration that lets a **hard-deleted** task's history stay
both readable and owner-scoped:

- upgrade ``0106 -> 0107`` adds ``field_history.user_id`` and
  ``idx_field_history_entity``;
- **an existing row survives the upgrade**, carrying NULL — the property that
  distinguishes this migration from one that would fail on every deployed
  database and pass on an empty one;
- downgrade ``0107 -> 0106`` drops both;
- re-running the upgrade after the downgrade re-adds them (re-runnable).

Runs against an isolated throwaway database so the shared session DB is
untouched, following ``test_tasks_migration.py``.
"""

from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import columns as _columns
from tests.integration.migration_helpers import index_exists as _index_exists

_TABLE = "field_history"
_COLUMN = "user_id"
_INDEX = "idx_field_history_entity"


async def _seed_history_row(engine_url: str) -> None:
    """A pre-existing history row, as every deployed database has thousands of.

    The upgrade has to cope with a **populated** table. A ``NOT NULL`` column
    with no default would be rejected here and accepted by an empty-database
    test, which is the whole reason this row is seeded before the upgrade rather
    than after it.
    """
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO field_history
                        (entity_type, entity_id, field_name, old_value,
                         new_value, changed_by, source, event_id)
                    VALUES ('journal', 1, 'title', 'Old', 'New', 'ui', 'ui',
                            'evt-migration')
                    """
                )
            )
    finally:
        await engine.dispose()


async def _stored_owner(engine_url: str) -> str | None:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text(
                        "SELECT user_id FROM field_history "
                        "WHERE event_id = 'evt-migration'"
                    )
                )
            ).scalar()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestFieldHistoryOwnerMigration:
    """0107 adds the ownership column and the entity index."""

    async def test_upgrade_adds_them_and_downgrade_drops_them(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        # 1. At 0106 the table exists without either.
        run_alembic(url, "upgrade", "0106")
        assert _COLUMN not in await _columns(url, _TABLE)
        assert not await _index_exists(url, _INDEX)

        # 2. Upgrade adds both.
        run_alembic(url, "upgrade", "0107")
        assert _COLUMN in await _columns(url, _TABLE)
        assert await _index_exists(url, _INDEX)

        # 3. Downgrade removes both (reversible in schema).
        run_alembic(url, "downgrade", "0106")
        assert _COLUMN not in await _columns(url, _TABLE)
        assert not await _index_exists(url, _INDEX)

        # 4. Re-applying the upgrade re-adds them (re-runnable).
        run_alembic(url, "upgrade", "0107")
        assert _COLUMN in await _columns(url, _TABLE)
        assert await _index_exists(url, _INDEX)

    async def test_an_existing_row_survives_the_upgrade_unowned(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """The deployed case: a populated table, and a column that may be NULL.

        The row is a **journal** one, which is also the narrowing stated: nothing
        in the migration fills it in, and nothing ever will — journal history
        authorises by loading the journal. Only task rows get an owner, from the
        projection and from ``TaskHistoryBackfill``.
        """
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0106")
        await _seed_history_row(url)

        run_alembic(url, "upgrade", "0107")

        assert await _stored_owner(url) is None

"""Migration round-trip test for 0098 (create outdoor_activity_dismissals).

Verifies the additive data-layer migration for the journal-scoped dismissal store:

- upgrade ``0097 -> 0098`` creates ``outdoor_activity_dismissals`` with the
  expected columns and the ``(user_id, journal_id)`` unique constraint;
- downgrade ``0098 -> 0097`` drops the table;
- re-running the upgrade after the downgrade recreates it (re-runnable).

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

_TABLE = "outdoor_activity_dismissals"
_EXPECTED_COLUMNS = {
    "id",
    "journal_id",
    "user_id",
    "provenance",
    "created_at",
    "updated_at",
}


async def _table_exists(engine_url: str, table: str) -> bool:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            found = (
                await conn.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = :table
                        """
                    ),
                    {"table": table},
                )
            ).scalar()
            return found is not None
    finally:
        await engine.dispose()


async def _columns(engine_url: str, table: str) -> set[str]:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = :table
                        """
                    ),
                    {"table": table},
                )
            ).fetchall()
            return {str(row.column_name) for row in rows}
    finally:
        await engine.dispose()


async def _has_unique_on_user_journal(engine_url: str, table: str) -> bool:
    """True when a unique constraint spans exactly (user_id, journal_id)."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT kcu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON tc.constraint_name = kcu.constraint_name
                         AND tc.table_name = kcu.table_name
                        WHERE tc.table_name = :table
                          AND tc.constraint_type = 'UNIQUE'
                        ORDER BY tc.constraint_name, kcu.ordinal_position
                        """
                    ),
                    {"table": table},
                )
            ).fetchall()
            return {str(row.column_name) for row in rows} == {"user_id", "journal_id"}
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestOutdoorActivityDismissalsMigration:
    """0098 creates the outdoor_activity_dismissals store."""

    async def test_upgrade_creates_table_and_downgrade_drops_it(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        # 1. At 0097 the table does not yet exist.
        run_alembic(url, "upgrade", "0097")
        assert not await _table_exists(url, _TABLE)

        # 2. Upgrade creates the table with the expected shape.
        run_alembic(url, "upgrade", "0098")
        assert await _table_exists(url, _TABLE)
        assert _EXPECTED_COLUMNS <= await _columns(url, _TABLE)
        assert await _has_unique_on_user_journal(url, _TABLE)

        # 3. Downgrade drops the table (reversible).
        run_alembic(url, "downgrade", "0097")
        assert not await _table_exists(url, _TABLE)

        # 4. Re-applying the upgrade recreates it (re-runnable).
        run_alembic(url, "upgrade", "0098")
        assert await _table_exists(url, _TABLE)

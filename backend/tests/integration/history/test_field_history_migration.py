"""Migration round-trip test for 0087 (contact_field_history -> field_history).

Verifies that the rename migration preserves existing rows, leaves them with a
NULL event_id, drops the old table name, and creates the event_id column plus the
idempotency unique index. Runs against an isolated throwaway database so the shared
session database is untouched.
"""

import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

THROWAWAY_DB_NAME = "pms_field_history_migration_test"
BACKEND_DIR = Path(__file__).resolve().parents[3]


def _run_alembic(database_url: str, target: str) -> None:
    """Run ``alembic upgrade <target>`` against the given database."""
    env = {
        **os.environ,
        "ENVIRONMENT": "test",
        "DATABASE_URL": database_url,
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade {target} failed:\n{result.stdout}\n{result.stderr}"
        )


@pytest_asyncio.fixture
async def throwaway_database(async_engine: AsyncEngine) -> AsyncGenerator[URL]:
    """Create and drop an isolated database derived from the test engine URL."""
    base_url: URL = async_engine.url
    admin_url = base_url.set(database="postgres")
    target_url = base_url.set(database=THROWAWAY_DB_NAME)

    admin_engine = create_async_engine(
        admin_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(f"DROP DATABASE IF EXISTS {THROWAWAY_DB_NAME} WITH (FORCE)")
            )
            await conn.execute(text(f"CREATE DATABASE {THROWAWAY_DB_NAME}"))
        yield target_url
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(f"DROP DATABASE IF EXISTS {THROWAWAY_DB_NAME} WITH (FORCE)")
            )
        await admin_engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestFieldHistoryMigration:
    """0087 rename migration round-trip."""

    async def test_rename_preserves_rows_and_adds_idempotency_schema(
        self, throwaway_database: URL
    ) -> None:
        url_str = throwaway_database.render_as_string(hide_password=False)

        # 1. Migrate to the revision just before the rename.
        _run_alembic(url_str, "0086")

        # 2. Insert a legacy row into the pre-rename table.
        engine = create_async_engine(url_str)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO contact_field_history "
                        "(entity_type, entity_id, field_name, old_value, new_value, "
                        "changed_by, source) "
                        "VALUES ('contact', 1, 'first_name', 'John', 'Jane', 'ui', 'ui')"
                    )
                )
        finally:
            await engine.dispose()

        # 3. Apply the rename migration.
        _run_alembic(url_str, "head")

        # 4. Assert the row survived under the new table name with NULL event_id,
        #    the old table name is gone, and the idempotency schema exists.
        engine = create_async_engine(url_str)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT entity_type, entity_id, field_name, old_value, "
                            "new_value, source, event_id FROM field_history"
                        )
                    )
                ).fetchall()
                assert len(rows) == 1
                row = rows[0]
                assert row.entity_type == "contact"
                assert row.entity_id == 1
                assert row.field_name == "first_name"
                assert row.old_value == "John"
                assert row.new_value == "Jane"
                assert row.source == "ui"
                assert row.event_id is None

                # Old table name no longer resolves.
                old_table = (
                    await conn.execute(
                        text("SELECT to_regclass('public.contact_field_history')")
                    )
                ).scalar()
                assert old_table is None

                # event_id column exists and is nullable.
                nullable = (
                    await conn.execute(
                        text(
                            "SELECT is_nullable FROM information_schema.columns "
                            "WHERE table_name = 'field_history' "
                            "AND column_name = 'event_id'"
                        )
                    )
                ).scalar()
                assert nullable == "YES"

                # A unique index covers (event_id, entity_type, entity_id, field_name).
                index_defs = (
                    (
                        await conn.execute(
                            text(
                                "SELECT indexdef FROM pg_indexes "
                                "WHERE tablename = 'field_history'"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert any(
                    "UNIQUE" in d
                    and "event_id" in d
                    and "entity_type" in d
                    and "entity_id" in d
                    and "field_name" in d
                    for d in index_defs
                ), index_defs
        finally:
            await engine.dispose()

"""Migration round-trip test for 0087 (contact_field_history -> field_history).

Verifies that the rename migration preserves existing rows, leaves them with a
NULL event_id, drops the old table name, and creates the event_id column plus the
idempotency unique index. Runs against an isolated throwaway database so the shared
session database is untouched.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import RunAlembic


@pytest.mark.integration
@pytest.mark.slow
class TestFieldHistoryMigration:
    """0087 rename migration round-trip."""

    async def test_rename_preserves_rows_and_adds_idempotency_schema(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url_str = throwaway_database.render_as_string(hide_password=False)

        # 1. Migrate to the revision just before the rename.
        run_alembic(url_str, "upgrade", "0086")

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
        run_alembic(url_str, "upgrade", "head")

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

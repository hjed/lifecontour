"""Migration round-trip test for 0088 (sync_jobs fan-out hierarchy).

Verifies that the migration adds ``parent_job_id`` and the child-counter columns,
extends ``ck_sync_jobs_status`` to allow ``in_progress``, and that ``downgrade``
cleanly reverses all of it. Runs against an isolated throwaway database so the
shared session database is untouched.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.integration.migration_helpers import RunAlembic

_NEW_COLUMNS = (
    "parent_job_id",
    "expected_children",
    "completed_children",
    "failed_children",
)


async def _existing_columns(engine: AsyncEngine) -> set[str]:
    """Return the set of sync_jobs column names present in the schema."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'sync_jobs'"
                )
            )
        ).fetchall()
    return {row.column_name for row in rows}


@pytest.mark.integration
@pytest.mark.slow
class TestSyncJobFanoutMigration:
    """0088 fan-out hierarchy migration round-trip."""

    async def test_upgrade_then_downgrade_round_trip(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url_str = throwaway_database.render_as_string(hide_password=False)

        # 1. Migrate the empty database up to the revision just before the
        #    fan-out hierarchy.
        run_alembic(url_str, "upgrade", "0087")
        engine = create_async_engine(url_str)
        try:
            before = await _existing_columns(engine)
            assert not (set(_NEW_COLUMNS) & before), before

            # A pre-existing row that must survive the additive upgrade.
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO sync_jobs "
                        "(job_id, user_id, integration_source, sync_type, status) "
                        "VALUES ('legacy-job', 'user-1', 'immich', 'full', 'running')"
                    )
                )
        finally:
            await engine.dispose()

        # 2. Apply the fan-out hierarchy migration. Target 0088 explicitly (not
        #    "head") so the round-trip stays scoped to this migration and cannot
        #    be perturbed by unrelated future migrations.
        run_alembic(url_str, "upgrade", "0088")

        engine = create_async_engine(url_str)
        try:
            after = await _existing_columns(engine)
            assert set(_NEW_COLUMNS) <= after, after

            async with engine.connect() as conn:
                # Existing row preserved with backfilled counter defaults.
                row = (
                    await conn.execute(
                        text(
                            "SELECT parent_job_id, expected_children, "
                            "completed_children, failed_children "
                            "FROM sync_jobs WHERE job_id = 'legacy-job'"
                        )
                    )
                ).fetchone()
                assert row is not None
                assert row.parent_job_id is None
                assert row.expected_children == 0
                assert row.completed_children == 0
                assert row.failed_children == 0

            # The extended check constraint accepts 'in_progress'.
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO sync_jobs "
                        "(job_id, user_id, integration_source, sync_type, status) "
                        "VALUES ('parent-job', 'user-1', 'immich', 'full', "
                        "'in_progress')"
                    )
                )

            # An invalid status is still rejected.
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO sync_jobs "
                            "(job_id, user_id, integration_source, sync_type, "
                            "status) VALUES ('bad-job', 'user-1', 'immich', 'full', "
                            "'bogus')"
                        )
                    )
        finally:
            await engine.dispose()

        # 3. Downgrade and assert the columns are gone and in_progress rejected.
        run_alembic(url_str, "downgrade", "0087")

        engine = create_async_engine(url_str)
        try:
            reverted = await _existing_columns(engine)
            assert not (set(_NEW_COLUMNS) & reverted), reverted

            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO sync_jobs "
                            "(job_id, user_id, integration_source, sync_type, "
                            "status) VALUES ('after-downgrade', 'user-1', 'immich', "
                            "'full', 'in_progress')"
                        )
                    )
        finally:
            await engine.dispose()

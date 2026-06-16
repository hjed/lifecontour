"""Migration round-trip test for 0088 (sync_jobs fan-out hierarchy).

Verifies that the migration adds ``parent_job_id`` and the child-counter columns,
extends ``ck_sync_jobs_status`` to allow ``in_progress``, and that ``downgrade``
cleanly reverses all of it. Runs against an isolated throwaway database so the
shared session database is untouched.
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Process-unique so parallel test workers (e.g. pytest-xdist) sharing the same
# Postgres instance each create/drop their own throwaway database.
THROWAWAY_DB_NAME = f"pms_sync_job_fanout_migration_test_{os.getpid()}"
BACKEND_DIR = Path(__file__).resolve().parents[3]

_NEW_COLUMNS = (
    "parent_job_id",
    "expected_children",
    "completed_children",
    "failed_children",
)


def _run_alembic(database_url: str, command: str, target: str) -> None:
    """Run ``alembic <command> <target>`` against the given database."""
    env = {
        **os.environ,
        "ENVIRONMENT": "test",
        "DATABASE_URL": database_url,
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, target],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {command} {target} failed:\n{result.stdout}\n{result.stderr}"
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
class TestSyncJobFanoutMigration:
    """0088 fan-out hierarchy migration round-trip."""

    async def test_upgrade_then_downgrade_round_trip(
        self, throwaway_database: URL
    ) -> None:
        url_str = throwaway_database.render_as_string(hide_password=False)

        # 1. Migrate the empty database up to the revision just before the
        #    fan-out hierarchy.
        _run_alembic(url_str, "upgrade", "0087")
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
        _run_alembic(url_str, "upgrade", "0088")

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
        _run_alembic(url_str, "downgrade", "0087")

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

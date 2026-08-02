"""Migration round-trip test for 0105 (create the task tables).

Verifies the additive data-layer migration that introduces tasks:

- upgrade ``0104 -> 0105`` creates ``tasks``, ``task_intermediate_journals`` and
  ``task_contacts`` with the expected columns;
- ``tasks.status`` accepts exactly the three ``TaskStatus`` values and rejects
  anything else, so the CHECK constraint and the domain enum cannot drift apart;
- downgrade ``0105 -> 0104`` drops all three tables;
- re-running the upgrade after the downgrade recreates them (re-runnable).

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

from collections.abc import Callable

import pytest
from core_shared.models.tasks import TaskStatus
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import columns as _columns
from tests.integration.migration_helpers import table_exists as _table_exists

_TASKS_TABLE = "tasks"
_INTERMEDIATE_TABLE = "task_intermediate_journals"
_CONTACTS_TABLE = "task_contacts"

_EXPECTED_TASK_COLUMNS = {
    "id",
    "user_id",
    "text",
    "status",
    "creating_journal_id",
    "due_journal_id",
    "created_at",
    "updated_at",
}
_EXPECTED_INTERMEDIATE_COLUMNS = {"task_id", "journal_id", "created_at"}
_EXPECTED_CONTACT_COLUMNS = {"task_id", "contact_id", "created_at"}


async def _seed_journal(engine_url: str) -> int:
    """Insert a minimal journal to anchor tasks against, returning its id."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            journal_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO journals (
                            user_id, title, content,
                            event_date_range_start, event_date_range_end
                        )
                        VALUES ('migration-user', 'Anchor', '', now(), now())
                        RETURNING id
                        """
                    )
                )
            ).scalar_one()
            return int(journal_id)
    finally:
        await engine.dispose()


async def _insert_task_with_status(
    engine_url: str, journal_id: int, status: str
) -> None:
    """Insert a task with the given raw status value."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO tasks (
                        user_id, text, status,
                        creating_journal_id, due_journal_id
                    )
                    VALUES (
                        'migration-user', 'Return the book', :status,
                        :journal_id, :journal_id
                    )
                    """
                ),
                {"status": status, "journal_id": journal_id},
            )
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestTasksMigration:
    """0105 creates the task tables."""

    async def test_upgrade_creates_tables_and_downgrade_drops_them(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        # 1. At 0104 none of the task tables exist.
        run_alembic(url, "upgrade", "0104")
        assert not await _table_exists(url, _TASKS_TABLE)
        assert not await _table_exists(url, _INTERMEDIATE_TABLE)
        assert not await _table_exists(url, _CONTACTS_TABLE)

        # 2. Upgrade creates all three with the expected shape.
        run_alembic(url, "upgrade", "0105")
        assert _EXPECTED_TASK_COLUMNS <= await _columns(url, _TASKS_TABLE)
        assert _EXPECTED_INTERMEDIATE_COLUMNS <= await _columns(
            url, _INTERMEDIATE_TABLE
        )
        assert _EXPECTED_CONTACT_COLUMNS <= await _columns(url, _CONTACTS_TABLE)

        # 3. Downgrade drops all three (reversible).
        run_alembic(url, "downgrade", "0104")
        assert not await _table_exists(url, _TASKS_TABLE)
        assert not await _table_exists(url, _INTERMEDIATE_TABLE)
        assert not await _table_exists(url, _CONTACTS_TABLE)

        # 4. Re-applying the upgrade recreates them (re-runnable).
        run_alembic(url, "upgrade", "0105")
        assert await _table_exists(url, _TASKS_TABLE)
        assert await _table_exists(url, _INTERMEDIATE_TABLE)
        assert await _table_exists(url, _CONTACTS_TABLE)

    async def test_status_check_matches_the_domain_enum(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """Every TaskStatus is accepted and nothing else is."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0105")
        journal_id = await _seed_journal(url)

        for status in TaskStatus:
            await _insert_task_with_status(url, journal_id, status.value)

        with pytest.raises(IntegrityError):
            await _insert_task_with_status(url, journal_id, "in_progress")

    async def test_status_defaults_to_not_done(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """A task inserted without a status is not done."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0105")
        journal_id = await _seed_journal(url)

        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                status = (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO tasks (
                                user_id, text, creating_journal_id, due_journal_id
                            )
                            VALUES ('migration-user', 'Pack the ropes', :jid, :jid)
                            RETURNING status
                            """
                        ),
                        {"jid": journal_id},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()

        assert status == TaskStatus.NOT_DONE.value

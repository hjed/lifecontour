"""Migration round-trip test for 0106 (reassign synthetic-owner rows).

Two hard-coded identities have owned real rows over this project's life:
``'debug-client'`` (the FastMCP ``DebugTokenVerifier`` default, every MCP write
since 2026-03-20) and ``'dev-user'`` (the ``DISABLE_AUTH`` REST user). Neither is
a person, so rows they own are unreachable from the signed-in user's
owner-scoped reads. 0106 hands them to the site's real owner.

A site supports exactly one user, so the migration derives that owner from the
data — the single distinct ``user_id`` that is not one of the constants — and
this test covers each branch of that decision:

- one real owner alongside both constants -> every table reassigned;
- only ``dev-user`` rows (the local dev / CI / e2e shape) -> untouched;
- two real owners -> raises, naming the owners rather than guessing;
- no synthetic rows -> clean no-op.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine


def _load_migration() -> ModuleType:
    """Load 0106 by path — revision files are not importable by module name.

    Reading ``REPAIRED_TABLES`` from the migration itself keeps this test and the
    repair single-sourced: a table added there is covered here automatically.
    """
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "migrations"
        / "versions"
        / "0106_reassign_synthetic_owner_rows.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0106", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_REAL_OWNER = "11111111-2222-4333-8444-555555555555"
DEBUG_CLIENT = "debug-client"
DEV_USER = "dev-user"

_PREVIOUS_REVISION = "0105"
_REVISION = "0106"


async def _execute(url: str, statements: list[tuple[str, dict[str, object]]]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for statement, params in statements:
                await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _owners(url: str, table: str) -> dict[str, int]:
    """Return ``{user_id: row_count}`` for a table."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(f"SELECT user_id, count(*) AS n FROM {table} GROUP BY user_id")  # noqa: S608 - table name is from our own constant list
                )
            ).fetchall()
            return {str(row.user_id): int(row.n) for row in rows}
    finally:
        await engine.dispose()


def _seed_for(owner: str, seq: int) -> list[tuple[str, dict[str, object]]]:
    """One row in every repaired table, all owned by ``owner``.

    ``seq`` keeps ids and unique keys distinct between owners so seeding two
    owners cannot trip a unique constraint before the migration even runs.
    """
    journal_id = 1000 + seq
    candidate_id = 2000 + seq
    contact_id = 3000 + seq
    return [
        (
            """
            INSERT INTO contacts (id, first_name, last_name)
            VALUES (:contact_id, 'Seed', :owner)
            """,
            {"contact_id": contact_id, "owner": owner},
        ),
        (
            """
            INSERT INTO journals (id, user_id, title, content,
                                  event_date_range_start, event_date_range_end)
            VALUES (:id, :owner, 'Seeded journal', '',
                    now(), now()),
                   (:candidate_id, :owner, 'Seeded candidate', '',
                    now(), now())
            """,
            {"id": journal_id, "candidate_id": candidate_id, "owner": owner},
        ),
        (
            """
            INSERT INTO calendars (user_id, name, color)
            VALUES (:owner, 'Seeded calendar', '#ffffff')
            """,
            {"owner": owner},
        ),
        (
            "INSERT INTO gear_items (user_id, name) VALUES (:owner, 'Seeded gear')",
            {"owner": owner},
        ),
        (
            "INSERT INTO journal_series (user_id, name) VALUES (:owner, :name)",
            {"owner": owner, "name": f"Seeded series {seq}"},
        ),
        (
            """
            INSERT INTO activity_templates (user_id, name, template_type)
            VALUES (:owner, :name, 'canyoning')
            """,
            {"owner": owner, "name": f"Seeded template {seq}"},
        ),
        (
            """
            INSERT INTO tasks (user_id, text, creating_journal_id, due_journal_id)
            VALUES (:owner, 'Seeded task', :id, :id)
            """,
            {"owner": owner, "id": journal_id},
        ),
        (
            """
            INSERT INTO outdoor_activity_dismissals (journal_id, user_id, provenance)
            VALUES (:id, :owner, 'ui')
            """,
            {"id": journal_id, "owner": owner},
        ),
        (
            """
            INSERT INTO journal_review_items (user_id, source_journal_id,
                                              candidate_journal_id, reason,
                                              confidence_score)
            VALUES (:owner, :id, :candidate_id, 'duplicate_journal', 0.5)
            """,
            {"owner": owner, "id": journal_id, "candidate_id": candidate_id},
        ),
        (
            """
            INSERT INTO strava_athlete_mappings (user_id, strava_athlete_id,
                                                 strava_athlete_name, contact_id)
            VALUES (:owner, :athlete_id, 'Seeded athlete', :contact_id)
            """,
            {
                "owner": owner,
                "athlete_id": f"athlete-{seq}",
                "contact_id": contact_id,
            },
        ),
    ]


@pytest.mark.integration
@pytest.mark.slow
class TestReassignSyntheticOwnerRows:
    """0106 hands rows owned by a hard-coded identity to the site's real user."""

    async def test_every_repaired_table_declares_a_user_id_column(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """A renamed or user_id-less table would be silently skipped otherwise."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            """
                            SELECT table_name FROM information_schema.columns
                            WHERE table_schema = 'public' AND column_name = 'user_id'
                            """
                        )
                    )
                ).fetchall()
        finally:
            await engine.dispose()

        owned = {str(row.table_name) for row in rows}
        assert set(migration.REPAIRED_TABLES) <= owned

    async def test_reassigns_both_constants_to_the_single_real_owner(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(url, _seed_for(REAL_OWNER, 1))
        await _execute(url, _seed_for(DEBUG_CLIENT, 2))
        await _execute(url, _seed_for(DEV_USER, 3))

        run_alembic(url, "upgrade", _REVISION)

        for table in migration.REPAIRED_TABLES:
            owners = await _owners(url, table)
            assert DEBUG_CLIENT not in owners, (
                f"{table} still owned by the MCP constant"
            )
            assert DEV_USER not in owners, f"{table} still owned by the dev constant"
            assert set(owners) == {REAL_OWNER}

    async def test_journal_rows_survive_the_reassignment(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """Rows move owner; none are dropped."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(url, _seed_for(REAL_OWNER, 1))
        await _execute(url, _seed_for(DEBUG_CLIENT, 2))

        run_alembic(url, "upgrade", _REVISION)

        assert (await _owners(url, "journals")) == {REAL_OWNER: 4}

    async def test_a_dev_only_database_is_left_alone(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """Local dev, CI and e2e own everything as ``dev-user`` legitimately.

        With no real owner to move rows to, the migration must not invent one.
        """
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(url, _seed_for(DEV_USER, 1))

        run_alembic(url, "upgrade", _REVISION)

        for table in migration.REPAIRED_TABLES:
            assert set(await _owners(url, table)) == {DEV_USER}

    async def test_ambiguous_ownership_fails_the_migration(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """Two real owners cannot happen on a one-user site — refuse to guess."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(url, _seed_for(REAL_OWNER, 1))
        await _execute(url, _seed_for(OTHER_REAL_OWNER, 2))
        await _execute(url, _seed_for(DEBUG_CLIENT, 3))

        with pytest.raises(RuntimeError) as excinfo:
            run_alembic(url, "upgrade", _REVISION)

        message = str(excinfo.value)
        assert REAL_OWNER in message
        assert OTHER_REAL_OWNER in message
        # The synthetic rows are left untouched by the failed migration.
        assert DEBUG_CLIENT in await _owners(url, "journals")

    async def test_no_synthetic_rows_is_a_clean_no_op(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(url, _seed_for(REAL_OWNER, 1))

        run_alembic(url, "upgrade", _REVISION)

        assert (await _owners(url, "journals")) == {REAL_OWNER: 2}

    async def test_empty_database_upgrades_and_downgrades(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """A fresh install has nothing to repair, and the revision reverses."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        run_alembic(url, "downgrade", _PREVIOUS_REVISION)
        run_alembic(url, "upgrade", _REVISION)

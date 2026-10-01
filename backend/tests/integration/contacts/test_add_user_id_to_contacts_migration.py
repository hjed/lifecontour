"""Migration round-trip test for 0122 (contacts gain an owner).

``contacts`` had no ``user_id``. 0122 adds the column and hands every existing
contact to the site's one user, derived from the data rather than configured:
the single distinct non-synthetic ``user_id`` across the owner-bearing tables,
credential and settings tables included (they cover an installation that has
only ever synced contacts). Each branch of that decision is covered here:

- one real owner -> every contact assigned to it;
- the owner known only from a settings table -> still assigned;
- only synthetic owners (dev, CI, e2e) -> ``dev-user``;
- no evidence, or two real owners -> refuses, unless ``-x contacts_owner`` names one;
- no contacts -> nothing to assign; the revision upgrades and downgrades.

Runs against an isolated throwaway database so the shared session DB is untouched.
Rows are inserted raw because the schema is pinned at 0121, where the seeding
helper's ``user_id`` column does not exist yet.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import RunAlembic, columns, index_exists


def _load_migration() -> ModuleType:
    """Load 0122 by path — revision files are not importable by module name."""
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "migrations"
        / "versions"
        / "0122_add_user_id_to_contacts.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0122", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_REAL_OWNER = "11111111-2222-4333-8444-555555555555"
DEV_USER = "dev-user"
DEBUG_CLIENT = "debug-client"

_PREVIOUS_REVISION = "0121"
_REVISION = "0122"


async def _execute(url: str, statement: str, params: dict[str, object]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _seed_contacts(url: str, *names: str) -> None:
    for name in names:
        await _execute(
            url, "INSERT INTO contacts (first_name) VALUES (:name)", {"name": name}
        )


async def _seed_journal(url: str, owner: str) -> None:
    await _execute(
        url,
        """
        INSERT INTO journals (user_id, title, content,
                              event_date_range_start, event_date_range_end)
        VALUES (:owner, 'Seeded journal', '', now(), now())
        """,
        {"owner": owner},
    )


async def _seed_settings(url: str, owner: str) -> None:
    await _execute(
        url, "INSERT INTO user_settings (user_id) VALUES (:owner)", {"owner": owner}
    )


async def _contact_owners(url: str) -> dict[str, str | None]:
    """Return ``{first_name: user_id}`` for every contact."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT first_name, user_id FROM contacts"))
            ).fetchall()
            return {str(row.first_name): row.user_id for row in rows}
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestAddUserIdToContacts:
    """0122 gives every contact the site's one owner, or refuses to guess."""

    async def test_every_evidence_table_declares_a_user_id_column(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """A renamed or user_id-less table would break the derivation query."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        for table in migration.EVIDENCE_TABLES:
            assert "user_id" in await columns(url, table), table

    async def test_contacts_go_to_the_single_real_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contacts(url, "Ada", "Grace")
        await _seed_journal(url, REAL_OWNER)
        await _seed_settings(url, DEV_USER)

        run_alembic(url, "upgrade", _REVISION)

        assert await _contact_owners(url) == {"Ada": REAL_OWNER, "Grace": REAL_OWNER}
        assert await index_exists(url, "idx_contacts_user_id")

    async def test_a_settings_row_alone_identifies_the_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """A contacts-only installation holds no journal, task or calendar."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contacts(url, "Ada")
        await _seed_settings(url, REAL_OWNER)

        run_alembic(url, "upgrade", _REVISION)

        assert await _contact_owners(url) == {"Ada": REAL_OWNER}

    async def test_a_dev_only_database_assigns_dev_user(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contacts(url, "Ada")
        await _seed_journal(url, DEV_USER)

        run_alembic(url, "upgrade", _REVISION)

        assert await _contact_owners(url) == {"Ada": DEV_USER}

    async def test_both_synthetic_owners_prefer_dev_user(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """``debug-client`` can no longer be produced; a database holding both
        is a legacy local one whose developer is the ``DISABLE_AUTH`` user."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contacts(url, "Ada")
        await _seed_journal(url, DEBUG_CLIENT)
        await _seed_journal(url, DEV_USER)

        run_alembic(url, "upgrade", _REVISION)

        assert await _contact_owners(url) == {"Ada": DEV_USER}

    async def test_contacts_without_owner_evidence_refuse(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contacts(url, "Ada")

        with pytest.raises(RuntimeError, match="contacts_owner"):
            run_alembic(url, "upgrade", _REVISION)

        # The whole revision rolled back: no half-added column.
        assert "user_id" not in await columns(url, "contacts")

    async def test_two_real_owners_refuse_and_name_both(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contacts(url, "Ada")
        await _seed_journal(url, REAL_OWNER)
        await _seed_settings(url, OTHER_REAL_OWNER)

        with pytest.raises(RuntimeError) as excinfo:
            run_alembic(url, "upgrade", _REVISION)

        assert REAL_OWNER in str(excinfo.value)
        assert OTHER_REAL_OWNER in str(excinfo.value)

    @pytest.mark.parametrize("evidence", [(), (REAL_OWNER, OTHER_REAL_OWNER)])
    async def test_the_operator_override_resolves_a_refusal(
        self,
        throwaway_database: URL,
        run_alembic: RunAlembic,
        evidence: tuple[str, ...],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contacts(url, "Ada")
        for owner in evidence:
            await _seed_journal(url, owner)

        run_alembic(
            url, "upgrade", _REVISION, x_args={"contacts_owner": OTHER_REAL_OWNER}
        )

        assert await _contact_owners(url) == {"Ada": OTHER_REAL_OWNER}

    async def test_an_empty_database_upgrades_and_downgrades(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """No contacts means nothing to assign — even with no owner evidence."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        assert "user_id" in await columns(url, "contacts")

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)
        assert "user_id" not in await columns(url, "contacts")
        assert not await index_exists(url, "idx_contacts_user_id")

        run_alembic(url, "upgrade", _REVISION)

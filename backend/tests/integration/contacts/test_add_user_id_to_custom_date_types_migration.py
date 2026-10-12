"""Migration round-trip test for 0133 (custom date types gain an owner).

``custom_date_types`` had no ``user_id``. 0133 adds the column and gives each
type the owner of the contacts whose important dates use it; a type no date
uses goes to the site's one user, derived from the data exactly as 0127 does
for journal tags. Each branch:

- a type used by one owner's contacts -> that owner, whatever the site owner;
- an unused type -> the site's one real owner (a settings row alone suffices);
- an unused type on a dev-only database -> ``dev-user``;
- a type used by two owners' contacts -> refuses, naming the type;
- unused types and no owner evidence -> refuses unless
  ``-x custom_date_types_owner``;
- no types -> nothing to assign; the revision upgrades and downgrades.

Runs against an isolated throwaway database so the shared session DB is untouched.
Rows are inserted raw because the schema is pinned at 0132.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import (
    RunAlembic,
    columns,
    index_exists,
    tables_with_column,
)


def _load_migration() -> ModuleType:
    """Load 0133 by path — revision files are not importable by module name."""
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "migrations"
        / "versions"
        / "0133_add_user_id_to_custom_date_types.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0133", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_REAL_OWNER = "11111111-2222-4333-8444-555555555555"
DEV_USER = "dev-user"

_PREVIOUS_REVISION = "0132"
_REVISION = "0133"
_INDEX = "idx_custom_date_types_user_id"


async def _execute(url: str, statement: str, params: dict[str, object]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _seed_types(url: str, *names: str) -> None:
    for name in names:
        await _execute(
            url, "INSERT INTO custom_date_types (name) VALUES (:name)", {"name": name}
        )


async def _seed_contact(url: str, owner: str, *type_names: str) -> None:
    """Seed a contact owned by ``owner`` with one dated row per named type."""
    await _execute(
        url,
        """
        WITH contact AS (
            INSERT INTO contacts (first_name, user_id)
            VALUES ('Seeded', :owner)
            RETURNING id
        )
        INSERT INTO contact_important_dates
            (contact_id, date_type, precision, month, day, custom_date_type_id)
        SELECT contact.id, 'custom', 'day_month', 3, 9, t.id
        FROM contact CROSS JOIN custom_date_types t
        WHERE t.name = ANY(:type_names)
        """,
        {"owner": owner, "type_names": list(type_names)},
    )


async def _seed_settings(url: str, owner: str) -> None:
    await _execute(
        url, "INSERT INTO user_settings (user_id) VALUES (:owner)", {"owner": owner}
    )


async def _type_owners(url: str) -> dict[str, str | None]:
    """Return ``{name: user_id}`` for every custom date type."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT name, user_id FROM custom_date_types"))
            ).fetchall()
            return {str(row.name): row.user_id for row in rows}
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestAddUserIdToCustomDateTypes:
    """0133 gives each custom date type its users' owner, or the site's one user."""

    async def test_every_table_recording_a_user_is_evidence(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The evidence is exactly the tables that hold a ``user_id`` at 0132."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        assert await tables_with_column(url, "user_id") == set(
            migration.EVIDENCE_TABLES
        )

    async def test_a_used_type_goes_to_its_contacts_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The contacts decide, even against a different site-wide owner."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_types(url, "Sobriety", "Graduation")
        await _seed_contact(url, REAL_OWNER, "Sobriety")
        await _seed_contact(url, OTHER_REAL_OWNER, "Graduation")
        await _seed_contact(url, OTHER_REAL_OWNER, "Graduation")

        run_alembic(url, "upgrade", _REVISION)

        assert await _type_owners(url) == {
            "Sobriety": REAL_OWNER,
            "Graduation": OTHER_REAL_OWNER,
        }
        assert await index_exists(url, _INDEX)

    async def test_an_unused_type_goes_to_the_site_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_types(url, "Sobriety", "Unused")
        await _seed_contact(url, REAL_OWNER, "Sobriety")

        run_alembic(url, "upgrade", _REVISION)

        assert await _type_owners(url) == {
            "Sobriety": REAL_OWNER,
            "Unused": REAL_OWNER,
        }

    async def test_a_settings_row_alone_identifies_the_site_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_types(url, "Unused")
        await _seed_settings(url, REAL_OWNER)

        run_alembic(url, "upgrade", _REVISION)

        assert await _type_owners(url) == {"Unused": REAL_OWNER}

    async def test_a_dev_only_database_assigns_dev_user(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_types(url, "Unused")
        await _seed_settings(url, DEV_USER)

        run_alembic(url, "upgrade", _REVISION)

        assert await _type_owners(url) == {"Unused": DEV_USER}

    async def test_a_type_used_by_two_owners_refuses_and_names_it(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Either owner would leave the other's contact dated by a foreign type."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_types(url, "Shared", "Sobriety")
        await _seed_contact(url, REAL_OWNER, "Shared", "Sobriety")
        await _seed_contact(url, OTHER_REAL_OWNER, "Shared")

        with pytest.raises(RuntimeError, match="Shared") as excinfo:
            run_alembic(
                url,
                "upgrade",
                _REVISION,
                x_args={"custom_date_types_owner": REAL_OWNER},
            )

        assert "Sobriety" not in str(excinfo.value)
        assert "user_id" not in await columns(url, "custom_date_types")

    async def test_unused_types_without_owner_evidence_refuse(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_types(url, "Unused")

        with pytest.raises(RuntimeError, match="custom_date_types_owner"):
            run_alembic(url, "upgrade", _REVISION)

        assert "user_id" not in await columns(url, "custom_date_types")

    async def test_the_operator_override_resolves_an_ambiguous_site_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The override names the owner of unused types; used types keep theirs."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_types(url, "Sobriety", "Unused")
        await _seed_contact(url, REAL_OWNER, "Sobriety")
        await _seed_settings(url, OTHER_REAL_OWNER)

        with pytest.raises(RuntimeError, match="custom_date_types_owner"):
            run_alembic(url, "upgrade", _REVISION)

        run_alembic(
            url,
            "upgrade",
            _REVISION,
            x_args={"custom_date_types_owner": OTHER_REAL_OWNER},
        )

        assert await _type_owners(url) == {
            "Sobriety": REAL_OWNER,
            "Unused": OTHER_REAL_OWNER,
        }

    async def test_an_empty_database_upgrades_and_downgrades(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """No types means nothing to assign — even with no owner evidence."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        assert "user_id" in await columns(url, "custom_date_types")

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)
        assert "user_id" not in await columns(url, "custom_date_types")
        assert not await index_exists(url, _INDEX)

        run_alembic(url, "upgrade", _REVISION)

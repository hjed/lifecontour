"""Migration round-trip test for 0134 (custom date types require an owner).

0133 gave every type an owner but left the column nullable and names unique
across all users. 0134 owns whatever was inserted without an owner since (a used
type takes its contacts' owner, an unused one the site's one user), refuses if a
contact's date uses another owner's type, makes the column ``NOT NULL``, and
moves name uniqueness from ``UNIQUE(name)`` to ``(user_id, name)``. The
downgrade restores the global key, so it refuses while two owners share a name.

Runs against an isolated throwaway database; rows are inserted raw because the
schema is pinned at 0133.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import RunAlembic, tables_with_column


def _load_migration() -> ModuleType:
    """Load 0134 by path — revision files are not importable by module name."""
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "migrations"
        / "versions"
        / "0134_require_custom_date_types_user_id.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0134", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_REAL_OWNER = "11111111-2222-4333-8444-555555555555"

_PREVIOUS_REVISION = "0133"
_REVISION = "0134"
_GLOBAL_KEY = "custom_date_types_name_key"
_PER_USER_KEY = "uq_custom_date_types_user_id_name"


async def _execute(url: str, statement: str, params: dict[str, object]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _seed_type(url: str, name: str, owner: str | None) -> None:
    await _execute(
        url,
        "INSERT INTO custom_date_types (name, user_id) VALUES (:name, :owner)",
        {"name": name, "owner": owner},
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
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT name, user_id FROM custom_date_types"))
            ).fetchall()
            return {str(row.name): row.user_id for row in rows}
    finally:
        await engine.dispose()


async def _constraint_exists(url: str, name: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            found = (
                await conn.execute(
                    text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
                    {"name": name},
                )
            ).scalar()
            return found is not None
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestRequireCustomDateTypesUserId:
    """0134 owns stragglers, requires the owner, and scopes names to it."""

    async def test_every_table_recording_a_user_is_evidence(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The evidence is exactly the tables that hold a ``user_id`` at 0133."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        assert await tables_with_column(url, "user_id") == set(
            migration.EVIDENCE_TABLES
        )

    async def test_stragglers_are_owned_by_their_contacts_or_the_site_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Types a pre-0133 writer inserted during the rollout get an owner."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_type(url, "Owned", REAL_OWNER)
        await _seed_type(url, "Used", None)
        await _seed_type(url, "Unused", None)
        await _seed_contact(url, OTHER_REAL_OWNER, "Used")
        await _seed_settings(url, OTHER_REAL_OWNER)

        run_alembic(
            url, "upgrade", _REVISION, x_args={"custom_date_types_owner": REAL_OWNER}
        )

        assert await _type_owners(url) == {
            "Owned": REAL_OWNER,
            "Used": OTHER_REAL_OWNER,
            "Unused": REAL_OWNER,
        }

    async def test_a_date_using_another_owners_type_refuses(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """A contact dated by a foreign type must be untangled by hand first."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_type(url, "Theirs", REAL_OWNER)
        await _seed_type(url, "Mine", OTHER_REAL_OWNER)
        await _seed_contact(url, OTHER_REAL_OWNER, "Theirs", "Mine")

        with pytest.raises(RuntimeError, match="Theirs") as excinfo:
            run_alembic(url, "upgrade", _REVISION)

        assert "Mine" not in str(excinfo.value)
        assert await _constraint_exists(url, _GLOBAL_KEY)

    async def test_the_owner_is_required_afterwards(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)

        with pytest.raises(IntegrityError):
            await _seed_type(url, "Ownerless", None)

    async def test_names_are_unique_per_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Two owners may share a name; one owner may not hold it twice."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        await _seed_type(url, "Sobriety", REAL_OWNER)
        await _seed_type(url, "Sobriety", OTHER_REAL_OWNER)

        with pytest.raises(IntegrityError, match=_PER_USER_KEY):
            await _seed_type(url, "Sobriety", REAL_OWNER)

        assert not await _constraint_exists(url, _GLOBAL_KEY)

    async def test_downgrade_refuses_while_two_owners_share_a_name(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        await _seed_type(url, "Sobriety", REAL_OWNER)
        await _seed_type(url, "Sobriety", OTHER_REAL_OWNER)

        with pytest.raises(RuntimeError, match="Sobriety"):
            run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await _constraint_exists(url, _PER_USER_KEY)

    async def test_an_unshared_database_downgrades_and_upgrades(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The downgrade restores the global key and lets owners go missing again."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        await _seed_type(url, "Sobriety", REAL_OWNER)

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await _constraint_exists(url, _GLOBAL_KEY)
        assert not await _constraint_exists(url, _PER_USER_KEY)
        await _seed_type(url, "Ownerless", None)
        with pytest.raises(IntegrityError, match=_GLOBAL_KEY):
            await _seed_type(url, "Sobriety", OTHER_REAL_OWNER)

        run_alembic(url, "upgrade", _REVISION)
        assert await _type_owners(url) == {
            "Sobriety": REAL_OWNER,
            "Ownerless": REAL_OWNER,
        }

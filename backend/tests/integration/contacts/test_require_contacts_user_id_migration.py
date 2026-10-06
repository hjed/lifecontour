"""Migration round-trip test for 0123 (``contacts.user_id`` becomes NOT NULL).

Between 0122 and the release that made every writer stamp an owner, a contact
created through REST or MCP still inserted ``user_id = NULL``. 0123 assigns
those rows by the same derivation as 0122 — with owned contacts now counting as
evidence — and only then constrains the column:

- NULL rows beside owned contacts -> given that owner, column NOT NULL;
- NULL rows with no owner evidence -> refuses, unless ``-x contacts_owner``;
- no NULL rows -> the constraint alone;
- downgrade -> nullable again.

Rows are inserted raw: the seeding helper cannot write a NULL owner.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import RunAlembic, tables_with_column


def _load_migration() -> ModuleType:
    """Load 0123 by path — revision files are not importable by module name."""
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "migrations"
        / "versions"
        / "0123_require_contacts_user_id.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0123", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"

_PREVIOUS_REVISION = "0122"
_REVISION = "0123"


async def _seed_contact(url: str, name: str, owner: str | None) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO contacts (first_name, user_id) VALUES (:n, :o)"),
                {"n": name, "o": owner},
            )
    finally:
        await engine.dispose()


async def _contact_owners(url: str) -> dict[str, str | None]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT first_name, user_id FROM contacts"))
            ).fetchall()
            return {str(row.first_name): row.user_id for row in rows}
    finally:
        await engine.dispose()


async def _owner_is_nullable(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            nullable = (
                await conn.execute(
                    text(
                        """
                        SELECT is_nullable FROM information_schema.columns
                        WHERE table_name = 'contacts' AND column_name = 'user_id'
                        """
                    )
                )
            ).scalar_one()
            return str(nullable) == "YES"
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestRequireContactsUserId:
    """0123 owns the stragglers, then makes an unowned contact impossible."""

    async def test_every_table_recording_a_user_is_evidence(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The evidence is exactly the tables holding a ``user_id`` at 0122,
        owned contacts included."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        assert await tables_with_column(url, "user_id") == set(
            migration.EVIDENCE_TABLES
        )

    async def test_unowned_contacts_join_the_existing_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contact(url, "Synced", REAL_OWNER)
        await _seed_contact(url, "Created via REST", None)

        run_alembic(url, "upgrade", _REVISION)

        assert await _contact_owners(url) == {
            "Synced": REAL_OWNER,
            "Created via REST": REAL_OWNER,
        }
        assert not await _owner_is_nullable(url)

    async def test_unowned_contacts_without_evidence_refuse(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contact(url, "Orphan", None)

        with pytest.raises(RuntimeError, match="contacts_owner"):
            run_alembic(url, "upgrade", _REVISION)

        assert await _owner_is_nullable(url)

    async def test_the_operator_override_resolves_the_refusal(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contact(url, "Orphan", None)

        run_alembic(url, "upgrade", _REVISION, x_args={"contacts_owner": REAL_OWNER})

        assert await _contact_owners(url) == {"Orphan": REAL_OWNER}

    async def test_owned_contacts_are_left_alone_and_the_revision_reverses(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_contact(url, "Synced", REAL_OWNER)

        run_alembic(url, "upgrade", _REVISION)
        assert await _contact_owners(url) == {"Synced": REAL_OWNER}
        assert not await _owner_is_nullable(url)

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)
        assert await _owner_is_nullable(url)

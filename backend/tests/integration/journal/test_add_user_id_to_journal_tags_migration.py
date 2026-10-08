"""Migration round-trip test for 0127 (journal tags gain an owner).

``journal_tags`` had no ``user_id``. 0127 adds the column and gives each tag the
owner of the journals that carry it; a tag no journal carries goes to the site's
one user, derived from the data exactly as 0123 does for contacts. Each branch:

- a tag carried by one owner's journals -> that owner, whatever the site owner;
- an uncarried tag -> the site's one real owner (a settings row alone suffices);
- an uncarried tag on a dev-only database -> ``dev-user``;
- a tag carried by two owners' journals -> refuses, naming the tag;
- uncarried tags and no owner evidence -> refuses unless ``-x journal_tags_owner``;
- no tags -> nothing to assign; the revision upgrades and downgrades.

Runs against an isolated throwaway database so the shared session DB is untouched.
Rows are inserted raw because the schema is pinned at 0126.
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
    """Load 0127 by path — revision files are not importable by module name."""
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "migrations"
        / "versions"
        / "0127_add_user_id_to_journal_tags.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0127", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_REAL_OWNER = "11111111-2222-4333-8444-555555555555"
DEV_USER = "dev-user"

_PREVIOUS_REVISION = "0126"
_REVISION = "0127"


async def _execute(url: str, statement: str, params: dict[str, object]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _seed_tags(url: str, *names: str) -> None:
    for name in names:
        await _execute(
            url, "INSERT INTO journal_tags (name) VALUES (:name)", {"name": name}
        )


async def _seed_journal(url: str, owner: str, *tag_names: str) -> None:
    """Seed a journal owned by ``owner`` carrying the named (existing) tags."""
    await _execute(
        url,
        """
        WITH journal AS (
            INSERT INTO journals (user_id, title, content,
                                  event_date_range_start, event_date_range_end)
            VALUES (:owner, 'Seeded journal', '', now(), now())
            RETURNING id
        )
        INSERT INTO journal_tag_assignments (journal_id, tag_id)
        SELECT journal.id, t.id
        FROM journal CROSS JOIN journal_tags t
        WHERE t.name = ANY(:tag_names)
        """,
        {"owner": owner, "tag_names": list(tag_names)},
    )


async def _seed_settings(url: str, owner: str) -> None:
    await _execute(
        url, "INSERT INTO user_settings (user_id) VALUES (:owner)", {"owner": owner}
    )


async def _tag_owners(url: str) -> dict[str, str | None]:
    """Return ``{name: user_id}`` for every journal tag."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT name, user_id FROM journal_tags"))
            ).fetchall()
            return {str(row.name): row.user_id for row in rows}
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestAddUserIdToJournalTags:
    """0127 gives each journal tag its carriers' owner, or the site's one user."""

    async def test_every_table_recording_a_user_is_evidence(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The evidence is exactly the tables that hold a ``user_id`` at 0126."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        assert await tables_with_column(url, "user_id") == set(
            migration.EVIDENCE_TABLES
        )

    async def test_a_carried_tag_goes_to_its_journals_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The carriers decide, even against a different site-wide owner."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "family", "work")
        await _seed_journal(url, REAL_OWNER, "family")
        await _seed_journal(url, OTHER_REAL_OWNER, "work")
        await _seed_journal(url, OTHER_REAL_OWNER, "work")

        run_alembic(url, "upgrade", _REVISION)

        assert await _tag_owners(url) == {
            "family": REAL_OWNER,
            "work": OTHER_REAL_OWNER,
        }
        assert await index_exists(url, "idx_journal_tags_user_id")

    async def test_an_uncarried_tag_goes_to_the_site_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "family", "unused")
        await _seed_journal(url, REAL_OWNER, "family")

        run_alembic(url, "upgrade", _REVISION)

        assert await _tag_owners(url) == {"family": REAL_OWNER, "unused": REAL_OWNER}

    async def test_a_settings_row_alone_identifies_the_site_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "unused")
        await _seed_settings(url, REAL_OWNER)

        run_alembic(url, "upgrade", _REVISION)

        assert await _tag_owners(url) == {"unused": REAL_OWNER}

    async def test_a_dev_only_database_assigns_dev_user(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "unused")
        await _seed_settings(url, DEV_USER)

        run_alembic(url, "upgrade", _REVISION)

        assert await _tag_owners(url) == {"unused": DEV_USER}

    async def test_a_tag_carried_by_two_owners_refuses_and_names_it(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Either owner would leave the other's journal holding a foreign tag."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "shared", "family")
        await _seed_journal(url, REAL_OWNER, "shared", "family")
        await _seed_journal(url, OTHER_REAL_OWNER, "shared")

        with pytest.raises(RuntimeError, match="shared") as excinfo:
            run_alembic(
                url,
                "upgrade",
                _REVISION,
                x_args={"journal_tags_owner": REAL_OWNER},
            )

        assert "family" not in str(excinfo.value)
        assert "user_id" not in await columns(url, "journal_tags")

    async def test_uncarried_tags_without_owner_evidence_refuse(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "unused")

        with pytest.raises(RuntimeError, match="journal_tags_owner"):
            run_alembic(url, "upgrade", _REVISION)

        assert "user_id" not in await columns(url, "journal_tags")

    async def test_the_operator_override_resolves_an_ambiguous_site_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The override names the owner of uncarried tags; carried tags keep theirs."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tags(url, "family", "unused")
        await _seed_journal(url, REAL_OWNER, "family")
        await _seed_settings(url, OTHER_REAL_OWNER)

        with pytest.raises(RuntimeError, match="journal_tags_owner"):
            run_alembic(url, "upgrade", _REVISION)

        run_alembic(
            url, "upgrade", _REVISION, x_args={"journal_tags_owner": OTHER_REAL_OWNER}
        )

        assert await _tag_owners(url) == {
            "family": REAL_OWNER,
            "unused": OTHER_REAL_OWNER,
        }

    async def test_an_empty_database_upgrades_and_downgrades(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """No tags means nothing to assign — even with no owner evidence."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        assert "user_id" in await columns(url, "journal_tags")

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)
        assert "user_id" not in await columns(url, "journal_tags")
        assert not await index_exists(url, "idx_journal_tags_user_id")

        run_alembic(url, "upgrade", _REVISION)

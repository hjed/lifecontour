"""Migration round-trip test for 0128 (journal tags require an owner).

0127 gave every tag an owner but left the column nullable and tag names unique
across all users. 0128 owns whatever was inserted without an owner since (a
carried tag takes its journals' owner, an uncarried one the site's one user),
refuses if any journal carries another owner's tag, makes the column ``NOT
NULL``. Name uniqueness stays global until 0129.

Runs against an isolated throwaway database; rows are inserted raw because the
schema is pinned at 0127.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import (
    RunAlembic,
    tables_with_column,
)


def _load_migration() -> ModuleType:
    """Load 0128 by path — revision files are not importable by module name."""
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "migrations"
        / "versions"
        / "0128_require_journal_tags_user_id.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0128", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_REAL_OWNER = "11111111-2222-4333-8444-555555555555"

_PREVIOUS_REVISION = "0127"
_REVISION = "0128"
_GLOBAL_INDEX = "uq_journal_tags_name_lower"


async def _execute(url: str, statement: str, params: dict[str, object]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _seed_tag(url: str, name: str, owner: str | None) -> None:
    await _execute(
        url,
        "INSERT INTO journal_tags (name, user_id) VALUES (:name, :owner)",
        {"name": name, "owner": owner},
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


async def _tag_owners(url: str) -> dict[str, str | None]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT name, user_id FROM journal_tags"))
            ).fetchall()
            return {str(row.name): row.user_id for row in rows}
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
                        WHERE table_name = 'journal_tags' AND column_name = 'user_id'
                        """
                    )
                )
            ).scalar_one()
            return str(nullable) == "YES"
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestRequireJournalTagsUserId:
    """0128 owns the stragglers, then makes tag names unique per owner."""

    async def test_every_table_recording_a_user_is_evidence(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        assert await tables_with_column(url, "user_id") == set(
            migration.EVIDENCE_TABLES
        )

    async def test_stragglers_are_owned_and_the_column_is_required(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tag(url, "owned", REAL_OWNER)
        await _seed_tag(url, "carried", None)
        await _seed_tag(url, "uncarried", None)
        await _seed_journal(url, OTHER_REAL_OWNER, "carried")

        # Two real owners in the data, so the uncarried tag needs the override;
        # the carried one follows its journal whatever the override says.
        run_alembic(
            url, "upgrade", _REVISION, x_args={"journal_tags_owner": REAL_OWNER}
        )

        assert await _tag_owners(url) == {
            "owned": REAL_OWNER,
            "carried": OTHER_REAL_OWNER,
            "uncarried": REAL_OWNER,
        }
        assert not await _owner_is_nullable(url)

    async def test_an_uncarried_straggler_without_evidence_refuses(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tag(url, "uncarried", None)

        with pytest.raises(RuntimeError, match="journal_tags_owner"):
            run_alembic(url, "upgrade", _REVISION)

        assert await _owner_is_nullable(url)

    async def test_a_journal_carrying_another_owners_tag_refuses(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The global name lookup before scoping could attach A's tag to B's journal."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tag(url, "family", REAL_OWNER)
        await _seed_tag(url, "chores", REAL_OWNER)
        await _seed_journal(url, REAL_OWNER, "chores")
        await _seed_journal(url, OTHER_REAL_OWNER, "family")

        with pytest.raises(RuntimeError, match="family") as excinfo:
            run_alembic(url, "upgrade", _REVISION)

        assert "chores" not in str(excinfo.value)
        assert await _owner_is_nullable(url)

    async def test_a_hierarchy_crossing_owners_refuses(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """0127 can split a parent and child between owners; the tree must not."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tag(url, "outdoors", REAL_OWNER)
        await _seed_tag(url, "sibling", REAL_OWNER)
        await _seed_tag(url, "climbing", OTHER_REAL_OWNER)
        await _seed_tag(url, "bouldering", OTHER_REAL_OWNER)
        await _execute(
            url,
            """
            UPDATE journal_tags SET parent_id = parents.id
            FROM journal_tags parents
            WHERE (journal_tags.name, parents.name)
                  IN (('climbing', 'outdoors'), ('bouldering', 'climbing'))
            """,
            {},
        )

        with pytest.raises(RuntimeError, match="'climbing'") as excinfo:
            run_alembic(url, "upgrade", _REVISION)

        assert "bouldering" not in str(excinfo.value)
        assert await _owner_is_nullable(url)

    async def test_names_stay_globally_unique_until_reads_are_scoped(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """0129 scopes the name index, together with the owner-scoped reads."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)

        await _seed_tag(url, "Family", REAL_OWNER)
        with pytest.raises(IntegrityError, match=_GLOBAL_INDEX):
            await _seed_tag(url, "family", OTHER_REAL_OWNER)

    async def test_a_clean_database_round_trips(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tag(url, "family", REAL_OWNER)

        run_alembic(url, "upgrade", _REVISION)
        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await _owner_is_nullable(url)
        assert await _tag_owners(url) == {"family": REAL_OWNER}

        run_alembic(url, "upgrade", _REVISION)

"""Migration round-trip tests for 0129 and 0136 (tag names unique per owner).

Both tag tables had a global case-insensitive name index. 0129 (journal tags)
and 0136 (contact tags) replace it with one per owner, so two users may each
hold ``family`` while one user still cannot hold ``Family`` and ``family``. Each
downgrade restores the global index and so refuses while two owners share a
name.

Runs against an isolated throwaway database.
"""

from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import RunAlembic, index_exists

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_REAL_OWNER = "11111111-2222-4333-8444-555555555555"


@dataclass(frozen=True)
class NameScope:
    table: str
    previous_revision: str
    revision: str
    global_index: str
    per_user_index: str


SCOPES = [
    NameScope(
        "journal_tags",
        "0128",
        "0129",
        "uq_journal_tags_name_lower",
        "uq_journal_tags_user_id_name_lower",
    ),
    NameScope(
        "tags", "0135", "0136", "uq_tags_name_lower", "uq_tags_user_id_name_lower"
    ),
]


async def _seed_tag(url: str, scope: NameScope, name: str, owner: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"INSERT INTO {scope.table} (name, user_id) VALUES (:name, :owner)"
                ),  # noqa: S608 - table name from SCOPES
                {"name": name, "owner": owner},
            )
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("scope", SCOPES, ids=lambda scope: scope.table)
class TestScopeTagNamesToOwner:
    """Tag names become unique per owner, case-insensitively."""

    async def test_names_are_unique_per_owner_and_case_insensitive(
        self, scope: NameScope, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", scope.revision)

        await _seed_tag(url, scope, "Family", REAL_OWNER)
        await _seed_tag(url, scope, "family", OTHER_REAL_OWNER)
        with pytest.raises(IntegrityError, match=scope.per_user_index):
            await _seed_tag(url, scope, "FAMILY", REAL_OWNER)

        assert not await index_exists(url, scope.global_index)
        assert await index_exists(url, scope.per_user_index)

    async def test_a_shared_name_refuses_the_downgrade(
        self, scope: NameScope, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", scope.revision)
        await _seed_tag(url, scope, "Family", REAL_OWNER)
        await _seed_tag(url, scope, "family", OTHER_REAL_OWNER)

        with pytest.raises(RuntimeError, match="family"):
            run_alembic(url, "downgrade", scope.previous_revision)

        assert await index_exists(url, scope.per_user_index)

    async def test_a_clean_database_round_trips(
        self, scope: NameScope, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", scope.previous_revision)
        await _seed_tag(url, scope, "family", REAL_OWNER)

        run_alembic(url, "upgrade", scope.revision)
        run_alembic(url, "downgrade", scope.previous_revision)

        assert await index_exists(url, scope.global_index)
        assert not await index_exists(url, scope.per_user_index)

        run_alembic(url, "upgrade", scope.revision)

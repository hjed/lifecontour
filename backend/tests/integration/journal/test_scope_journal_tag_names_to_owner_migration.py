"""Migration round-trip test for 0129 (journal tag names unique per owner).

0129 replaces the global case-insensitive name index with one per owner, so two
users may each hold ``family`` while one user still cannot hold ``Family`` and
``family``. Its downgrade restores the global index and so refuses while two
owners share a name.

Runs against an isolated throwaway database.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import RunAlembic, index_exists

REAL_OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_REAL_OWNER = "11111111-2222-4333-8444-555555555555"

_PREVIOUS_REVISION = "0128"
_REVISION = "0129"
_GLOBAL_INDEX = "uq_journal_tags_name_lower"
_PER_USER_INDEX = "uq_journal_tags_user_id_name_lower"


async def _seed_tag(url: str, name: str, owner: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO journal_tags (name, user_id) VALUES (:name, :owner)"),
                {"name": name, "owner": owner},
            )
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestScopeJournalTagNamesToOwner:
    """0129 makes journal tag names unique per owner, case-insensitively."""

    async def test_names_are_unique_per_owner_and_case_insensitive(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)

        await _seed_tag(url, "Family", REAL_OWNER)
        await _seed_tag(url, "family", OTHER_REAL_OWNER)
        with pytest.raises(IntegrityError, match=_PER_USER_INDEX):
            await _seed_tag(url, "FAMILY", REAL_OWNER)

        assert not await index_exists(url, _GLOBAL_INDEX)
        assert await index_exists(url, _PER_USER_INDEX)

    async def test_a_shared_name_refuses_the_downgrade(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        await _seed_tag(url, "Family", REAL_OWNER)
        await _seed_tag(url, "family", OTHER_REAL_OWNER)

        with pytest.raises(RuntimeError, match="family"):
            run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await index_exists(url, _PER_USER_INDEX)

    async def test_a_clean_database_round_trips(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_tag(url, "family", REAL_OWNER)

        run_alembic(url, "upgrade", _REVISION)
        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await index_exists(url, _GLOBAL_INDEX)
        assert not await index_exists(url, _PER_USER_INDEX)

        run_alembic(url, "upgrade", _REVISION)

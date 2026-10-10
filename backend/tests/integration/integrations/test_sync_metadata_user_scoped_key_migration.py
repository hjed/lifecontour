"""Migration round-trip test for 0128 (the per-user link key becomes the only one).

0126 gave every link an owner but left the column nullable, so a writer not yet
deployed could still insert an owner-less row. 0128:

- gives every row still unowned its entity's owner, or the site's one owner
  (logged; ``-x sync_metadata_owner`` names it when the data cannot);
- makes ``sync_metadata.user_id`` NOT NULL;
- drops the global ``(integration_source, external_id)`` index, so two users
  may each link the same external id.

Its downgrade restores both, refusing while two owners hold one external id.
"""

import pytest
from sqlalchemy.engine import URL

from tests.integration.migration_helpers import (
    RunAlembic,
    execute,
    index_exists,
    link_owners,
    load_revision,
    tables_with_column,
)

migration = load_revision("0128_sync_metadata_user_scoped_unique_key.py")

OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_OWNER = "1b2c3d4e-0000-4000-8000-fedcbafedcba"

_PREVIOUS_REVISION = "0127"
_REVISION = "0128"
_GLOBAL_INDEX = "idx_sync_metadata_integration_external"
_PER_USER_INDEX = "uq_sync_metadata_user_source_external"


async def _seed_contact(url: str, owner: str) -> int:
    contact_id: int = await execute(
        url,
        "INSERT INTO contacts (first_name, user_id) VALUES ('Ada', :o) RETURNING id",
        {"o": owner},
    )
    return contact_id


async def _seed_link(
    url: str,
    external_id: str,
    *,
    user_id: str | None = None,
    internal_id: int | None = None,
    source: str = "google",
) -> None:
    await execute(
        url,
        """
        INSERT INTO sync_metadata (
            user_id, internal_id, integration_source, external_id,
            last_synced_at, version_hash, sync_status, internal_entity_type
        ) VALUES (
            :user_id, :internal_id, :source, :external_id,
            now(), 'h', 'success', 'contact'
        )
        """,
        {
            "user_id": user_id,
            "internal_id": internal_id,
            "source": source,
            "external_id": external_id,
        },
    )


async def _owner_is_required(url: str) -> bool:
    nullable = await execute(
        url,
        """
        SELECT is_nullable FROM information_schema.columns
        WHERE table_name = 'sync_metadata' AND column_name = 'user_id'
        """,
    )
    return bool(nullable == "NO")


@pytest.mark.integration
@pytest.mark.slow
class TestSyncMetadataUserScopedKey:
    """0128 requires an owner on every link and keys links by it alone."""

    async def test_every_table_recording_a_user_is_evidence(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The orphan evidence is exactly the tables holding a ``user_id`` at 0127."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        assert await tables_with_column(url, "user_id") == set(
            migration.EVIDENCE_TABLES
        )

    async def test_unowned_links_are_assigned_then_an_owner_is_required(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """A row a pre-release writer left owner-less takes its entity's owner;
        one naming no live entity is logged and takes the site's owner."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        theirs = await _seed_contact(url, OTHER_OWNER)
        await _seed_contact(url, OWNER)
        await _seed_link(url, "people/theirs", internal_id=theirs)
        await _seed_link(url, "people/owned", user_id=OWNER)
        await _seed_link(url, "people/orphan", internal_id=999_999)

        # Two owners in the data and an orphan: whose it is cannot be derived.
        with pytest.raises(RuntimeError, match="sync_metadata_owner"):
            run_alembic(url, "upgrade", _REVISION)
        output = run_alembic(
            url, "upgrade", _REVISION, x_args={"sync_metadata_owner": OWNER}
        )

        assert await link_owners(url) == {
            "people/theirs": OTHER_OWNER,
            "people/owned": OWNER,
            "people/orphan": OWNER,
        }
        assert "people/orphan" in output
        assert await _owner_is_required(url)

    async def test_orphans_without_owner_evidence_refuse(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_link(url, "people/orphan")

        with pytest.raises(RuntimeError, match="sync_metadata_owner"):
            run_alembic(url, "upgrade", _REVISION)

        assert not await _owner_is_required(url)
        assert await index_exists(url, _GLOBAL_INDEX)

    async def test_two_owners_may_link_the_same_external_id(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)

        await _seed_link(url, "asset-7", user_id=OWNER, source="snipeit")
        await _seed_link(url, "asset-7", user_id=OTHER_OWNER, source="snipeit")

        assert not await index_exists(url, _GLOBAL_INDEX)
        assert await index_exists(url, _PER_USER_INDEX)
        count = await execute(
            url, "SELECT count(*) FROM sync_metadata WHERE external_id = 'asset-7'"
        )
        assert count == 2

    async def test_the_revision_reverses_and_reapplies(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        await _seed_link(url, "people/1", user_id=OWNER)

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert not await _owner_is_required(url)
        assert await index_exists(url, _GLOBAL_INDEX)

        run_alembic(url, "upgrade", _REVISION)
        assert await _owner_is_required(url)
        assert not await index_exists(url, _GLOBAL_INDEX)

    async def test_downgrade_refuses_while_two_owners_hold_one_external_id(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        await _seed_link(url, "asset-7", user_id=OWNER, source="snipeit")
        await _seed_link(url, "asset-7", user_id=OTHER_OWNER, source="snipeit")

        with pytest.raises(RuntimeError, match="asset-7"):
            run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await _owner_is_required(url)
        assert not await index_exists(url, _GLOBAL_INDEX)

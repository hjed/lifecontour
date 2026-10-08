"""Migration round-trip test for 0126 (``sync_metadata`` gains an owner).

0126 adds a nullable ``sync_metadata.user_id`` and gives every link the owner of
the entity it points at:

- a contact link -> the contact's owner (``internal_id``);
- a journal link -> the journal's owner, by ``internal_id`` or, for Snipe-IT,
  by the journal id stored as text in ``internal_uuid``;
- a gear link -> the gear item's owner (``internal_uuid``);
- a row with no ``internal_entity_type`` -> typed by its source (the Snipe-IT
  worker never writes one);
- a row still unowned (no pointer, or a deleted entity) -> logged, then the
  site's one owner, unless ``-x sync_metadata_owner`` names it;

then creates the per-user unique index beside the global one.

Rows are inserted raw: the revision under test predates every writer helper.
"""

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import (
    RunAlembic,
    columns,
    index_exists,
    tables_with_column,
)


def _load_migration() -> ModuleType:
    """Load 0126 by path — revision files are not importable by module name."""
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "migrations"
        / "versions"
        / "0126_add_user_id_to_sync_metadata.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0126", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_OWNER = "1b2c3d4e-0000-4000-8000-fedcbafedcba"

_PREVIOUS_REVISION = "0125"
_REVISION = "0126"
_PER_USER_INDEX = "uq_sync_metadata_user_source_external"


async def _execute(url: str, sql: str, params: dict[str, Any] | None = None) -> Any:
    """Run ``sql`` in its own transaction; return its scalar when it returns rows."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            return result.scalar() if result.returns_rows else None
    finally:
        await engine.dispose()


async def _seed_contact(url: str, owner: str) -> int:
    contact_id: int = await _execute(
        url,
        "INSERT INTO contacts (first_name, user_id) VALUES ('Ada', :o) RETURNING id",
        {"o": owner},
    )
    return contact_id


async def _seed_journal(url: str, owner: str) -> int:
    journal_id: int = await _execute(
        url,
        """
        INSERT INTO journals (user_id, title, content,
                              event_date_range_start, event_date_range_end)
        VALUES (:o, 'Seeded journal', '', now(), now())
        RETURNING id
        """,
        {"o": owner},
    )
    return journal_id


async def _seed_gear_item(url: str, owner: str) -> str:
    gear_id = str(uuid.uuid4())
    await _execute(
        url,
        "INSERT INTO gear_items (id, user_id, name) VALUES (:id, :o, 'Rope')",
        {"id": gear_id, "o": owner},
    )
    return gear_id


async def _seed_link(
    url: str,
    source: str,
    external_id: str,
    *,
    internal_id: int | None = None,
    internal_uuid: str | None = None,
    internal_entity_type: str | None = None,
) -> None:
    await _execute(
        url,
        """
        INSERT INTO sync_metadata (
            internal_id, internal_uuid, integration_source, external_id,
            last_synced_at, version_hash, sync_status, internal_entity_type
        ) VALUES (
            :internal_id, :internal_uuid, :source, :external_id,
            now(), 'h', 'success', :internal_entity_type
        )
        """,
        {
            "internal_id": internal_id,
            "internal_uuid": internal_uuid,
            "source": source,
            "external_id": external_id,
            "internal_entity_type": internal_entity_type,
        },
    )


async def _link_owners(url: str) -> dict[str, str | None]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT external_id, user_id FROM sync_metadata")
                )
            ).fetchall()
            return {str(row.external_id): row.user_id for row in rows}
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestAddUserIdToSyncMetadata:
    """0126 gives every link its entity's owner, and orphans the site's owner."""

    async def test_every_table_recording_a_user_is_evidence(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The orphan evidence is exactly the tables holding a ``user_id`` at 0125."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)

        assert await tables_with_column(url, "user_id") == set(
            migration.EVIDENCE_TABLES
        )

    async def test_each_link_takes_its_own_entitys_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Two owners' links each resolve to their entity, and with no orphan
        left the two-owner site is not refused."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        contact = await _seed_contact(url, OWNER)
        journal = await _seed_journal(url, OTHER_OWNER)
        snipeit_journal = await _seed_journal(url, OWNER)
        gear = await _seed_gear_item(url, OTHER_OWNER)
        await _seed_link(
            url,
            "google",
            "people/1",
            internal_id=contact,
            internal_entity_type="contact",
        )
        await _seed_link(
            url, "strava", "act-1", internal_id=journal, internal_entity_type="journal"
        )
        # No entity type: typed by source, as the Snipe-IT worker writes them.
        await _seed_link(url, "immich_album", "album-1", internal_id=journal)
        await _seed_link(
            url, "snipeit_checkin", "checkin-1", internal_uuid=str(snipeit_journal)
        )
        await _seed_link(
            url, "snipeit_maintenance", "maint-1", internal_uuid=str(snipeit_journal)
        )
        await _seed_link(url, "snipeit", "asset-1", internal_uuid=gear)

        run_alembic(url, "upgrade", _REVISION)

        assert await _link_owners(url) == {
            "people/1": OWNER,
            "act-1": OTHER_OWNER,
            "album-1": OTHER_OWNER,
            "checkin-1": OWNER,
            "maint-1": OWNER,
            "asset-1": OTHER_OWNER,
        }

    async def test_orphans_take_the_sites_owner_and_are_logged(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """A link naming no entity, and one naming a deleted contact, cannot be
        resolved; each is logged and given the one owner the data records."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_journal(url, OWNER)
        await _seed_link(url, "snipeit_maintenance", "maint-unlinked")
        await _seed_link(
            url,
            "google",
            "people/deleted",
            internal_id=999_999,
            internal_entity_type="contact",
        )

        output = run_alembic(url, "upgrade", _REVISION)

        assert await _link_owners(url) == {
            "maint-unlinked": OWNER,
            "people/deleted": OWNER,
        }
        assert "maint-unlinked" in output
        assert "people/deleted" in output

    async def test_orphans_without_owner_evidence_refuse(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_link(url, "snipeit_maintenance", "maint-unlinked")

        with pytest.raises(RuntimeError, match="sync_metadata_owner"):
            run_alembic(url, "upgrade", _REVISION)

        assert "user_id" not in await columns(url, "sync_metadata")

    async def test_the_operator_override_names_the_orphans_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _seed_journal(url, OTHER_OWNER)
        await _seed_link(url, "snipeit_maintenance", "maint-unlinked")

        run_alembic(url, "upgrade", _REVISION, x_args={"sync_metadata_owner": OWNER})

        assert await _link_owners(url) == {"maint-unlinked": OWNER}

    async def test_the_per_user_key_is_unique(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The per-user index exists beside the global one and rejects a second
        row for the same owner, source and external id."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)

        assert await index_exists(url, _PER_USER_INDEX)
        assert await index_exists(url, "idx_sync_metadata_integration_external")
        insert = """
            INSERT INTO sync_metadata (
                user_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status
            ) VALUES (:o, 'google', 'people/1', now(), 'h', 'success')
        """
        await _execute(url, insert, {"o": OWNER})
        with pytest.raises(IntegrityError):
            await _execute(url, insert, {"o": OWNER})

    async def test_the_revision_reverses_and_reapplies(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        contact = await _seed_contact(url, OWNER)
        await _seed_link(
            url,
            "google",
            "people/1",
            internal_id=contact,
            internal_entity_type="contact",
        )

        run_alembic(url, "upgrade", _REVISION)
        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert "user_id" not in await columns(url, "sync_metadata")
        assert not await index_exists(url, _PER_USER_INDEX)

        run_alembic(url, "upgrade", _REVISION)
        assert await _link_owners(url) == {"people/1": OWNER}

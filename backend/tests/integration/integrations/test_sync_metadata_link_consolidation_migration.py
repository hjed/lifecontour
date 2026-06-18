"""Migration round-trip test for 0089 (sync_metadata link consolidation).

Verifies that the additive migration adds ``reference_data``,
``internal_entity_type`` and ``external_entity_type`` (all nullable), backfills
the entity-type columns from ``integration_source`` for existing rows, leaves
``reference_data`` NULL, preserves pre-existing data, and that ``downgrade``
cleanly drops the three columns. Runs against an isolated throwaway database so
the shared session database is untouched.
"""

from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_NEW_COLUMNS = (
    "reference_data",
    "internal_entity_type",
    "external_entity_type",
)

# (integration_source, external_id, expected internal/external entity type).
# ``None`` entity types mean the source has no mapping and must stay NULL.
_SEED_ROWS = (
    ("google", "people/c1", "contact", "person"),
    ("immich", "person-uuid-1", "contact", "person"),
    ("immich_album", "album-uuid-1", "journal", "album"),
    ("strava", "activity-1", "journal", "activity"),
    ("snipeit", "asset-1", "gear_item", "hardware"),
    ("snipeit_maintenance", "snipeit_maint:1", "journal", "maintenance"),
    ("snipeit_checkout", "snipeit_checkout:1:2", "journal", "checkout"),
    ("firefly_iii", "txn-1", None, None),
)


async def _existing_columns(engine: AsyncEngine) -> set[str]:
    """Return the set of sync_metadata column names present in the schema."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'sync_metadata'"
                )
            )
        ).fetchall()
    return {row.column_name for row in rows}


@pytest.mark.integration
@pytest.mark.slow
class TestSyncMetadataLinkConsolidationMigration:
    """0089 additive link-consolidation migration round-trip."""

    async def test_upgrade_backfills_then_downgrade_round_trip(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url_str = throwaway_database.render_as_string(hide_password=False)

        # 1. Migrate the empty database up to the revision just before the
        #    link-consolidation schema change.
        run_alembic(url_str, "upgrade", "0088")
        engine = create_async_engine(url_str)
        try:
            before = await _existing_columns(engine)
            assert not (set(_NEW_COLUMNS) & before), before

            # Pre-existing rows that must survive the additive upgrade and get
            # their entity types backfilled from integration_source.
            async with engine.begin() as conn:
                for index, seed in enumerate(_SEED_ROWS):
                    source, external_id = seed[0], seed[1]
                    await conn.execute(
                        text(
                            "INSERT INTO sync_metadata "
                            "(internal_id, integration_source, external_id, "
                            "last_synced_at, version_hash, sync_status) "
                            "VALUES (:internal_id, :source, :external_id, "
                            "now(), :version_hash, 'success')"
                        ),
                        {
                            "internal_id": index + 1,
                            "source": source,
                            "external_id": external_id,
                            "version_hash": f"hash-{index}",
                        },
                    )
        finally:
            await engine.dispose()

        # 2. Apply the link-consolidation migration. Target 0089 explicitly (not
        #    "head") so the round-trip stays scoped to this migration and cannot
        #    be perturbed by unrelated future migrations.
        run_alembic(url_str, "upgrade", "0089")

        engine = create_async_engine(url_str)
        try:
            after = await _existing_columns(engine)
            assert set(_NEW_COLUMNS) <= after, after

            # All three new columns are nullable.
            async with engine.connect() as conn:
                nullables = (
                    await conn.execute(
                        text(
                            "SELECT column_name, is_nullable "
                            "FROM information_schema.columns "
                            "WHERE table_name = 'sync_metadata' "
                            "AND column_name = ANY(:cols)"
                        ),
                        {"cols": list(_NEW_COLUMNS)},
                    )
                ).fetchall()
            assert {row.is_nullable for row in nullables} == {"YES"}, nullables

            # Entity-type backfill is correct per source; reference_data stays
            # NULL; pre-existing columns are preserved; row count is unchanged.
            async with engine.connect() as conn:
                total = (
                    await conn.execute(text("SELECT count(*) FROM sync_metadata"))
                ).scalar()
                assert total == len(_SEED_ROWS)

                for index, seed in enumerate(_SEED_ROWS):
                    source, external_id, internal_type, external_type = seed
                    rows = (
                        await conn.execute(
                            text(
                                "SELECT version_hash, internal_entity_type, "
                                "external_entity_type, reference_data "
                                "FROM sync_metadata "
                                "WHERE integration_source = :source "
                                "AND external_id = :external_id"
                            ),
                            {"source": source, "external_id": external_id},
                        )
                    ).fetchall()
                    # Exactly one row per (source, external_id); no duplication.
                    assert len(rows) == 1, source
                    row = rows[0]
                    # Pre-existing column value preserved verbatim, not just non-null.
                    assert row.version_hash == f"hash-{index}", source
                    assert row.internal_entity_type == internal_type, source
                    assert row.external_entity_type == external_type, source
                    assert row.reference_data is None, source
        finally:
            await engine.dispose()

        # 3. Downgrade and assert the three columns are gone but rows survive.
        run_alembic(url_str, "downgrade", "0088")

        engine = create_async_engine(url_str)
        try:
            reverted = await _existing_columns(engine)
            assert not (set(_NEW_COLUMNS) & reverted), reverted

            async with engine.connect() as conn:
                total = (
                    await conn.execute(text("SELECT count(*) FROM sync_metadata"))
                ).scalar()
                assert total == len(_SEED_ROWS)
        finally:
            await engine.dispose()

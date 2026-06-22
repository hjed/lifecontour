"""Migration round-trip test for 0093 (drop external_references + quarantine).

Verifies the final contract step of the link consolidation:

- after upgrading, neither ``external_references`` nor the 0091
  ``link_backfill_quarantine`` audit table exists;
- the canonical ``sync_metadata`` link store still works (insert + read);
- downgrade recreates ``external_references`` (post-0015 schema) and the empty
  ``link_backfill_quarantine`` audit table.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine


async def _scalar(engine_url: str, sql: str, params: dict[str, Any]) -> Any:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestDropExternalReferencesMigration:
    """0093 drop of external_references and the link-backfill quarantine table."""

    async def test_drop_then_downgrade_round_trip(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        # 0091 leaves external_references + link_backfill_quarantine present.
        run_alembic(url, "upgrade", "0091")
        assert (
            await _scalar(url, "SELECT to_regclass('public.external_references')", {})
            is not None
        )
        assert (
            await _scalar(
                url, "SELECT to_regclass('public.link_backfill_quarantine')", {}
            )
            is not None
        )

        # A real contact + its canonical link must survive the drop untouched.
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        text(
                            "INSERT INTO contacts (first_name, last_name) "
                            "VALUES ('Keep', 'Me') RETURNING id"
                        )
                    )
                ).fetchone()
                assert row is not None
                contact_id = int(row.id)
                await conn.execute(
                    text("""
                        INSERT INTO sync_metadata
                            (internal_id, integration_source, external_id,
                             last_synced_at, version_hash, sync_status,
                             internal_entity_type, external_entity_type)
                        VALUES (:iid, 'google', 'people/keep', now(), 'h', 'success',
                                'contact', 'person')
                    """),
                    {"iid": contact_id},
                )
        finally:
            await engine.dispose()

        # Upgrade through 0092 (no bug pairs -> no-op) and 0093 (the drop).
        run_alembic(url, "upgrade", "0093")

        assert (
            await _scalar(url, "SELECT to_regclass('public.external_references')", {})
            is None
        )
        assert (
            await _scalar(
                url, "SELECT to_regclass('public.link_backfill_quarantine')", {}
            )
            is None
        )

        # sync_metadata is intact and still writable/readable.
        assert (
            await _scalar(
                url,
                "SELECT internal_id FROM sync_metadata WHERE external_id = 'people/keep'",
                {},
            )
            == contact_id
        )
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("""
                        INSERT INTO sync_metadata
                            (integration_source, external_id, last_synced_at,
                             version_hash, sync_status)
                        VALUES ('strava', 'act-1', now(), 'h', 'success')
                    """)
                )
        finally:
            await engine.dispose()
        assert (
            await _scalar(
                url,
                "SELECT count(*) FROM sync_metadata WHERE integration_source = 'strava'",
                {},
            )
            == 1
        )

        # Downgrade recreates the legacy table + audit table (empty).
        run_alembic(url, "downgrade", "0092")
        assert (
            await _scalar(url, "SELECT to_regclass('public.external_references')", {})
            is not None
        )
        assert await _scalar(url, "SELECT count(*) FROM external_references", {}) == 0
        assert (
            await _scalar(
                url, "SELECT to_regclass('public.link_backfill_quarantine')", {}
            )
            is not None
        )

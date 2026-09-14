"""Migration test for 0111 (invalidate Snipe-IT gear hashes for HTML decode).

Verifies that upgrading ``0110 -> 0111`` resets ``version_hash`` for the
``snipeit`` gear source only, so the next sync re-imports gear through the
decoding transformer, and that the no-op downgrade succeeds.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

_SENTINEL = "invalidated_for_html_decode"


async def _seed_sync_metadata(engine_url: str) -> None:
    """Insert one synced row per Snipe-IT source with a real-looking hash."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            for source in ("snipeit", "snipeit_maintenance", "snipeit_checkout"):
                await conn.execute(
                    text("""
                        INSERT INTO sync_metadata
                            (integration_source, external_id, last_synced_at,
                             version_hash, sync_status)
                        VALUES (:source, '42', now(), :hash, 'success')
                    """),
                    {"source": source, "hash": f"hash-{source}"},
                )
    finally:
        await engine.dispose()


async def _hashes_by_source(engine_url: str) -> dict[str, str]:
    """Return ``integration_source -> version_hash`` for the seeded rows."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT integration_source, version_hash FROM sync_metadata")
                )
            ).fetchall()
            return {str(row.integration_source): str(row.version_hash) for row in rows}
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestInvalidateSnipeItHashForHtmlDecodeMigration:
    """0111 invalidates Snipe-IT gear version hashes."""

    async def test_upgrade_invalidates_only_snipeit_gear_hashes(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        run_alembic(url, "upgrade", "0110")
        await _seed_sync_metadata(url)

        run_alembic(url, "upgrade", "0111")
        assert await _hashes_by_source(url) == {
            "snipeit": _SENTINEL,
            "snipeit_maintenance": "hash-snipeit_maintenance",
            "snipeit_checkout": "hash-snipeit_checkout",
        }

        # Downgrade cannot restore hashes; it must still succeed.
        run_alembic(url, "downgrade", "0110")
        assert (await _hashes_by_source(url))["snipeit"] == _SENTINEL

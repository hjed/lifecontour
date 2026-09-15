"""Migration test for 0111 (decode HTML-escaped Snipe-IT gear text in place).

Verifies that upgrading ``0110 -> 0111`` decodes gear text that is exactly
Snipe-IT's escaped API output, leaves everything else untouched, and keeps
``version_hash`` so no re-sync (and no dropped local edit) is triggered:

- Snipe-IT-synced gear holding escaped text is decoded;
- raw locally-edited text, text truncated mid-entity and gear with no
  Snipe-IT link are left as-is;
- the Snipe-IT ``version_hash`` is unchanged, and the no-op downgrade succeeds;
- a value edited after the migration read the row is not overwritten with the
  stale decoded value.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine


def _load_migration() -> ModuleType:
    """Load 0111 by path; revision files are not importable by module name."""
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "migrations"
        / "versions"
        / "0111_decode_html_escaped_snipeit_gear_text.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0111", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

_ESCAPED_ID = "00000000-0000-0000-0000-000000000001"
_LOCAL_EDIT_ID = "00000000-0000-0000-0000-000000000002"
_TRUNCATED_ID = "00000000-0000-0000-0000-000000000003"
_UNSYNCED_ID = "00000000-0000-0000-0000-000000000004"
_TRUNCATED_NAME = "A" * 196 + "&am"

_GEAR_ROWS: list[dict[str, Any]] = [
    {
        "id": _ESCAPED_ID,
        "name": "Petzl Am&#039;d Ball Lock",
        "model": "&lt;Rope&gt; 60m",
        "manufacturer": "Black &amp; Decker",
        "serial_number": "SN &quot;A&quot;",
    },
    {
        "id": _LOCAL_EDIT_ID,
        "name": "Rope & Harness",
        "model": "Tom's Rope",
        "manufacturer": "Petzl",
        "serial_number": None,
    },
    {
        "id": _TRUNCATED_ID,
        "name": _TRUNCATED_NAME,
        "model": None,
        "manufacturer": None,
        "serial_number": None,
    },
    {
        "id": _UNSYNCED_ID,
        "name": "Manual &amp; Gear",
        "model": None,
        "manufacturer": None,
        "serial_number": None,
    },
]


async def _seed(engine_url: str) -> None:
    """Insert gear items, linking all but the unsynced one to Snipe-IT."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            for row in _GEAR_ROWS:
                await conn.execute(
                    text("""
                        INSERT INTO gear_items
                            (id, user_id, name, model, manufacturer, serial_number)
                        VALUES
                            (:id, 'user-1', :name, :model, :manufacturer,
                             :serial_number)
                    """),
                    row,
                )
            for external_id, gear_id in enumerate(
                (_ESCAPED_ID, _LOCAL_EDIT_ID, _TRUNCATED_ID), start=1
            ):
                await conn.execute(
                    text("""
                        INSERT INTO sync_metadata
                            (internal_uuid, integration_source, external_id,
                             last_synced_at, version_hash, sync_status)
                        VALUES
                            (:gear_id, 'snipeit', :external_id, now(),
                             :hash, 'success')
                    """),
                    {
                        "gear_id": gear_id,
                        "external_id": str(external_id),
                        "hash": f"hash-{external_id}",
                    },
                )
    finally:
        await engine.dispose()


async def _gear_by_id(engine_url: str) -> dict[str, dict[str, str | None]]:
    """Return the text columns of every gear item keyed by id."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id::text AS id, name, model, manufacturer, "
                        "serial_number FROM gear_items"
                    )
                )
            ).fetchall()
            return {
                str(row.id): {
                    "name": row.name,
                    "model": row.model,
                    "manufacturer": row.manufacturer,
                    "serial_number": row.serial_number,
                }
                for row in rows
            }
    finally:
        await engine.dispose()


async def _snipeit_hashes(engine_url: str) -> set[str]:
    """Return the version hashes of the Snipe-IT gear sync rows."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT version_hash FROM sync_metadata "
                        "WHERE integration_source = 'snipeit'"
                    )
                )
            ).fetchall()
            return {str(row.version_hash) for row in rows}
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestDecodeHtmlEscapedSnipeItGearTextMigration:
    """0111 decodes Snipe-IT-escaped gear text without touching sync hashes."""

    async def test_upgrade_decodes_only_escaped_snipeit_gear_text(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        run_alembic(url, "upgrade", "0110")
        await _seed(url)

        run_alembic(url, "upgrade", "0111")
        gear = await _gear_by_id(url)

        assert gear[_ESCAPED_ID] == {
            "name": "Petzl Am'd Ball Lock",
            "model": "<Rope> 60m",
            "manufacturer": "Black & Decker",
            "serial_number": 'SN "A"',
        }
        # Raw local edits are not Snipe-IT's escaped form, so they stay raw.
        assert gear[_LOCAL_EDIT_ID]["name"] == "Rope & Harness"
        assert gear[_LOCAL_EDIT_ID]["model"] == "Tom's Rope"
        # An entity cut by truncation is left rather than half-decoded.
        assert gear[_TRUNCATED_ID]["name"] == _TRUNCATED_NAME
        # Gear with no Snipe-IT link is not Snipe-IT text.
        assert gear[_UNSYNCED_ID]["name"] == "Manual &amp; Gear"
        # Hashes are kept, so the next sync does not re-import (and overwrite).
        assert await _snipeit_hashes(url) == {"hash-1", "hash-2", "hash-3"}

        # The original escaping cannot be restored; the downgrade must still run.
        run_alembic(url, "downgrade", "0110")
        assert (await _gear_by_id(url))[_ESCAPED_ID]["name"] == "Petzl Am'd Ball Lock"

    async def test_decode_does_not_overwrite_a_concurrent_edit(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0110")
        await _seed(url)

        # The row as the migration read it, before a user edits the name.
        stale_row = {**_GEAR_ROWS[0]}
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE gear_items SET name = 'Edited & kept' WHERE id = :id"),
                    {"id": _ESCAPED_ID},
                )
            async with engine.begin() as conn:
                await conn.run_sync(
                    lambda sync_conn: migration.decode_gear_row(sync_conn, stale_row)
                )
        finally:
            await engine.dispose()

        gear = (await _gear_by_id(url))[_ESCAPED_ID]
        # The edit wins; columns nobody touched are still decoded.
        assert gear["name"] == "Edited & kept"
        assert gear["manufacturer"] == "Black & Decker"

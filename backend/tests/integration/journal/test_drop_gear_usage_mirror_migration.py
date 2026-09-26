"""Migration round-trip test for 0120 (drop the gear usage single-item columns).

- upgrade ``0119 -> 0120`` drops the entry's mirror columns and keeps the entry
  and its items;
- downgrade ``0120 -> 0119`` re-adds them, refilled from each entry's first item.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import columns as _columns

_ROPE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_HARNESS = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_MIRROR = {"gear_item_id", "checkout_date", "checkin_date"}


async def _run(engine_url: str, sql: str, params: dict[str, Any] | None = None) -> Any:
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            return result.fetchall() if result.returns_rows else None
    finally:
        await engine.dispose()


async def _seed(engine_url: str) -> int:
    """A journal whose entry lists two items, harness first, at the 0119 schema."""
    await _run(
        engine_url,
        "INSERT INTO gear_items (id, user_id, name) VALUES "
        "(:rope, 'user-1', 'Rope'), (:harness, 'user-1', 'Harness')",
        {"rope": _ROPE, "harness": _HARNESS},
    )
    rows = await _run(
        engine_url,
        """
        INSERT INTO journals (user_id, title, content,
                              event_date_range_start, event_date_range_end)
        VALUES ('user-1', 'Trip', '', now(), now())
        RETURNING id
        """,
    )
    journal_id = int(rows[0].id)
    await _run(
        engine_url,
        "INSERT INTO journal_gear_usage_data (journal_id, gear_item_id) "
        "VALUES (:id, :harness)",
        {"id": journal_id, "harness": _HARNESS},
    )
    await _run(
        engine_url,
        "INSERT INTO journal_gear_usage_items (journal_id, gear_item_id, position) "
        "VALUES (:id, :harness, 0), (:id, :rope, 1)",
        {"id": journal_id, "harness": _HARNESS, "rope": _ROPE},
    )
    return journal_id


@pytest.mark.integration
@pytest.mark.slow
class TestDropGearUsageMirrorMigration:
    async def test_the_mirror_goes_and_comes_back_from_the_first_item(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0119")
        journal_id = await _seed(url)
        # Lose the mirror, as a deleted gear item would, so the downgrade must
        # refill it rather than keep what was there.
        await _run(url, "UPDATE journal_gear_usage_data SET gear_item_id = NULL")

        run_alembic(url, "upgrade", "0120")
        assert not _MIRROR & await _columns(url, "journal_gear_usage_data")
        items = await _run(url, "SELECT count(*) AS n FROM journal_gear_usage_items")
        assert items[0].n == 2

        run_alembic(url, "downgrade", "0119")
        entries = await _run(
            url,
            "SELECT journal_id, gear_item_id::text AS gear_item_id "
            "FROM journal_gear_usage_data",
        )
        assert [(r.journal_id, r.gear_item_id) for r in entries] == [
            (journal_id, _HARNESS)
        ]

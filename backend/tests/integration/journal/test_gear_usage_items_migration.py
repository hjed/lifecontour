"""Migration round-trip test for 0119 (gear usage items).

0119 lets one GEAR_USAGE entry hold many gear items. The entry row in
``journal_gear_usage_data`` stays — it is what makes a journal a GEAR_USAGE
journal — and its items move to ``journal_gear_usage_items``:

- **every existing row becomes exactly one item**, carrying its gear item and
  both buffer dates, and the entry row itself is left as it was (its columns
  are the legacy mirror of the first item until a later migration drops them);
- the backfill writes no outbox rows, so nothing is pushed to Snipe-IT for the
  journals it moves;
- ``gear_item_id`` on the entry becomes nullable, so an entry can hold no items;
- downgrade drops the items table and refuses nothing a deployed database holds.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import table_exists as _table_exists

_ITEMS = "journal_gear_usage_items"
_GEAR_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_GEAR_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_CHECKOUT = datetime(2026, 5, 1, 22, 0, tzinfo=UTC)
_CHECKIN = datetime(2026, 5, 3, 8, 30, tzinfo=UTC)


async def _seed(engine_url: str) -> dict[str, int]:
    """Two GEAR_USAGE journals at the 0118 schema: one with dates, one without."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            for gear_id, name in ((_GEAR_A, "Rope"), (_GEAR_B, "Harness")):
                await conn.execute(
                    text(
                        "INSERT INTO gear_items (id, user_id, name) "
                        "VALUES (:id, 'user-1', :name)"
                    ),
                    {"id": gear_id, "name": name},
                )
            journal_ids: dict[str, int] = {}
            for key in ("dated", "undated"):
                row = (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO journals (
                                user_id, title, content,
                                event_date_range_start, event_date_range_end
                            )
                            VALUES ('user-1', :title, '', now(), now())
                            RETURNING id
                            """
                        ),
                        {"title": key},
                    )
                ).fetchone()
                assert row is not None
                journal_ids[key] = int(row.id)
            await conn.execute(
                text(
                    """
                    INSERT INTO journal_gear_usage_data
                        (journal_id, gear_item_id, checkout_date, checkin_date)
                    VALUES
                        (:dated, :gear_a, :checkout, :checkin),
                        (:undated, :gear_b, NULL, NULL)
                    """
                ),
                {
                    "dated": journal_ids["dated"],
                    "undated": journal_ids["undated"],
                    "gear_a": _GEAR_A,
                    "gear_b": _GEAR_B,
                    "checkout": _CHECKOUT,
                    "checkin": _CHECKIN,
                },
            )
        return journal_ids
    finally:
        await engine.dispose()


async def _fetch(engine_url: str, sql: str) -> list[Any]:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            return list((await conn.execute(text(sql))).fetchall())
    finally:
        await engine.dispose()


async def _execute(engine_url: str, sql: str, params: dict[str, Any]) -> None:
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestGearUsageItemsMigration:
    """0119 moves each gear usage row into an item under the same entry."""

    async def test_each_existing_row_becomes_one_item(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0118")
        journal_ids = await _seed(url)
        outbox_before = await _fetch(url, "SELECT count(*) AS n FROM outbox_events")

        run_alembic(url, "upgrade", "0119")

        items = await _fetch(
            url,
            f"""
            SELECT journal_id, gear_item_id::text AS gear_item_id,
                   checkout_date, checkin_date, created_at, updated_at
            FROM {_ITEMS} ORDER BY journal_id
            """,
        )
        assert [
            (r.journal_id, r.gear_item_id, r.checkout_date, r.checkin_date)
            for r in items
        ] == [
            (journal_ids["dated"], _GEAR_A, _CHECKOUT, _CHECKIN),
            (journal_ids["undated"], _GEAR_B, None, None),
        ]
        assert all(r.created_at is not None and r.updated_at is not None for r in items)

        # The entry rows — what makes each journal a GEAR_USAGE journal — stay,
        # still mirroring their (only) item.
        entries = await _fetch(
            url,
            "SELECT journal_id, gear_item_id::text AS gear_item_id "
            "FROM journal_gear_usage_data ORDER BY journal_id",
        )
        assert [(r.journal_id, r.gear_item_id) for r in entries] == [
            (journal_ids["dated"], _GEAR_A),
            (journal_ids["undated"], _GEAR_B),
        ]

        outbox_after = await _fetch(url, "SELECT count(*) AS n FROM outbox_events")
        assert outbox_after[0].n == outbox_before[0].n

    async def test_an_entry_may_hold_no_items_and_an_item_is_unique(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0118")
        journal_ids = await _seed(url)
        run_alembic(url, "upgrade", "0119")

        # The mirror of an entry with no items is NULL.
        await _execute(
            url,
            "UPDATE journal_gear_usage_data SET gear_item_id = NULL "
            "WHERE journal_id = :id",
            {"id": journal_ids["undated"]},
        )

        # The same gear item cannot be listed twice on one journal.
        with pytest.raises(Exception, match="duplicate key"):
            await _execute(
                url,
                f"INSERT INTO {_ITEMS} (journal_id, gear_item_id) VALUES (:id, :gear)",
                {"id": journal_ids["dated"], "gear": _GEAR_A},
            )

        # A second, different gear item on the same journal is fine.
        await _execute(
            url,
            f"INSERT INTO {_ITEMS} (journal_id, gear_item_id) VALUES (:id, :gear)",
            {"id": journal_ids["dated"], "gear": _GEAR_B},
        )

    async def test_items_follow_their_entry(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """A merge moves an entry by rewriting its journal_id; deleting drops items."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0118")
        journal_ids = await _seed(url)
        run_alembic(url, "upgrade", "0119")
        await _execute(
            url,
            "DELETE FROM journal_gear_usage_data WHERE journal_id = :id",
            {"id": journal_ids["undated"]},
        )

        await _execute(
            url,
            "UPDATE journal_gear_usage_data SET journal_id = :to "
            "WHERE journal_id = :from",
            {"from": journal_ids["dated"], "to": journal_ids["undated"]},
        )

        remaining = await _fetch(
            url, f"SELECT journal_id FROM {_ITEMS} ORDER BY journal_id"
        )
        assert [r.journal_id for r in remaining] == [journal_ids["undated"]]

    async def test_deleting_a_gear_item_keeps_the_entry_and_its_other_items(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0118")
        journal_ids = await _seed(url)
        run_alembic(url, "upgrade", "0119")
        await _execute(
            url,
            f"INSERT INTO {_ITEMS} (journal_id, gear_item_id, position) "
            "VALUES (:id, :gear, 1)",
            {"id": journal_ids["dated"], "gear": _GEAR_B},
        )

        await _execute(url, "DELETE FROM gear_items WHERE id = :id", {"id": _GEAR_A})

        entries = await _fetch(
            url,
            "SELECT journal_id, gear_item_id FROM journal_gear_usage_data "
            "ORDER BY journal_id",
        )
        assert [(r.journal_id, r.gear_item_id) for r in entries] == [
            (journal_ids["dated"], None),
            (journal_ids["undated"], entries[1].gear_item_id),
        ]
        items = await _fetch(
            url,
            f"SELECT journal_id, gear_item_id::text AS gear_item_id FROM {_ITEMS} "
            "ORDER BY journal_id",
        )
        assert [(r.journal_id, r.gear_item_id) for r in items] == [
            (journal_ids["dated"], _GEAR_B),
            (journal_ids["undated"], _GEAR_B),
        ]

        # Downgrading refills the emptied mirror from the remaining first item.
        run_alembic(url, "downgrade", "0118")
        entries = await _fetch(
            url,
            "SELECT journal_id, gear_item_id::text AS gear_item_id "
            "FROM journal_gear_usage_data ORDER BY journal_id",
        )
        assert [(r.journal_id, r.gear_item_id) for r in entries] == [
            (journal_ids["dated"], _GEAR_B),
            (journal_ids["undated"], _GEAR_B),
        ]

    async def test_downgrade_drops_the_items_and_upgrade_reruns(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0118")
        await _seed(url)
        run_alembic(url, "upgrade", "0119")

        run_alembic(url, "downgrade", "0118")
        assert not await _table_exists(url, _ITEMS)
        entries = await _fetch(url, "SELECT count(*) AS n FROM journal_gear_usage_data")
        assert entries[0].n == 2

        run_alembic(url, "upgrade", "0119")
        items = await _fetch(url, f"SELECT count(*) AS n FROM {_ITEMS}")
        assert items[0].n == 2

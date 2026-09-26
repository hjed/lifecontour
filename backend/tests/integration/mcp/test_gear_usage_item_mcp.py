"""MCP tools that add or remove one gear item on a journal.

``add_gear_usage_item`` adds a gear item to a journal (giving it the GEAR_USAGE
type if it has none) or updates the dates of one it already lists;
``remove_gear_usage_item`` removes one. Neither rewrites the rest of the list.
"""

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.mcp.http_helpers import call_mcp_tool
from tests.integration.tasks.task_seeding import OTHER_USER_ID, create_journal


async def _gear_item(client: Any, name: str) -> str:
    payload = await call_mcp_tool(client, "create_gear_item", {"name": name})
    assert "error" not in payload, payload
    return str(payload["id"])


async def _journal(client: Any) -> int:
    payload = await call_mcp_tool(
        client,
        "create_journal_entry",
        {
            "request": {
                "title": "Canyon trip",
                "content": "",
                "event_date_range": {"start": "2025-04-09", "end": "2025-04-10"},
                "types": ["CANYONING"],
            }
        },
    )
    assert "error" not in payload, payload
    return int(payload["id"])


def _instant(value: str | None) -> str | None:
    return datetime.fromisoformat(value).isoformat() if value else None


def _items(payload: dict[str, Any]) -> list[tuple[str, str | None, str | None]]:
    return [
        (
            item["gear_item_id"],
            _instant(item["checkout_date"]),
            _instant(item["checkin_date"]),
        )
        for item in payload["items"]
    ]


async def _gear_usage_history(connection: AsyncConnection, journal_id: int) -> int:
    result = await connection.execute(
        text(
            "SELECT count(*) FROM outbox_events "
            "WHERE event_type = 'JournalUpdated' AND aggregate_id = :id "
            "AND event_data LIKE '%gear_usage:item:%'"
        ),
        {"id": journal_id},
    )
    return int(result.scalar() or 0)


class TestGearUsageItemTools:
    @pytest.mark.asyncio
    async def test_items_are_added_updated_and_removed_one_at_a_time(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        async with authenticated_lifespan_client() as client:
            rope = await _gear_item(client, "Rope")
            harness = await _gear_item(client, "Harness")
            journal_id = await _journal(client)

            # The first item gives the journal the GEAR_USAGE type.
            added = await call_mcp_tool(
                client,
                "add_gear_usage_item",
                {"journal_id": journal_id, "gear_item_id": rope},
            )
            assert "error" not in added, added
            assert _items(added) == [(rope, None, None)]

            added = await call_mcp_tool(
                client,
                "add_gear_usage_item",
                {
                    "journal_id": journal_id,
                    "gear_item_id": harness,
                    "checkout_date": "2025-04-08T20:00:00+00:00",
                },
            )
            assert _items(added) == [
                (rope, None, None),
                (harness, "2025-04-08T20:00:00+00:00", None),
            ]

            # Adding a listed item again sets the dates sent and keeps the rest.
            updated = await call_mcp_tool(
                client,
                "add_gear_usage_item",
                {
                    "journal_id": journal_id,
                    "gear_item_id": harness,
                    "checkin_date": "2025-04-11T08:00:00+00:00",
                },
            )
            assert _items(updated) == [
                (rope, None, None),
                (
                    harness,
                    "2025-04-08T20:00:00+00:00",
                    "2025-04-11T08:00:00+00:00",
                ),
            ]

            removed = await call_mcp_tool(
                client,
                "remove_gear_usage_item",
                {"journal_id": journal_id, "gear_item_id": rope},
            )
            assert "error" not in removed, removed
            assert [item[0] for item in _items(removed)] == [harness]

            fetched = await call_mcp_tool(
                client, "get_journal", {"journal_id": journal_id}
            )
            assert "canyoning" in fetched["types"]
            assert [
                item["gear_item_id"]
                for item in fetched["type_data"]["gear_usage"]["items"]
            ] == [harness]

        # Every change reached history and the integrations as JournalUpdated.
        assert await _gear_usage_history(clean_database, journal_id) == 4

    @pytest.mark.asyncio
    async def test_removing_an_item_the_journal_does_not_list_is_refused(
        self, authenticated_lifespan_client
    ) -> None:
        async with authenticated_lifespan_client() as client:
            rope = await _gear_item(client, "Rope")
            helmet = await _gear_item(client, "Helmet")
            journal_id = await _journal(client)
            await call_mcp_tool(
                client,
                "add_gear_usage_item",
                {"journal_id": journal_id, "gear_item_id": rope},
            )

            payload = await call_mcp_tool(
                client,
                "remove_gear_usage_item",
                {"journal_id": journal_id, "gear_item_id": helmet},
            )

        assert "error" in payload
        assert "gear_item_id" in payload["message"]

    @pytest.mark.asyncio
    async def test_an_unknown_gear_item_is_refused(
        self, authenticated_lifespan_client
    ) -> None:
        async with authenticated_lifespan_client() as client:
            journal_id = await _journal(client)

            payload = await call_mcp_tool(
                client,
                "add_gear_usage_item",
                {
                    "journal_id": journal_id,
                    "gear_item_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
                },
            )

        assert "error" in payload

    @pytest.mark.asyncio
    async def test_another_users_journal_is_reported_missing(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        theirs = await create_journal(
            SqlJournalRepository(clean_database), user_id=OTHER_USER_ID
        )
        async with authenticated_lifespan_client() as client:
            rope = await _gear_item(client, "Rope")

            payload = await call_mcp_tool(
                client,
                "add_gear_usage_item",
                {"journal_id": theirs, "gear_item_id": rope},
            )

        assert "error" in payload
        assert "not found" in payload["message"].lower()

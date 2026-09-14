"""`get_journal` reports every calendar an event lives in.

The REST surface gained a `calendars` list when de-duplication made one
journal linkable to several calendars; this is the same answer asked for
the way an AI client asks for it. Without it an assistant reading a shared
event would be told it sits in one calendar, and would say so.

`calendar` is populated here for the first time — no MCP caller ever passed
one, so the field was always null. It now reports the display calendar, and
is the first entry of `calendars`.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.linked_calendar_seeding import USER_ID, seed_shared_event
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)

pytestmark = pytest.mark.integration


async def _call_tool(client: Any, name: str, arguments: dict[str, Any]) -> Any:
    return await call_mcp_tool(client, name, arguments)


@pytest.fixture
async def shared_event(clean_database: AsyncConnection) -> dict[str, Any]:
    """One journal displayed in Work, also held by Personal."""
    journal_id, work, personal = await seed_shared_event(clean_database)
    return {"journal_id": journal_id, "work": work, "personal": personal}


class TestGetJournalReportsEveryCalendar:
    async def test_both_calendars_are_listed(
        self, authenticated_lifespan_client, shared_event: dict[str, Any]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "get_journal",
                {"journal_id": shared_event["journal_id"]},
            )

        assert [c["id"] for c in payload["calendars"]] == [
            shared_event["work"],
            shared_event["personal"],
        ]

    async def test_the_display_calendar_leads_and_fills_the_calendar_field(
        self, authenticated_lifespan_client, shared_event: dict[str, Any]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "get_journal",
                {"journal_id": shared_event["journal_id"]},
            )

        assert payload["calendars"][0]["id"] == shared_event["work"]
        assert payload["calendar"]["id"] == shared_event["work"]
        assert payload["calendar"]["name"] == "Work"

    async def test_a_journal_with_no_calendar_reports_none(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        now = datetime.now(UTC)
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content,
                                      event_date_range_start,
                                      event_date_range_end)
                VALUES (:user_id, 'Just a note', '', :start, :start)
                RETURNING id
            """),
            {"user_id": USER_ID, "start": now},
        )
        journal_id = int(result.scalar_one())

        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client, "get_journal", {"journal_id": journal_id}
            )

        assert payload["calendars"] == []
        assert payload["calendar"] is None

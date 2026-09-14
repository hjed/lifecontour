"""Integration tests for the outdoor dashboard MCP tool.

Exercises ``get_outdoor_dashboard`` end-to-end over the mounted MCP HTTP
server. Journals are seeded through the real repositories on the shared
savepoint connection (anchored on ``datetime.now(UTC)``), so the MCP app
under test sees them and outcomes are deterministic. The single tool returns
all four dashboard sections (spec §5 "Outdoor dashboard data").
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastmcp import Client, FastMCP
from sqlalchemy.ext.asyncio import AsyncConnection

from app.mcp.domains.journals.tools import register_journal_tools
from tests.integration.journal.outdoor_activity_seeding import (
    OTHER_USER_ID,
    Seeder,
)
from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def seeder(async_connection: AsyncConnection) -> Seeder:
    return Seeder(async_connection)


async def _call_tool(
    client: Any, name: str, arguments: dict[str, Any], req_id: int = 1
) -> dict[str, Any]:
    response = await client.post(
        "/mcp-server/mcp",
        json=sessionless_mcp_request(
            "tools/call", {"name": name, "arguments": arguments}, request_id=req_id
        ),
        headers=sessionless_mcp_headers("tools/call", name),
    )
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def test_outdoor_dashboard_tool_registered() -> None:
    mcp: FastMCP[None] = FastMCP("TestServer")
    register_journal_tools(mcp)

    async with Client(mcp) as client:
        tool_names = [tool.name for tool in await client.list_tools()]

    assert "get_outdoor_dashboard" in tool_names


async def test_get_outdoor_dashboard_returns_all_four_sections(
    authenticated_lifespan_client,
    seeder: Seeder,
) -> None:
    now = datetime.now(UTC)
    # Upcoming: one future outdoor journal (another user's must not leak).
    upcoming_id = await seeder.create_outdoor_journal(
        title="Upcoming trip", start=now + timedelta(days=3)
    )
    await seeder.create_outdoor_journal(
        title="Theirs", user_id=OTHER_USER_ID, start=now + timedelta(days=4)
    )
    # Totals: a canyoning trip 10 days ago (both windows); the abseiling
    # journals below land at -100/-50 days (365-day window only).
    await seeder.create_incomplete_canyoning_journal(
        title="Past canyon", start=now - timedelta(days=10)
    )
    # Checked-out gear: one open checkout.
    rope = await seeder.create_gear_item(name="Rope")
    gear_journal_id = await seeder.create_gear_usage_journal(
        rope,
        title="Out now",
        start=now - timedelta(days=2),
        end=now + timedelta(days=1),
    )
    # Templates done: one template referenced by two abseiling journals.
    template_id = await seeder.create_template(
        name="Empress Falls", template_type="canyoning"
    )
    await seeder.create_abseiling_journal(
        title="First run", start=now - timedelta(days=100), template_id=template_id
    )
    await seeder.create_abseiling_journal(
        title="Second run", start=now - timedelta(days=50), template_id=template_id
    )

    async with authenticated_lifespan_client() as client:
        payload = await _call_tool(client, "get_outdoor_dashboard", {})

    assert "error" not in payload, payload
    assert [entry["journal_id"] for entry in payload["upcoming_activities"]] == [
        upcoming_id
    ]
    upcoming = payload["upcoming_activities"][0]
    assert upcoming["title"] == "Upcoming trip"
    assert upcoming["is_planning"] is False
    assert upcoming["event_date_range"]["start"] is not None
    assert [entry["journal_id"] for entry in payload["checked_out_gear"]] == [
        gear_journal_id
    ]
    gear = payload["checked_out_gear"][0]
    assert gear["gear_item_id"] == rope
    assert gear["name"] == "Rope"
    assert gear["checked_out_since"] is not None
    assert payload["activity_totals_last_30_days"] == {"canyoning": 1}
    assert payload["activity_totals_last_365_days"] == {
        "abseiling_trip": 2,
        "canyoning": 1,
    }
    assert payload["total_activities_last_30_days"] == 1
    assert payload["total_activities_last_365_days"] == 3
    assert payload["templates_done"] == {
        "canyoning": [
            {"template_id": template_id, "name": "Empress Falls", "done_count": 2}
        ]
    }
    # Both runs are 50+ days old, so the template is done but not done recently.
    assert payload["templates_done_last_30_days"] == 0
    assert payload["summary"] == (
        "Dashboard: 1 upcoming activity, 1 gear item checked out, "
        "1 outdoor activity in the last 30 days, 1 unique template done "
        "(0 in the last 30 days)."
    )


async def test_get_outdoor_dashboard_empty(
    authenticated_lifespan_client,
) -> None:
    async with authenticated_lifespan_client() as client:
        payload = await _call_tool(client, "get_outdoor_dashboard", {})

    assert "error" not in payload, payload
    assert payload["upcoming_activities"] == []
    assert payload["checked_out_gear"] == []
    assert payload["activity_totals_last_30_days"] == {}
    assert payload["activity_totals_last_365_days"] == {}
    assert payload["total_activities_last_30_days"] == 0
    assert payload["total_activities_last_365_days"] == 0
    assert payload["templates_done"] == {}
    assert payload["templates_done_last_30_days"] == 0
    assert payload["summary"] == (
        "Dashboard: 0 upcoming activities, 0 gear items checked out, "
        "0 outdoor activities in the last 30 days, 0 unique templates done "
        "(0 in the last 30 days)."
    )

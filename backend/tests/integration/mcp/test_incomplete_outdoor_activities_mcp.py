"""Integration tests for the incomplete outdoor activities MCP tools.

Exercises ``list_incomplete_outdoor_activities`` / ``dismiss_incomplete_outdoor_activity``
/ ``undismiss_incomplete_outdoor_activity`` end-to-end over the mounted MCP HTTP
server. Journals are seeded through the real repositories on the shared savepoint
connection, so the MCP app under test sees them and outcomes are deterministic.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from core_shared.models.history import Provenance
from fastmcp import Client, FastMCP
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.outdoor_activity_dismissal_repository import (
    SqlOutdoorActivityDismissalRepository,
)
from app.mcp.domains.journals.tools import register_journal_tools
from tests.integration.journal.outdoor_activity_seeding import (
    OTHER_USER_ID,
    USER_ID,
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


async def _fetch_dismissal_provenance(
    async_connection: AsyncConnection, journal_id: int
) -> str | None:
    result = await async_connection.execute(
        text(
            "SELECT provenance FROM outdoor_activity_dismissals"
            " WHERE journal_id = :journal_id"
        ),
        {"journal_id": journal_id},
    )
    return result.scalar()


async def test_incomplete_outdoor_activity_tools_registered() -> None:
    mcp: FastMCP[None] = FastMCP("TestServer")
    register_journal_tools(mcp)

    async with Client(mcp) as client:
        tool_names = [tool.name for tool in await client.list_tools()]

    for expected in (
        "list_incomplete_outdoor_activities",
        "dismiss_incomplete_outdoor_activity",
        "undismiss_incomplete_outdoor_activity",
    ):
        assert expected in tool_names, f"Tool {expected} not registered"


async def test_list_incomplete_via_mcp(
    authenticated_lifespan_client,
    seeder: Seeder,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal()

    async with authenticated_lifespan_client() as client:
        payload = await _call_tool(client, "list_incomplete_outdoor_activities", {})

    assert "error" not in payload, payload
    assert payload["total_count"] == 1
    entry = payload["activities"][0]
    assert entry["journal_id"] == journal_id
    assert entry["title"] == "Empty canyon"
    assert entry["reasons"] == [
        "no_attributes",
        "missing_template",
        "no_participants",
    ]
    assert "canyoning" in entry["subtypes"]
    assert entry["event_date_range"]["start"] is not None
    assert entry["dismissed"] is False


async def test_list_incomplete_include_dismissed_via_mcp(
    authenticated_lifespan_client,
    seeder: Seeder,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal()

    async with authenticated_lifespan_client() as client:
        dismissed = await _call_tool(
            client,
            "dismiss_incomplete_outdoor_activity",
            {"journal_id": journal_id},
        )
        assert dismissed["dismissed"] is True

        default_listing = await _call_tool(
            client, "list_incomplete_outdoor_activities", {}, req_id=2
        )
        assert default_listing["total_count"] == 0

        listing = await _call_tool(
            client,
            "list_incomplete_outdoor_activities",
            {"include_dismissed": True},
            req_id=3,
        )

    assert "error" not in listing, listing
    assert listing["total_count"] == 1
    entry = listing["activities"][0]
    assert entry["journal_id"] == journal_id
    assert entry["dismissed"] is True


async def test_list_incomplete_via_mcp_excludes_future_activities(
    authenticated_lifespan_client,
    seeder: Seeder,
) -> None:
    """The MCP listing matches the REST endpoint: started activities only."""
    now = datetime.now(UTC)
    past_id = await seeder.create_incomplete_canyoning_journal(
        title="Past canyon", start=now - timedelta(days=3)
    )
    await seeder.create_incomplete_canyoning_journal(
        title="Future canyon", start=now + timedelta(days=10)
    )

    async with authenticated_lifespan_client() as client:
        payload = await _call_tool(client, "list_incomplete_outdoor_activities", {})

    assert "error" not in payload, payload
    assert payload["total_count"] == 1
    assert [entry["journal_id"] for entry in payload["activities"]] == [past_id]


async def test_dismiss_via_mcp_records_mcp_provenance_and_removes_entry(
    authenticated_lifespan_client,
    seeder: Seeder,
    async_connection: AsyncConnection,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal()

    async with authenticated_lifespan_client() as client:
        payload = await _call_tool(
            client,
            "dismiss_incomplete_outdoor_activity",
            {"journal_id": journal_id},
        )
        assert "error" not in payload, payload
        assert payload["journal_id"] == journal_id
        assert payload["dismissed"] is True
        assert payload["provenance"] == "mcp"

        listing = await _call_tool(
            client, "list_incomplete_outdoor_activities", {}, req_id=2
        )

    assert listing["total_count"] == 0
    assert listing["activities"] == []
    assert (
        await _fetch_dismissal_provenance(async_connection, journal_id)
        == Provenance.MCP.value
    )


async def test_redismiss_via_mcp_refreshes_provenance(
    authenticated_lifespan_client,
    seeder: Seeder,
    async_connection: AsyncConnection,
) -> None:
    """Re-dismissing an already-dismissed journal refreshes its provenance."""
    journal_id = await seeder.create_incomplete_canyoning_journal()
    await SqlOutdoorActivityDismissalRepository(async_connection).dismiss(
        journal_id=journal_id, user_id=USER_ID, provenance=Provenance.UI
    )

    async with authenticated_lifespan_client() as client:
        payload = await _call_tool(
            client,
            "dismiss_incomplete_outdoor_activity",
            {"journal_id": journal_id},
        )

    assert "error" not in payload, payload
    assert payload["dismissed"] is True
    assert (
        await _fetch_dismissal_provenance(async_connection, journal_id)
        == Provenance.MCP.value
    )


async def test_dismiss_unknown_and_foreign_journal_returns_not_found(
    authenticated_lifespan_client,
    seeder: Seeder,
    async_connection: AsyncConnection,
) -> None:
    foreign_journal_id = await seeder.create_incomplete_canyoning_journal(
        title="Someone else's canyon", user_id=OTHER_USER_ID
    )

    async with authenticated_lifespan_client() as client:
        unknown = await _call_tool(
            client,
            "dismiss_incomplete_outdoor_activity",
            {"journal_id": 999999},
        )
        assert unknown["error"] == "Journal not found"

        foreign = await _call_tool(
            client,
            "dismiss_incomplete_outdoor_activity",
            {"journal_id": foreign_journal_id},
            req_id=2,
        )
        assert foreign["error"] == "Journal not found"

        unknown_undismiss = await _call_tool(
            client,
            "undismiss_incomplete_outdoor_activity",
            {"journal_id": 999999},
            req_id=3,
        )
        assert unknown_undismiss["error"] == "Journal not found"

        foreign_undismiss = await _call_tool(
            client,
            "undismiss_incomplete_outdoor_activity",
            {"journal_id": foreign_journal_id},
            req_id=4,
        )
        assert foreign_undismiss["error"] == "Journal not found"

    assert (
        await _fetch_dismissal_provenance(async_connection, foreign_journal_id) is None
    )


async def test_undismiss_via_mcp_restores_entry_and_is_idempotent(
    authenticated_lifespan_client,
    seeder: Seeder,
) -> None:
    journal_id = await seeder.create_incomplete_canyoning_journal()

    async with authenticated_lifespan_client() as client:
        dismissed = await _call_tool(
            client,
            "dismiss_incomplete_outdoor_activity",
            {"journal_id": journal_id},
        )
        assert dismissed["dismissed"] is True

        restored = await _call_tool(
            client,
            "undismiss_incomplete_outdoor_activity",
            {"journal_id": journal_id},
            req_id=2,
        )
        assert "error" not in restored, restored
        assert restored["journal_id"] == journal_id
        assert restored["dismissed"] is False
        assert restored["was_dismissed"] is True

        listing = await _call_tool(
            client, "list_incomplete_outdoor_activities", {}, req_id=3
        )
        assert [entry["journal_id"] for entry in listing["activities"]] == [journal_id]

        noop = await _call_tool(
            client,
            "undismiss_incomplete_outdoor_activity",
            {"journal_id": journal_id},
            req_id=4,
        )

    assert "error" not in noop, noop
    assert noop["dismissed"] is False
    assert noop["was_dismissed"] is False

"""The mounted MCP server answers both protocol eras.

FastMCP 4 serves the sessionless ``2026-07-28`` protocol — every request
carries its own protocol version and client capabilities, and there is no
``initialize`` handshake or ``mcp-session-id`` — alongside the session-based
handshake that older clients still speak. The era is chosen per request by the
``MCP-Protocol-Version`` header, and there is no server setting to drop either,
so both are pinned here against the real app.
"""

from typing import Any

import pytest
from mcp_types.jsonrpc import HEADER_MISMATCH
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.models.journal_tag import JournalTag
from tests.integration.mcp.http_helpers import (
    MCP_PATH,
    call_mcp_tool,
    extract_mcp_json_payload,
    mcp_headers,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)


async def _save_tag(connection: AsyncConnection, name: str) -> None:
    await SqlJournalTagRepository(connection).save(JournalTag(name=name))


async def _initialize_session(client: Any) -> str:
    """Open a handshake-era session and return its id.

    Asks for the newest handshake version explicitly: the SDK's latest
    protocol is the sessionless one, which has no ``initialize`` at all.
    """
    response = await client.post(
        MCP_PATH,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_HANDSHAKE_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        },
        headers=mcp_headers(),
    )
    assert response.status_code == 200, response.text
    session_id = response.headers.get("mcp-session-id")
    assert isinstance(session_id, str)

    initialized = await client.post(
        MCP_PATH,
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers={**mcp_headers(), "mcp-session-id": session_id},
    )
    assert initialized.status_code in {200, 202, 204}
    return session_id


async def _call_tool_in_session(
    client: Any, session_id: str, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        MCP_PATH,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
        headers={**mcp_headers(), "mcp-session-id": session_id},
    )
    assert response.status_code == 200, response.text
    return extract_mcp_json_payload(response.text)


@pytest.mark.integration
class TestSessionlessProtocol:
    """A 2026-07-28 client needs no handshake and gets no session."""

    async def test_a_tool_call_needs_no_handshake_and_opens_no_session(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """The first request is the tool call itself, answered as plain JSON."""
        await _save_tag(clean_database, "sessionless")

        async with authenticated_lifespan_client() as client:
            response = await client.post(
                MCP_PATH,
                json=sessionless_mcp_request(
                    "tools/call",
                    {"name": "list_journal_tags", "arguments": {}},
                ),
                headers=sessionless_mcp_headers("tools/call", "list_journal_tags"),
            )

        assert response.status_code == 200, response.text
        assert "mcp-session-id" not in response.headers
        assert response.headers["content-type"].startswith("application/json")
        payload = extract_mcp_json_payload(response.text)
        assert [tag["name"] for tag in payload["tags"]] == ["sessionless"]

    async def test_the_call_helper_reaches_the_user_scoped_dependencies(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Dishka resolves the connection for a sessionless request too."""
        await _save_tag(clean_database, "via-helper")

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(client, "list_journal_tags", {})

        assert payload["total_count"] == 1

    async def test_tools_are_listed_without_a_handshake(
        self, authenticated_lifespan_client
    ) -> None:
        async with authenticated_lifespan_client() as client:
            response = await client.post(
                MCP_PATH,
                json=sessionless_mcp_request("tools/list", {}),
                headers=sessionless_mcp_headers("tools/list"),
            )

        assert response.status_code == 200, response.text
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        assert {"list_journal_tags", "retarget_task"} <= names

    async def test_a_header_that_contradicts_the_body_is_rejected(
        self, authenticated_lifespan_client
    ) -> None:
        """Gateways route on the headers, so they must agree with the body."""
        async with authenticated_lifespan_client() as client:
            response = await client.post(
                MCP_PATH,
                json=sessionless_mcp_request(
                    "tools/call",
                    {"name": "list_journal_tags", "arguments": {}},
                ),
                headers=sessionless_mcp_headers("tools/call", "delete_journal_tag"),
            )

        assert response.status_code == 400
        error: dict[str, Any] = response.json()["error"]
        assert error["code"] == HEADER_MISMATCH


@pytest.mark.integration
class TestHandshakeProtocol:
    """A session-based client still initializes and calls tools as before."""

    async def test_a_handshake_session_still_calls_tools(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        await _save_tag(clean_database, "handshake")

        async with authenticated_lifespan_client() as client:
            session_id = await _initialize_session(client)
            payload = await _call_tool_in_session(
                client, session_id, "list_journal_tags", {}
            )

        assert [tag["name"] for tag in payload["tags"]] == ["handshake"]

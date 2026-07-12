"""Unit tests for the shared read-only MCP toolset exposed to Gemini."""

from __future__ import annotations

from fastmcp import Client

from app.mcp.shared.read_only_tools import (
    READ_ONLY_TOOL_NAMES,
    create_read_only_mcp_server,
)


def test_toolset_includes_contact_journal_lookup() -> None:
    """get_contact_journals lets the model pull recent meetings per contact."""
    assert "get_contact_journals" in READ_ONLY_TOOL_NAMES


async def test_server_exposes_all_read_only_tools() -> None:
    """Every declared read-only tool resolves from the main MCP server."""
    server = await create_read_only_mcp_server("Test Tools")

    async with Client(server) as client:
        exposed = {tool.name for tool in await client.list_tools()}

    assert set(READ_ONLY_TOOL_NAMES) <= exposed

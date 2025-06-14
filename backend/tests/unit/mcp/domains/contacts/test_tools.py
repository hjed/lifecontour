"""
Unit tests for contact domain MCP tools.

Tests the MCP tools for contact management functionality.
Note: Full functionality testing with mocked services is done in integration tests.
These unit tests focus on tool registration and basic structure.
"""

import pytest
from fastmcp import Client, FastMCP

from app.mcp.domains.contacts.tools import register_contact_tools


class TestContactTools:
    """Test contact MCP tools registration and functionality."""

    @pytest.fixture
    def mcp_server(self):
        """Create FastMCP server for testing."""
        from typing import Any

        mcp: Any = FastMCP("TestServer")
        register_contact_tools(mcp)
        return mcp

    def test_register_contact_tools(self, mcp_server):
        """Test that contact tools are registered successfully."""
        # Tools are already registered in the mcp_server fixture
        # If we get here without exceptions, registration was successful
        assert True

    @pytest.mark.asyncio
    async def test_list_tools(self, mcp_server):
        """Test that contact tools are properly registered and listed."""
        # Use FastMCP Client for in-memory testing
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list - the response might be a list or have a tools attribute
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Verify contact tools are registered
            tool_names = [tool.name for tool in tools]
            expected_tools = [
                "get_contact",
                "search_contacts",
                "global_search",
                "create_contact",
                "list_contacts",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names, (
                    f"Tool {expected_tool} not found in registered tools"
                )

    # Note: The actual tool functionality is tested in integration tests
    # These unit tests focus on tool registration and basic structure
    # For full functionality testing with mocked services, see integration tests

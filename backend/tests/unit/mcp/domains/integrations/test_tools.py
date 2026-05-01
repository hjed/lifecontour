"""
Unit tests for integration domain MCP tools.

Tests tool registration and basic structure.
Full functionality is tested in integration tests.
"""

import pytest
from fastmcp import Client, FastMCP

from app.mcp.domains.integrations.tools import register_integration_tools


class TestIntegrationTools:
    """Test integration MCP tools registration and functionality."""

    @pytest.fixture
    def mcp_server(self):
        """Create FastMCP server for testing."""
        from typing import Any

        mcp: Any = FastMCP("TestServer")
        register_integration_tools(mcp)
        return mcp

    def test_register_integration_tools(self, mcp_server):
        """Test that integration tools are registered successfully."""
        assert mcp_server is not None

    @pytest.mark.asyncio
    async def test_list_integrations_tool_registered(self, mcp_server):
        """Test that list_integrations tool is registered."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool_names = [tool.name for tool in tools]
            assert "list_integrations" in tool_names, (
                "list_integrations tool not found in registered tools"
            )

    @pytest.mark.asyncio
    async def test_list_integrations_tool_description(self, mcp_server):
        """Test that list_integrations tool has a descriptive description."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next((t for t in tools if t.name == "list_integrations"), None)
            assert tool is not None
            assert tool.description is not None

            # Should mention key concepts for AI understanding
            desc = tool.description.lower()
            assert "integration" in desc
            assert "status" in desc

    @pytest.mark.asyncio
    async def test_list_integrations_tool_has_no_required_inputs(self, mcp_server):
        """Test that list_integrations doesn't require any user inputs.

        All parameters (user_id, connection, registry_service) are injected
        via DI/depends, so there should be no required user-facing inputs.
        """
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next((t for t in tools if t.name == "list_integrations"), None)
            assert tool is not None
            assert tool.inputSchema is not None

            # DI-injected params should not appear as required user inputs
            required = tool.inputSchema.get("required", [])
            assert "user_id" not in required
            assert "connection" not in required
            assert "registry_service" not in required

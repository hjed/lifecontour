"""
Unit tests for journal domain MCP tools.

Tests the MCP tools for journal management functionality.
Note: Full functionality testing with mocked services is done in integration tests.
These unit tests focus on tool registration and basic structure.
"""

import pytest
from fastmcp import Client, FastMCP

from app.mcp.domains.journals.tools import register_journal_tools


class TestJournalTools:
    """Test journal MCP tools registration and functionality."""

    @pytest.fixture
    def mcp_server(self):
        """Create FastMCP server for testing."""
        from typing import Any

        mcp: Any = FastMCP("TestServer")
        register_journal_tools(mcp)
        return mcp

    def test_register_journal_tools(self, mcp_server):
        """Test that journal tools are registered successfully."""
        # Tools are already registered in the mcp_server fixture
        # If we get here without exceptions, registration was successful
        assert True

    @pytest.mark.asyncio
    async def test_list_tools(self, mcp_server):
        """Test that journal tools are properly registered and listed."""
        # Use FastMCP Client for in-memory testing
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list - the response might be a list or have a tools attribute
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Verify journal tools are registered
            tool_names = [tool.name for tool in tools]
            expected_tools = [
                "create_journal_entry",
                "update_journal_entry",
                "get_journal",
                "search_journals",
                "delete_journal",
                "get_contact_journals",
                "link_journal_to_contact",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names, (
                    f"Tool {expected_tool} not found in registered tools"
                )

    @pytest.mark.asyncio
    async def test_create_journal_entry_tool_registration(self, mcp_server):
        """Test that create_journal_entry tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the create_journal_entry tool
            create_tool = None
            for tool in tools:
                if tool.name == "create_journal_entry":
                    create_tool = tool
                    break

            assert create_tool is not None, "create_journal_entry tool not found"
            assert create_tool.description is not None
            assert "create" in create_tool.description.lower()
            assert create_tool.inputSchema is not None

            # Verify the tool has the expected parameter
            properties = create_tool.inputSchema.get("properties", {})
            assert "journal_data" in properties
            assert properties["journal_data"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_update_journal_entry_tool_registration(self, mcp_server):
        """Test that update_journal_entry tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the update_journal_entry tool
            update_tool = None
            for tool in tools:
                if tool.name == "update_journal_entry":
                    update_tool = tool
                    break

            assert update_tool is not None, "update_journal_entry tool not found"
            assert update_tool.description is not None
            assert "update" in update_tool.description.lower()
            assert update_tool.inputSchema is not None

            # Verify the tool has the expected parameters
            properties = update_tool.inputSchema.get("properties", {})
            assert "journal_id" in properties
            assert "journal_data" in properties

    @pytest.mark.asyncio
    async def test_get_journal_tool_registration(self, mcp_server):
        """Test that get_journal tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the get_journal tool
            get_tool = None
            for tool in tools:
                if tool.name == "get_journal":
                    get_tool = tool
                    break

            assert get_tool is not None, "get_journal tool not found"
            assert get_tool.description is not None
            assert get_tool.inputSchema is not None

            # Verify the tool has the expected parameters
            properties = get_tool.inputSchema.get("properties", {})
            assert "journal_id" in properties
            assert "include_children" in properties

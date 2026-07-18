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
    async def test_toggle_contact_favourite_tool_registered(self, mcp_server):
        """Test that toggle_contact_favourite tool is registered."""
        from fastmcp.client import Client

        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Verify toggle_contact_favourite tool is registered
            tool_names = [tool.name for tool in tools]
            assert "toggle_contact_favourite" in tool_names, (
                "toggle_contact_favourite tool not found in registered tools"
            )

    @pytest.mark.asyncio
    async def test_list_contact_tags_tool_registered(self, mcp_server):
        """Test that list_contact_tags tool is registered under its scoped name."""
        from fastmcp.client import Client

        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Verify list_contact_tags tool is registered
            tool_names = [tool.name for tool in tools]
            assert "list_contact_tags" in tool_names, (
                "list_contact_tags tool not found in registered tools"
            )
            assert "list_tags" not in tool_names, (
                "list_tags should have been renamed to list_contact_tags"
            )

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
                "update_contact",
                "list_contacts",
                "toggle_contact_favourite",
                "list_contact_tags",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names, (
                    f"Tool {expected_tool} not found in registered tools"
                )

    @pytest.mark.asyncio
    async def test_update_contact_tool_registration(self, mcp_server):
        """Test that update_contact tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the update_contact tool
            update_tool = None
            for tool in tools:
                if tool.name == "update_contact":
                    update_tool = tool
                    break

            assert update_tool is not None, "update_contact tool not found"
            assert update_tool.description is not None
            assert "update" in update_tool.description.lower()
            assert update_tool.inputSchema is not None

            # Verify the tool has the expected parameter
            properties = update_tool.inputSchema.get("properties", {})
            assert "request" in properties

    def test_contact_update_request_schema_validation(self):
        """Test that ContactUpdateRequest schema validates correctly."""
        import json

        from app.mcp.domains.contacts.schemas import ContactUpdateRequest

        # Test valid update request with explicit construction
        request = ContactUpdateRequest(
            contact_id=123,
            first_name="Updated",
            last_name="Name",
            email="updated@example.com",
            tags=["work", "important"],
        )
        assert request.contact_id == 123
        assert request.first_name == "Updated"
        assert request.last_name == "Name"
        assert request.email == "updated@example.com"
        assert request.tags == ["work", "important"]

        # Test minimal update request (only contact_id required)
        minimal_request = ContactUpdateRequest(contact_id=456)
        assert minimal_request.contact_id == 456
        assert minimal_request.first_name is None
        assert minimal_request.tags is None

        # Test JSON serialization/deserialization
        valid_data = {
            "contact_id": 123,
            "first_name": "Updated",
            "last_name": "Name",
            "email": "updated@example.com",
            "tags": ["work", "important"],
        }
        json_str = json.dumps(valid_data)
        parsed_data = json.loads(json_str)
        # Use model_validate for proper type handling
        parsed_request = ContactUpdateRequest.model_validate(parsed_data)
        assert parsed_request.contact_id == 123

    # Note: The actual tool functionality is tested in integration tests
    # These unit tests focus on tool registration and basic structure
    # For full functionality testing with mocked services, see integration tests

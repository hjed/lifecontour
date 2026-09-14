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
    async def test_update_contact_tag_tool_schema(self, mcp_server):
        """Test update_contact_tag exposes the editable fields and requires only the id."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next(t for t in tools if t.name == "update_contact_tag")

            schema = tool.input_schema
            properties = schema["properties"]
            for field in ("tag_id", "name", "color", "description", "parent_id"):
                assert field in properties, f"{field} should be an update parameter"

            # Contact tag IDs cross the MCP boundary as strings so they round-trip
            # from list_contact_tags into the write tools (issue #1139).
            assert properties["tag_id"]["type"] == "string"
            # parent_id is optional, so it is a string-or-null union.
            parent_types = {
                option["type"] for option in properties["parent_id"]["anyOf"]
            }
            assert parent_types == {"string", "null"}

            # Only the tag id is mandatory: every other field is an optional edit.
            assert schema.get("required", []) == ["tag_id"]

            # move_to_root is how callers clear a parent, since an omitted
            # parent_id means "leave the parent alone".
            assert "move_to_root" in properties

            assert tool.description is not None
            assert "update_journal_tag" in tool.description, (
                "contact tag tool should point at the journal tag equivalent"
            )

    @pytest.mark.asyncio
    async def test_delete_contact_tag_tool_schema(self, mcp_server):
        """Test delete_contact_tag takes only the tag id and warns about un-assignment."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next(t for t in tools if t.name == "delete_contact_tag")

            schema = tool.input_schema
            assert "tag_id" in schema["properties"]
            # Contact tag IDs are strings across the MCP surface (issue #1139).
            assert schema["properties"]["tag_id"]["type"] == "string"
            assert schema.get("required", []) == ["tag_id"]

            assert tool.description is not None
            # Deleting un-assigns the tag from every contact, so the docstring
            # must say so rather than letting callers assume it is blocked.
            # Assert the phrase, not just the word "contact" — the tool name
            # alone would satisfy that and the contract would go undefended.
            assert "every contact" in tool.description.lower()
            assert "re-parented" in tool.description.lower()
            assert "delete_journal_tag" in tool.description, (
                "contact tag tool should point at the journal tag equivalent"
            )

    @pytest.mark.asyncio
    async def test_merge_contact_tags_tool_schema(self, mcp_server):
        """Test merge_contact_tags is registered under its scoped name.

        Renamed from the unscoped ``merge_tags`` when ``merge_journal_tag``
        landed beside it, matching ``list_contact_tags`` and the other scoped
        tag tools.
        """
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool_names = [tool.name for tool in tools]
            assert "merge_contact_tags" in tool_names
            assert "merge_tags" not in tool_names, (
                "merge_tags should have been renamed to merge_contact_tags"
            )

            tool = next(t for t in tools if t.name == "merge_contact_tags")
            properties = tool.input_schema["properties"]
            assert "source_id" in properties
            assert "target_id" in properties
            # Contact tag IDs are strings across the MCP surface (issue #1139).
            assert properties["source_id"]["type"] == "string"
            assert properties["target_id"]["type"] == "string"

            assert tool.description is not None
            assert "merge_journal_tag" in tool.description, (
                "contact tag tool should point at the journal tag equivalent"
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
                "delete_contact_tag",
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
            assert update_tool.input_schema is not None

            # Verify the tool has the expected parameter
            properties = update_tool.input_schema.get("properties", {})
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

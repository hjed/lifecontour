"""
Unit tests for contact domain MCP tools.

Tests the MCP tools for contact management functionality.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client, FastMCP

from app.core.contacts.models.entities import (
    Contact,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from app.mcp.domains.contacts.tools import register_contact_tools


class TestContactTools:
    """Test contact MCP tools registration and functionality."""

    @pytest.fixture
    def mock_contact_service(self):
        """Mock contact service for testing."""
        service = AsyncMock()
        return service

    @pytest.fixture
    def mcp_server(self):
        """Create FastMCP server for testing."""
        return FastMCP("TestServer")

    @pytest.fixture
    def sample_contact(self):
        """Create a sample contact for testing."""
        from app.core.contacts.models.value_objects import TagName

        # Create contact with basic info
        contact = Contact(
            id=123,
            first_name="John",
            last_name="Doe",
        )

        # Add related data to the contact
        contact.methods = [
            ContactMethod(
                id=1,
                contact_id=123,
                method_type=MethodType.EMAIL,
                value="john@example.com",
                is_primary=True,
            ),
            ContactMethod(
                id=2,
                contact_id=123,
                method_type=MethodType.PHONE,
                value="+1234567890",
                is_primary=True,
            ),
        ]

        contact.tags = [
            Tag(id=1, name=TagName("friend")),
            Tag(id=2, name=TagName("work")),
        ]

        contact.notes = [
            ContactNote(
                id=1,
                contact_id=123,
                content="Great colleague and friend",
                created_at=None,
            ),
        ]

        return contact

    def test_register_contact_tools(self, mcp_server):
        """Test that contact tools are registered successfully."""
        # Register tools - should not raise any exceptions
        register_contact_tools(mcp_server)

        # If we get here without exceptions, registration was successful
        assert True

    @pytest.mark.asyncio
    async def test_get_contact_tool_success(self, mock_contact_service, sample_contact):
        """Test successful contact retrieval through MCP tool."""
        # Setup mock service to return our sample contact
        mock_contact_service.get_contact_by_id.return_value = sample_contact

        # Create server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock the get_contact_service dependency
        with patch(
            "app.mcp.domains.contacts.tools.get_contact_service"
        ) as mock_get_service:
            mock_get_service.return_value = mock_contact_service

            # Use FastMCP Client for in-memory testing
            async with Client(mcp) as client:
                # Call the get_contact tool
                result = await client.call_tool("get_contact", {"contact_id": 123})

                # Parse the JSON response - result is a list of content objects
                response_data = json.loads(result[0].text)

                # Verify the response structure and content
                assert response_data["id"] == "123"
                assert response_data["name"] == "John Doe"
                assert response_data["email"] == "john@example.com"
                assert response_data["phone"] == "+1234567890"
                assert response_data["tags"] == ["friend", "work"]
                assert "John Doe is a contact" in response_data["summary"]
                assert "tagged as: friend, work" in response_data["summary"]
                assert "Primary email: john@example.com" in response_data["summary"]
                assert "Primary phone: +1234567890" in response_data["summary"]
                assert "Notes: Great colleague and friend" in response_data["summary"]

                # Verify the mock was called correctly
                mock_contact_service.get_contact_by_id.assert_called_once_with(123)

    @pytest.mark.asyncio
    async def test_get_contact_tool_not_found(self, mock_contact_service):
        """Test contact not found handling."""
        # Setup mock to return None (contact not found)
        mock_contact_service.get_contact_by_id.return_value = None

        # Create server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock the get_contact_service dependency
        with patch(
            "app.mcp.domains.contacts.tools.get_contact_service"
        ) as mock_get_service:
            mock_get_service.return_value = mock_contact_service

            # Use FastMCP Client for in-memory testing
            async with Client(mcp) as client:
                # Call the get_contact tool with non-existent ID
                result = await client.call_tool("get_contact", {"contact_id": 999})

                # Parse the JSON response - result is a list of content objects
                response_data = json.loads(result[0].text)

                # Verify error response structure
                assert response_data["error"] == "Contact not found"
                assert response_data["contact_id"] == 999
                assert "No contact exists with ID: 999" in response_data["message"]

                # Verify the mock was called correctly
                mock_contact_service.get_contact_by_id.assert_called_once_with(999)

    @pytest.mark.asyncio
    async def test_get_contact_tool_exception_handling(self, mock_contact_service):
        """Test contact tool exception handling."""
        # Setup mock to raise an exception
        mock_contact_service.get_contact_by_id.side_effect = Exception("Database error")

        # Create server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock the get_contact_service dependency
        with patch(
            "app.mcp.domains.contacts.tools.get_contact_service"
        ) as mock_get_service:
            mock_get_service.return_value = mock_contact_service

            # Use FastMCP Client for in-memory testing
            async with Client(mcp) as client:
                # Call the get_contact tool
                result = await client.call_tool("get_contact", {"contact_id": 123})

                # Parse the JSON response - result is a list of content objects
                response_data = json.loads(result[0].text)

                # Verify error response structure
                assert response_data["error"] == "Internal error"
                assert response_data["contact_id"] == 123
                assert (
                    "An error occurred while retrieving the contact"
                    in response_data["message"]
                )

                # Verify the mock was called correctly
                mock_contact_service.get_contact_by_id.assert_called_once_with(123)

    @pytest.mark.asyncio
    async def test_get_contact_tool_list_tools(self):
        """Test that get_contact tool is properly registered and listed."""
        # Create server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Use FastMCP Client for in-memory testing
        async with Client(mcp) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list - the response might be a list or have a tools attribute
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Verify get_contact tool is registered
            tool_names = [tool.name for tool in tools]
            assert "get_contact" in tool_names

            # Find the get_contact tool and verify its schema
            get_contact_tool = next(
                tool for tool in tools if tool.name == "get_contact"
            )
            assert get_contact_tool.description is not None
            assert "Get contact details by ID" in get_contact_tool.description

            # Verify the tool has the correct input schema
            assert get_contact_tool.inputSchema is not None
            properties = get_contact_tool.inputSchema.get("properties", {})
            assert "contact_id" in properties
            assert properties["contact_id"]["type"] == "integer"

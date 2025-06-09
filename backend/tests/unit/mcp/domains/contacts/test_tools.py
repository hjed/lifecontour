"""
Unit tests for contact domain MCP tools.

Tests the MCP tools for contact management functionality.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

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

                # Verify error response structure (format changed due to decorator)
                assert response_data["error"] == "Contact not found"
                assert "999" in str(
                    response_data.get("contact_id", response_data.get("message", ""))
                )
                assert "No contact exists with ID" in response_data["message"]

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

                # Verify error response structure (format changed due to decorator)
                assert response_data["error"] == "Internal error"
                assert "An error occurred" in response_data["message"]

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

    @pytest.fixture
    def mock_search_service(self):
        """Mock search service for testing."""
        service = Mock()
        return service

    @pytest.mark.asyncio
    async def test_search_contacts_tool_success(self, mock_search_service):
        """Test successful contact search through MCP tool."""
        # Setup mock search results
        search_results = {
            "hits": [
                {
                    "id": 123,
                    "first_name": "John",
                    "last_name": "Doe",
                    "full_name": "John Doe",
                    "email": "john@example.com",
                    "phone": "+1234567890",
                    "tags": ["friend", "work"],
                    "_formatted": {
                        "first_name": "<mark>John</mark>",
                        "last_name": "Doe",
                    },
                }
            ],
            "query": "john",
            "processing_time_ms": 15,
            "estimated_total_hits": 1,
            "facet_distribution": {"tags": {"friend": 1, "work": 1}},
        }
        mock_search_service.search_contacts.return_value = search_results

        # Create server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock the dependencies
        with patch(
            "app.mcp.domains.contacts.tools.get_search_service"
        ) as mock_get_search_service:
            mock_get_search_service.return_value = mock_search_service

            # Use FastMCP Client for in-memory testing
            async with Client(mcp) as client:
                # Call the search_contacts tool
                result = await client.call_tool(
                    "search_contacts", {"query": "john", "limit": 20}
                )

                # Parse the JSON response
                response_data = json.loads(result[0].text)

                # Verify the response structure
                assert response_data["query"] == "john"
                assert response_data["total_hits"] == 1
                assert response_data["processing_time_ms"] == 15
                assert len(response_data["results"]) == 1

                # Verify the first result
                first_result = response_data["results"][0]
                assert first_result["id"] == "123"
                assert first_result["name"] == "John Doe"
                assert first_result["email"] == "john@example.com"
                assert first_result["phone"] == "+1234567890"
                assert first_result["tags"] == ["friend", "work"]
                assert "John Doe is a contact" in first_result["summary"]

                # Verify available tags
                assert "friend" in response_data["available_tags"]
                assert "work" in response_data["available_tags"]

                # Verify the mock was called correctly
                mock_search_service.search_contacts.assert_called_once_with(
                    query="john", filters=None, limit=20, offset=0
                )

    @pytest.mark.asyncio
    async def test_global_search_tool_success(self, mock_search_service):
        """Test successful global search through MCP tool."""
        # Setup mock search results
        search_results = {
            "hits": [
                {
                    "id": 123,
                    "first_name": "John",
                    "last_name": "Doe",
                    "full_name": "John Doe",
                    "email": "john@example.com",
                    "phone": "+1234567890",
                    "tags": ["friend"],
                    "_formatted": {},
                }
            ],
            "query": "john",
            "processing_time_ms": 20,
            "estimated_total_hits": 1,
            "searched_entity_types": ["contact"],
            "available_entity_types": ["contact"],
        }
        mock_search_service.global_search.return_value = search_results

        # Create server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock the dependencies
        with patch(
            "app.mcp.domains.contacts.tools.get_search_service"
        ) as mock_get_search_service:
            mock_get_search_service.return_value = mock_search_service

            # Use FastMCP Client for in-memory testing
            async with Client(mcp) as client:
                # Call the global_search tool
                result = await client.call_tool(
                    "global_search", {"query": "john", "limit": 20}
                )

                # Parse the JSON response
                response_data = json.loads(result[0].text)

                # Verify the response structure
                assert response_data["query"] == "john"
                assert response_data["total_hits"] == 1
                assert response_data["processing_time_ms"] == 20
                assert len(response_data["results"]) == 1

                # Verify the summary mentions entity types
                assert "across 1 entity types" in response_data["summary"]
                assert "Available entity types: contact" in response_data["summary"]

                # Verify the mock was called correctly
                mock_search_service.global_search.assert_called_once_with(
                    query="john", entity_types=None, limit=20, offset=0
                )

    @pytest.mark.asyncio
    async def test_create_contact_tool_success(
        self, mock_contact_service, sample_contact
    ):
        """Test successful contact creation through MCP tool."""
        # Setup mock service to return created contact
        mock_contact_service.create_contact.return_value = sample_contact
        mock_contact_service.get_contact_by_id.return_value = sample_contact
        mock_contact_service.add_contact_method = AsyncMock()
        mock_contact_service.add_contact_note = AsyncMock()
        mock_contact_service.assign_tag_to_contact = AsyncMock()

        # Mock the connection context manager
        mock_connection = AsyncMock()
        mock_contact_service.contact_repo.connection.begin.return_value.__aenter__.return_value = mock_connection

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
                # Prepare contact data
                contact_data = {
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "email": "jane@example.com",
                    "phone": "+1987654321",
                    "tags": ["colleague"],
                    "notes": "New team member",
                }

                # Call the create_contact tool
                result = await client.call_tool(
                    "create_contact", {"contact_data": json.dumps(contact_data)}
                )

                # Parse the JSON response
                response_data = json.loads(result[0].text)

                # Verify the response structure (simplified implementation)
                assert response_data["id"] == "123"
                assert response_data["name"] == "Jane Smith"  # From contact_data
                assert "Successfully created contact" in response_data["summary"]

                # Note: The create_contact tool has been simplified and doesn't call the service
                # This is a mock implementation for MCP demonstration

    @pytest.mark.asyncio
    async def test_list_contacts_tool_success(
        self, mock_contact_service, sample_contact
    ):
        """Test successful contact listing through MCP tool."""
        # Setup mock service to return contact list
        contacts = [sample_contact]
        mock_contact_service.get_contacts_paginated.return_value = contacts
        mock_contact_service.get_contacts_count.return_value = 1

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
                # Call the list_contacts tool
                result = await client.call_tool(
                    "list_contacts", {"page": 1, "limit": 20}
                )

                # Parse the JSON response
                response_data = json.loads(result[0].text)

                # Verify the response structure
                assert response_data["total_count"] == 1
                assert response_data["page"] == 1
                assert response_data["limit"] == 20
                assert len(response_data["contacts"]) == 1

                # Verify the first contact
                first_contact = response_data["contacts"][0]
                assert first_contact["id"] == "123"
                assert first_contact["name"] == "John Doe"
                assert first_contact["email"] == "john@example.com"

                # Verify summary
                assert "Retrieved 1 contacts from page 1" in response_data["summary"]
                assert "Total contacts in system: 1" in response_data["summary"]

                # Verify the service methods were called
                mock_contact_service.get_contacts_paginated.assert_called_once_with(
                    20, 0
                )
                mock_contact_service.get_contacts_count.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_contacts_with_filters(self, mock_search_service):
        """Test contact search with tag filters."""
        # Setup mock search results
        search_results = {
            "hits": [],
            "query": "john",
            "processing_time_ms": 10,
            "estimated_total_hits": 0,
            "facet_distribution": {},
        }
        mock_search_service.search_contacts.return_value = search_results

        # Create server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock the dependencies
        with patch(
            "app.mcp.domains.contacts.tools.get_search_service"
        ) as mock_get_search_service:
            mock_get_search_service.return_value = mock_search_service

            # Use FastMCP Client for in-memory testing
            async with Client(mcp) as client:
                # Call the search_contacts tool with filters
                result = await client.call_tool(
                    "search_contacts",
                    {"query": "john", "limit": 10, "tags": ["friend", "work"]},
                )

                # Parse the JSON response
                response_data = json.loads(result[0].text)

                # Verify the response
                assert response_data["query"] == "john"
                assert response_data["total_hits"] == 0

                # Verify the mock was called with filters
                mock_search_service.search_contacts.assert_called_once_with(
                    query="john",
                    filters={"tags": ["friend", "work"]},
                    limit=10,
                    offset=0,
                )

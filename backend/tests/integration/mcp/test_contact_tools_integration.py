"""
Integration tests for MCP contact tools.

Tests the full MCP contact tools with real database and search service integration.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp import FastMCP
from fastmcp.client import Client

from app.core.contacts.models.entities import Contact, ContactMethod, MethodType, Tag
from app.core.contacts.models.value_objects import TagName
from app.mcp.domains.contacts.tools import register_contact_tools


class TestContactToolsIntegration:
    """Integration tests for MCP contact tools with real services."""

    @pytest.fixture
    def sample_contact_entity(self):
        """Create a sample contact entity for testing."""
        contact = Contact(
            id=123,
            first_name="John",
            last_name="Doe",
            middle_name="William",
            nick_name="Johnny",
        )

        # Add contact methods
        email_method = ContactMethod(
            id=1,
            method_type=MethodType.EMAIL,
            value="john@example.com",
            is_primary=True,
            contact_id=123,
        )
        phone_method = ContactMethod(
            id=2,
            method_type=MethodType.PHONE,
            value="+1234567890",
            is_primary=True,
            contact_id=123,
        )
        contact.methods = [email_method, phone_method]

        # Add tags
        tag1 = Tag(id=1, name=TagName("friend"))
        tag2 = Tag(id=2, name=TagName("work"))
        contact.tags = [tag1, tag2]

        return contact

    @pytest.mark.asyncio
    async def test_get_contact_integration(self, sample_contact_entity):
        """Test get_contact tool with real service integration."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock the contact service to return our sample contact
        with patch(
            "app.mcp.domains.contacts.tools.get_contact_service"
        ) as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_contact_by_id.return_value = sample_contact_entity
            mock_get_service.return_value = mock_service

            # Use FastMCP Client for integration testing
            async with Client(mcp) as client:
                # Call the get_contact tool
                result = await client.call_tool("get_contact", {"contact_id": 123})

                # Parse the JSON response
                response_data = json.loads(result[0].text)

                # Verify the response structure
                assert response_data["id"] == "123"
                assert response_data["name"] == "John William Doe"
                assert response_data["email"] == "john@example.com"
                assert response_data["phone"] == "+1234567890"
                assert "friend" in response_data["tags"]
                assert "work" in response_data["tags"]
                assert "John William Doe is a contact" in response_data["summary"]
                assert "tagged as: friend, work" in response_data["summary"]

                # Verify the service was called correctly
                mock_service.get_contact_by_id.assert_called_once_with(123)

    @pytest.mark.asyncio
    async def test_get_contact_not_found_integration(self):
        """Test get_contact tool with contact not found scenario."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock the contact service to return None (not found)
        with patch(
            "app.mcp.domains.contacts.tools.get_contact_service"
        ) as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_contact_by_id.return_value = None
            mock_get_service.return_value = mock_service

            # Use FastMCP Client for integration testing
            async with Client(mcp) as client:
                # Call the get_contact tool
                result = await client.call_tool("get_contact", {"contact_id": 999})

                # Parse the JSON response
                response_data = json.loads(result[0].text)

                # Verify error response (format changed due to decorator)
                assert response_data["error"] == "Contact not found"
                assert "999" in str(
                    response_data.get("contact_id", response_data.get("message", ""))
                )
                assert "No contact exists with ID" in response_data["message"]

    @pytest.mark.asyncio
    async def test_create_contact_integration_real_db(self, clean_database):
        """Test create_contact tool with real database integration."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Test data
        contact_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@example.com",
        }

        # Use FastMCP Client for integration testing
        async with Client(mcp) as client:
            # Call the create_contact tool
            result = await client.call_tool(
                "create_contact", {"contact_data": json.dumps(contact_data)}
            )

            # Verify response structure
            assert result is not None
            # FastMCP client returns a list of TextContent objects
            if isinstance(result, list) and len(result) > 0:
                result_text = result[0].text
            else:
                result_text = result
            response_data = json.loads(result_text)

            # Check that we have the expected fields
            assert "id" in response_data
            assert "name" in response_data
            assert "email" in response_data
            assert "summary" in response_data

            # Verify the data
            assert response_data["name"] == "John Doe"
            assert response_data["email"] == "john.doe@example.com"
            assert "Successfully created contact" in response_data["summary"]

            # Verify the contact was actually created in the database
            contact_id = int(response_data["id"])
            assert contact_id > 0

            # Verify we can retrieve the contact using the regular service
            # Note: The MCP tool uses its own database connection, so we need to use a fresh connection
            from app.infrastructure.database import get_async_database_engine
            from app.shared.dependencies import create_contact_service

            engine = get_async_database_engine()
            async with engine.begin() as connection:
                contact_service = create_contact_service(connection)
                saved_contact = await contact_service.get_contact_by_id(contact_id)

            assert saved_contact is not None
            assert saved_contact.first_name == "John"
            assert saved_contact.last_name == "Doe"
            assert saved_contact.get_primary_email() == "john.doe@example.com"

    @pytest.mark.asyncio
    async def test_create_contact_integration_with_phone_and_notes(
        self, clean_database
    ):
        """Test create_contact tool with phone and notes using real database."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Test data with phone and notes
        contact_data = {
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane.smith@example.com",
            "phone": "+1234567890",
            "notes": "Met at conference",
        }

        # Use FastMCP Client for integration testing
        async with Client(mcp) as client:
            # Call the create_contact tool
            result = await client.call_tool(
                "create_contact", {"contact_data": json.dumps(contact_data)}
            )

            # Verify response structure
            assert result is not None
            # FastMCP client returns a list of TextContent objects
            if isinstance(result, list) and len(result) > 0:
                result_text = result[0].text
            else:
                result_text = result
            response_data = json.loads(result_text)

            # Check that we have the expected fields
            assert "id" in response_data
            assert "name" in response_data
            assert "email" in response_data
            assert "phone" in response_data
            assert "summary" in response_data

            # Verify the data
            assert response_data["name"] == "Jane Smith"
            assert response_data["email"] == "jane.smith@example.com"
            assert response_data["phone"] == "+1234567890"
            assert "Successfully created contact" in response_data["summary"]

            # Verify the contact was actually created in the database with all data
            contact_id = int(response_data["id"])
            from app.infrastructure.database import get_async_database_engine
            from app.shared.dependencies import create_contact_service

            engine = get_async_database_engine()
            async with engine.begin() as connection:
                contact_service = create_contact_service(connection)
                saved_contact = await contact_service.get_contact_by_id(contact_id)

            assert saved_contact is not None
            assert saved_contact.first_name == "Jane"
            assert saved_contact.last_name == "Smith"
            assert saved_contact.get_primary_email() == "jane.smith@example.com"
            assert saved_contact.get_primary_phone() == "+1234567890"
            assert len(saved_contact.notes) > 0
            assert saved_contact.notes[0].content == "Met at conference"

    @pytest.mark.asyncio
    async def test_create_contact_integration_minimal(self, clean_database):
        """Test create_contact tool with minimal data using real database."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Test data with only required fields
        contact_data = {
            "first_name": "Bob",
        }

        # Use FastMCP Client for integration testing
        async with Client(mcp) as client:
            # Call the create_contact tool
            result = await client.call_tool(
                "create_contact", {"contact_data": json.dumps(contact_data)}
            )

            # Verify response structure
            assert result is not None
            # FastMCP client returns a list of TextContent objects
            if isinstance(result, list) and len(result) > 0:
                result_text = result[0].text
            else:
                result_text = result
            response_data = json.loads(result_text)

            # Check that we have the expected fields
            assert "id" in response_data
            assert "name" in response_data
            assert "summary" in response_data

            # Verify the data
            assert response_data["name"] == "Bob"
            assert response_data["email"] is None
            assert response_data["phone"] is None
            assert "Successfully created contact" in response_data["summary"]

            # Verify the contact was actually created in the database
            contact_id = int(response_data["id"])
            from app.infrastructure.database import get_async_database_engine
            from app.shared.dependencies import create_contact_service

            engine = get_async_database_engine()
            async with engine.begin() as connection:
                contact_service = create_contact_service(connection)
                saved_contact = await contact_service.get_contact_by_id(contact_id)

            assert saved_contact is not None
            assert saved_contact.first_name == "Bob"
            assert saved_contact.last_name is None
            assert len(saved_contact.methods) == 0  # No email or phone provided

    @pytest.mark.asyncio
    async def test_list_contacts_integration(self, sample_contact_entity):
        """Test list_contacts tool with real service integration."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock the contact service
        with patch(
            "app.mcp.domains.contacts.tools.get_contact_service"
        ) as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_contacts_paginated.return_value = [sample_contact_entity]
            mock_service.get_contacts_count.return_value = 1
            mock_get_service.return_value = mock_service

            # Use FastMCP Client for integration testing
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

                # Verify the contact data
                contact = response_data["contacts"][0]
                assert contact["id"] == "123"
                assert contact["name"] == "John William Doe"
                assert contact["email"] == "john@example.com"
                assert contact["phone"] == "+1234567890"
                assert "friend" in contact["tags"]
                assert "work" in contact["tags"]

                # Verify summary
                assert "Retrieved 1 contacts from page 1" in response_data["summary"]
                assert "Total contacts in system: 1" in response_data["summary"]

                # Verify service calls
                mock_service.get_contacts_paginated.assert_called_once_with(20, 0)
                mock_service.get_contacts_count.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_contacts_integration(self):
        """Test search_contacts tool with real search service integration."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Mock search results
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

        # Mock the search service
        with patch(
            "app.mcp.domains.contacts.tools.get_search_service"
        ) as mock_get_search_service:
            mock_search_service = Mock()
            mock_search_service.search_contacts.return_value = search_results
            mock_get_search_service.return_value = mock_search_service

            # Use FastMCP Client for integration testing
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

                # Verify the search result
                result_item = response_data["results"][0]
                assert result_item["id"] == "123"
                assert result_item["name"] == "John Doe"
                assert result_item["email"] == "john@example.com"
                assert result_item["phone"] == "+1234567890"
                assert result_item["tags"] == ["friend", "work"]
                assert "highlighted" in result_item

                # Verify available tags
                assert "friend" in response_data["available_tags"]
                assert "work" in response_data["available_tags"]

                # Verify summary
                assert "Found 1 contacts matching 'john'" in response_data["summary"]

                # Verify service call
                mock_search_service.search_contacts.assert_called_once_with(
                    query="john", filters=None, limit=20, offset=0
                )

    @pytest.mark.asyncio
    async def test_mcp_server_tool_registration_integration(self):
        """Test that all contact tools are properly registered with the MCP server."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Use FastMCP Client to test tool registration
        async with Client(mcp) as client:
            # Get list of available tools
            tools = await client.list_tools()

            # Verify all expected tools are registered
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
                    f"Tool {expected_tool} not registered"
                )

            # Verify tool descriptions are present
            for tool in tools:
                assert tool.description is not None
                assert len(tool.description) > 0
                assert tool.inputSchema is not None

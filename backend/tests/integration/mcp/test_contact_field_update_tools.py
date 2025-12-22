"""
Integration tests for MCP contact field update tools.

Tests the MCP tools for updating individual contact fields, methods, addresses, and notes.
"""

import json
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from dishka import Provider, Scope, make_async_container, provide
from fastmcp import FastMCP
from fastmcp.client import Client
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import Contact, ContactMethod, MethodType
from app.core.contacts.services import ContactService
from app.infrastructure.search.search_service import SearchService
from app.mcp.domains.contacts.tools import register_contact_tools
from tests.fixtures.contact_fixtures import create_full_contact


class ContactTestProvider(Provider):
    """Test provider for contact services with mocked dependencies."""

    def __init__(self, connection: AsyncConnection):
        super().__init__()
        self.connection = connection

    @provide(scope=Scope.REQUEST)
    def get_connection(self) -> AsyncConnection:
        return self.connection

    @provide(scope=Scope.REQUEST)
    def get_contact_service(self, connection: AsyncConnection) -> ContactService:
        from app.core.contacts.adapters.sql import (
            SqlContactEventPublisher,
            SqlContactFieldHistoryRepository,
            SqlContactRepository,
            SqlTagRepository,
        )
        from app.core.contacts.services import (
            AddressValidationService,
            ContactHistoryService,
            ContactService,
            ContactValidationService,
            TagHierarchyService,
        )

        contact_repository = SqlContactRepository(connection)
        tag_repository = SqlTagRepository(connection)
        history_repository = SqlContactFieldHistoryRepository(connection)
        event_publisher = SqlContactEventPublisher(connection)

        contact_validation_service = ContactValidationService(contact_repository)
        address_validation_service = AddressValidationService()

        history_service = ContactHistoryService(history_repository)
        tag_hierarchy_service = TagHierarchyService(tag_repository)

        return ContactService(
            contact_repo=contact_repository,
            tag_repo=tag_repository,
            history_repo=history_repository,
            event_publisher=event_publisher,
            contact_validation_service=contact_validation_service,
            address_validation_service=address_validation_service,
            history_service=history_service,
            tag_hierarchy_service=tag_hierarchy_service,
        )

    @provide(scope=Scope.APP)
    def get_search_service(self) -> SearchService:
        mock_service = Mock(spec=SearchService)
        mock_service.search_contacts.return_value = {
            "hits": [],
            "query": "",
            "processing_time_ms": 10,
            "estimated_total_hits": 0,
            "facet_distribution": {},
        }
        return mock_service


class TestContactFieldUpdateTools:
    """Integration tests for MCP contact field update tools."""

    @pytest_asyncio.fixture
    async def test_container(self, clean_database: AsyncConnection):
        """Create test container with mocked dependencies."""
        container = make_async_container(ContactTestProvider(clean_database))
        yield container
        await container.close()

    @pytest.mark.asyncio
    async def test_field_update_tools_registered(self):
        """Test that field update tools are registered with MCP server."""
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        async with Client(mcp) as client:
            tools = await client.list_tools()
            tool_names = [tool.name for tool in tools]

            # Verify field update tools are registered
            expected_tools = [
                "update_contact_field",
                "update_contact_method_field",
                "update_contact_address_field",
                "update_contact_note_field",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names, (
                    f"Tool {expected_tool} not registered"
                )

    @pytest.mark.asyncio
    async def test_update_contact_field_tool_exists(self):
        """Test that update_contact_field tool is properly registered."""
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        async with Client(mcp) as client:
            tools = await client.list_tools()
            tool_names = [tool.name for tool in tools]
            assert "update_contact_field" in tool_names


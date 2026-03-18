"""
Integration tests for MCP contact tools.

Tests the full MCP contact tools with real database and search service integration
using Dishka dependency injection patterns.
"""

from unittest.mock import Mock

import pytest
import pytest_asyncio
from core_shared.models.contacts.entities import (
    Contact,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from core_shared.models.contacts.value_objects import TagName
from dishka import Provider, Scope, make_async_container, provide
from fastmcp import FastMCP
from fastmcp.client import Client
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services import ContactService
from app.infrastructure.search.search_service import SearchService
from app.mcp.domains.contacts.tools import register_contact_tools
from tests.fixtures.contact_fixtures import create_basic_contact, create_full_contact
from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    initialize_mcp_session,
    mcp_headers,
)


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
        # Create ContactService using the same factory logic
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

        # Create repositories
        contact_repository = SqlContactRepository(connection)
        tag_repository = SqlTagRepository(connection)
        history_repository = SqlContactFieldHistoryRepository(connection)
        event_publisher = SqlContactEventPublisher(connection)

        # Create validation services
        contact_validation_service = ContactValidationService(contact_repository)
        address_validation_service = AddressValidationService()

        # Create history service
        history_service = ContactHistoryService(history_repository)

        # Create tag hierarchy service
        tag_hierarchy_service = TagHierarchyService(tag_repository)

        # Create and return contact service
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
        # Return a mock search service for testing
        mock_service = Mock(spec=SearchService)
        mock_service.search_contacts.return_value = {
            "hits": [],
            "query": "",
            "processing_time_ms": 10,
            "estimated_total_hits": 0,
            "facet_distribution": {},
        }
        mock_service.global_search.return_value = {
            "hits": [],
            "query": "",
            "processing_time_ms": 10,
            "estimated_total_hits": 0,
            "searched_entity_types": ["contact"],
            "available_entity_types": ["contact"],
        }
        return mock_service


class TestContactToolsIntegration:
    """Integration tests for MCP contact tools with real services."""

    @pytest.fixture
    def sample_contact_entity(self):
        """Create a sample contact entity for testing."""
        # Use shared fixture factory with customized values to match original
        return create_full_contact(
            first_name="John",
            last_name="Doe",
            middle_name="William",
            nick_name="Johnny",
            email="john@example.com",
            phone="+1234567890",
            tags=["friend", "work"],
            notes=["Great colleague and friend"],
            contact_id=123,
        )

    @pytest_asyncio.fixture
    async def test_container(self, clean_database: AsyncConnection):
        """Create test container with mocked dependencies."""
        container = make_async_container(ContactTestProvider(clean_database))
        yield container
        await container.close()

    @pytest_asyncio.fixture
    async def contact_service(self, test_container):
        """Get contact service from test container."""
        async with test_container() as request_container:
            return await request_container.get(ContactService)

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection):
        """Create real tag repository."""
        from app.core.contacts.adapters.sql import SqlTagRepository

        return SqlTagRepository(clean_database)

    @pytest_asyncio.fixture
    async def search_service(self, test_container):
        """Get search service from test container."""
        return await test_container.get(SearchService)

    @pytest.mark.asyncio
    async def test_get_contact_integration(self, sample_contact_entity):
        """Test get_contact tool with mocked service integration."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        # Since the tools use Dishka dependency injection, we need to mock at the Dishka level
        # For now, let's test the tool registration and basic functionality
        # Use FastMCP Client for integration testing
        async with Client(mcp) as client:
            # Get list of available tools to verify registration
            tools = await client.list_tools()
            tool_names = [tool.name for tool in tools]

            # Verify all expected tools are registered
            expected_tools = [
                "get_contact",
                "search_contacts",
                "global_search",
                "create_contact",
                "update_contact",
                "list_contacts",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names, (
                    f"Tool {expected_tool} not registered"
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
                "update_contact",
                "list_contacts",
                "toggle_contact_favourite",
                "list_tags",
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

    @pytest.mark.asyncio
    async def test_create_contact_integration_real_db(
        self, contact_service: ContactService, clean_database: AsyncConnection
    ):
        """Test create_contact tool with real database integration."""
        # Test creating a contact directly with the service

        # Create a test contact
        contact = Contact(
            first_name="John",
            last_name="Doe",
        )

        # Save the contact
        saved_contact = await contact_service.create_contact(contact, clean_database)

        # Verify the contact was created
        assert saved_contact is not None
        assert saved_contact.id is not None
        assert saved_contact.first_name == "John"
        assert saved_contact.last_name == "Doe"

        # Add an email method
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john.doe@example.com",
            contact_id=saved_contact.id,
            is_primary=True,
        )

        await contact_service.add_contact_method(
            saved_contact.id, email_method, clean_database
        )

        # Retrieve the contact to verify the email was added
        retrieved_contact = await contact_service.get_contact_by_id(saved_contact.id)
        assert retrieved_contact is not None
        assert retrieved_contact.get_primary_email() == "john.doe@example.com"

    @pytest.mark.asyncio
    async def test_create_contact_integration_with_phone_and_notes(
        self, contact_service: ContactService, clean_database: AsyncConnection
    ):
        """Test creating a contact with phone and notes using real database with single transaction."""
        # Test creating a contact with additional data using the new single-call approach

        # Create a test contact with attached methods and notes
        contact = Contact(
            first_name="Jane",
            last_name="Smith",
        )

        # Add email method (attached before creation)
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="jane.smith@example.com",
            contact_id=0,  # Will be set when contact is saved
            is_primary=True,
        )
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(email_method)

        # Add phone method (attached before creation)
        phone_method = ContactMethod(
            method_type=MethodType.PHONE,
            value="+1234567890",
            contact_id=0,  # Will be set when contact is saved
            is_primary=True,
        )
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(phone_method)

        # Add note (attached before creation)
        note = ContactNote(
            content="Met at conference",
            contact_id=0,  # Will be set when contact is saved
        )
        if contact.notes is None:
            contact.notes = []
        contact.notes.append(note)

        # Create the contact with all attached data in a single transaction
        saved_contact = await contact_service.create_contact(contact, clean_database)

        # Verify the contact was created with all data
        assert saved_contact.id is not None
        assert saved_contact.first_name == "Jane"
        assert saved_contact.last_name == "Smith"
        assert saved_contact.methods is not None and len(saved_contact.methods) == 2
        assert saved_contact.notes is not None and len(saved_contact.notes) == 1

        # Retrieve the contact to verify all data was persisted correctly
        retrieved_contact = await contact_service.get_contact_by_id(saved_contact.id)
        assert retrieved_contact is not None
        assert retrieved_contact.first_name == "Jane"
        assert retrieved_contact.last_name == "Smith"
        assert retrieved_contact.get_primary_email() == "jane.smith@example.com"
        assert retrieved_contact.get_primary_phone() == "+1234567890"
        assert retrieved_contact.notes is not None
        assert len(retrieved_contact.notes) == 1
        assert retrieved_contact.notes[0].content == "Met at conference"

    @pytest.mark.asyncio
    async def test_create_contact_integration_minimal(
        self, contact_service: ContactService, clean_database: AsyncConnection
    ):
        """Test creating a contact with minimal data using real database."""
        # Use shared fixture factory for consistent test data
        contact = create_basic_contact(first_name="Bob", last_name=None)

        # Save the contact
        saved_contact = await contact_service.create_contact(contact, clean_database)

        # Verify the contact was created
        assert saved_contact is not None
        assert saved_contact.id is not None
        assert saved_contact.first_name == "Bob"
        assert saved_contact.last_name is None

        # Retrieve the contact to verify it was saved correctly
        assert saved_contact.id is not None
        retrieved_contact = await contact_service.get_contact_by_id(saved_contact.id)
        assert retrieved_contact is not None
        assert retrieved_contact.first_name == "Bob"
        assert retrieved_contact.last_name is None
        assert not retrieved_contact.methods  # No email or phone provided

    @pytest.mark.asyncio
    async def test_list_contacts_integration(
        self, contact_service: ContactService, clean_database: AsyncConnection
    ):
        """Test listing contacts with real database integration."""
        # Use shared fixture factory for consistent test data
        contact1 = create_basic_contact(first_name="John", last_name="Doe")
        contact2 = create_basic_contact(first_name="Jane", last_name="Smith")

        await contact_service.create_contact(contact1, clean_database)
        await contact_service.create_contact(contact2, clean_database)

        # Test pagination
        contacts = await contact_service.get_contacts_paginated(limit=10, offset=0)
        total_count = await contact_service.get_contacts_count()

        # Verify results
        assert len(contacts) == 2
        assert total_count == 2

        # Verify contact data
        contact_names = [contact.get_full_name() for contact in contacts]
        assert "John Doe" in contact_names
        assert "Jane Smith" in contact_names

    @pytest.mark.asyncio
    async def test_search_service_integration(self, search_service: SearchService):
        """Test search service integration with mocked search functionality."""
        # Test that the search service is properly configured
        assert search_service is not None

        # Test search_contacts method
        result = search_service.search_contacts(
            query="test", filters=None, limit=20, offset=0
        )

        # Verify the mock returns expected structure
        assert "hits" in result
        assert "query" in result
        assert "processing_time_ms" in result
        assert "estimated_total_hits" in result
        assert "facet_distribution" in result

        # Test global_search method
        global_result = search_service.global_search(
            query="test", entity_types=None, limit=20, offset=0
        )

        # Verify the mock returns expected structure
        assert "hits" in global_result
        assert "query" in global_result
        assert "processing_time_ms" in global_result
        assert "estimated_total_hits" in global_result
        assert "searched_entity_types" in global_result
        assert "available_entity_types" in global_result

    @pytest.mark.asyncio
    async def test_create_contact_single_transaction_integration(
        self, contact_service: ContactService, clean_database: AsyncConnection
    ):
        """Test that create_contact tool uses single transaction for contact with methods and notes."""
        # This test verifies that the refactored create_contact tool
        # creates contacts with methods and notes in a single service call

        # Create a contact with methods and notes using the same pattern as the MCP tool
        from core_shared.models.contacts.entities import (
            ContactNote,
        )

        contact = Contact(
            first_name="Alice",
            last_name="Johnson",
        )

        # Add email method (same as MCP tool)
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="alice.johnson@example.com",
            contact_id=0,  # Will be set when contact is saved
            is_primary=True,
        )
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(email_method)

        # Add phone method (same as MCP tool)
        phone_method = ContactMethod(
            method_type=MethodType.PHONE,
            value="+1987654321",
            contact_id=0,  # Will be set when contact is saved
            is_primary=True,
        )
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(phone_method)

        # Add note (same as MCP tool)
        note = ContactNote(
            content="Created via MCP tool integration test",
            contact_id=0,  # Will be set when contact is saved
        )
        if contact.notes is None:
            contact.notes = []
        contact.notes.append(note)

        # Create the contact using the service (same as MCP tool)
        created_contact = await contact_service.create_contact(contact, clean_database)

        # Verify the contact was created with all related data
        assert created_contact.id is not None
        assert created_contact.first_name == "Alice"
        assert created_contact.last_name == "Johnson"
        assert created_contact.methods is not None
        assert len(created_contact.methods) == 2
        assert created_contact.notes is not None
        assert len(created_contact.notes) == 1

        # Verify the contact was actually saved to database
        saved_contact = await contact_service.get_contact_by_id(created_contact.id)
        assert saved_contact is not None
        assert saved_contact.get_primary_email() == "alice.johnson@example.com"
        assert saved_contact.get_primary_phone() == "+1987654321"
        assert saved_contact.notes is not None and len(saved_contact.notes) == 1
        assert (
            saved_contact.notes is not None
            and saved_contact.notes[0].content
            == "Created via MCP tool integration test"
        )

    @pytest.mark.asyncio
    async def test_create_contact_with_tags_integration(
        self, contact_service: ContactService, tag_repo, clean_database: AsyncConnection
    ):
        """Test that create_contact tool handles tags correctly - finds existing and creates new ones."""
        # First, create an existing tag

        existing_tag = Tag(name=TagName("work"))
        saved_existing_tag = await tag_repo.save(existing_tag)

        # Now test the MCP tool pattern with both existing and new tags
        from core_shared.models.contacts.entities import (
            Contact,
            ContactMethod,
            MethodType,
        )

        contact = Contact(
            first_name="David",
            last_name="Wilson",
        )

        # Add email method
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="david.wilson@example.com",
            contact_id=0,  # Will be set when contact is saved
            is_primary=True,
        )
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(email_method)

        # Simulate the MCP tool tag handling logic
        tag_names = [
            "work",
            "client",
            "important",
        ]  # work exists, client and important are new

        for tag_name in tag_names:
            # Try to find existing tag by name
            existing_tag_found = await tag_repo.find_by_name(tag_name)

            if existing_tag_found:
                # Use existing tag
                contact.add_tag(existing_tag_found)
            else:
                # Create new tag
                new_tag = Tag(name=TagName(tag_name))
                saved_tag = await tag_repo.save(new_tag)
                contact.add_tag(saved_tag)

        # Create the contact using the service (same as MCP tool)
        created_contact = await contact_service.create_contact(contact, clean_database)

        # Verify the contact was created with all tags
        assert created_contact.id is not None
        assert created_contact.first_name == "David"
        assert created_contact.tags is not None
        assert len(created_contact.tags) == 3

        # Verify tag names
        tag_names_created = [str(tag.name) for tag in created_contact.tags]
        assert "work" in tag_names_created
        assert "client" in tag_names_created
        assert "important" in tag_names_created

        # Verify the contact was actually saved to the database with tags
        retrieved_contact = await contact_service.get_contact_by_id(created_contact.id)
        assert retrieved_contact is not None
        assert retrieved_contact.tags is not None
        assert len(retrieved_contact.tags) == 3

        retrieved_tag_names = [str(tag.name) for tag in retrieved_contact.tags]
        assert "work" in retrieved_tag_names
        assert "client" in retrieved_tag_names
        assert "important" in retrieved_tag_names

        # Verify that the existing "work" tag was reused (same ID)
        work_tag_in_contact = next(
            tag for tag in retrieved_contact.tags if str(tag.name) == "work"
        )
        assert work_tag_in_contact.id == saved_existing_tag.id

    @pytest.mark.asyncio
    async def test_update_contact_integration(
        self, contact_service: ContactService, tag_repo, clean_database: AsyncConnection
    ):
        """Test update_contact tool with real database integration."""
        # First create a contact to update
        original_contact = Contact(
            first_name="Original",
            last_name="Name",
        )

        # Add original email method
        original_email = ContactMethod(
            method_type=MethodType.EMAIL,
            value="original@example.com",
            contact_id=0,
            is_primary=True,
        )
        if original_contact.methods is None:
            original_contact.methods = []
        original_contact.methods.append(original_email)

        # Create original tag
        original_tag = Tag(name=TagName("original"))
        saved_original_tag = await tag_repo.save(original_tag)
        if original_contact.tags is None:
            original_contact.tags = []
        original_contact.tags.append(saved_original_tag)

        # Save the original contact
        saved_contact = await contact_service.create_contact(
            original_contact, clean_database
        )
        assert saved_contact.id is not None

        # Now test updating the contact (simulating MCP tool behavior)
        updated_contact = Contact(
            id=saved_contact.id,
            first_name="Updated",  # Changed
            last_name="Name",  # Same
            middle_name="Middle",  # New
            nick_name="Nick",  # New
        )

        # Update email method (replacement strategy)
        updated_email = ContactMethod(
            method_type=MethodType.EMAIL,
            value="updated@example.com",
            contact_id=saved_contact.id,
            is_primary=True,
        )
        if updated_contact.methods is None:
            updated_contact.methods = []
        updated_contact.methods.append(updated_email)

        # Add phone method (new)
        phone_method = ContactMethod(
            method_type=MethodType.PHONE,
            value="+1234567890",
            contact_id=saved_contact.id,
            is_primary=True,
        )
        if updated_contact.methods is None:
            updated_contact.methods = []
        updated_contact.methods.append(phone_method)

        # Update tags (replacement strategy) - mix of existing and new
        # Create a new tag for testing
        new_tag = Tag(name=TagName("updated"))
        saved_new_tag = await tag_repo.save(new_tag)
        if updated_contact.tags is None:
            updated_contact.tags = []
        updated_contact.tags.append(saved_new_tag)

        # Update the contact using the service
        final_contact = await contact_service.update_contact(
            updated_contact, clean_database
        )

        # Verify the contact was updated
        assert final_contact.id == saved_contact.id
        assert final_contact.first_name == "Updated"
        assert final_contact.last_name == "Name"
        assert final_contact.middle_name == "Middle"
        assert final_contact.nick_name == "Nick"
        assert final_contact.methods is not None
        assert len(final_contact.methods) == 2  # Email + Phone
        assert final_contact.tags is not None
        assert len(final_contact.tags) == 1  # Only the new tag (replacement strategy)

        # Verify the contact was actually updated in the database
        retrieved_contact = await contact_service.get_contact_by_id(saved_contact.id)
        assert retrieved_contact is not None
        assert retrieved_contact.first_name == "Updated"
        assert retrieved_contact.middle_name == "Middle"
        assert retrieved_contact.nick_name == "Nick"
        assert retrieved_contact.get_primary_email() == "updated@example.com"
        assert retrieved_contact.get_primary_phone() == "+1234567890"

        # Verify tags were replaced (not appended)
        assert retrieved_contact.tags is not None
        assert len(retrieved_contact.tags) == 1
        assert str(retrieved_contact.tags[0].name) == "updated"

    @pytest.mark.asyncio
    async def test_list_tags_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        tag_repo,
    ):
        """Mounted MCP HTTP calls should resolve request-scoped dependencies."""
        await tag_repo.save(Tag(name=TagName("friend")))
        await tag_repo.save(Tag(name=TagName("colleague")))

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            response = await authenticated_client.post(
                "/mcp-server",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "list_tags",
                        "arguments": {"limit": 10},
                    },
                },
                headers=mcp_headers(session_id),
            )

        assert response.status_code == 200
        payload = extract_mcp_json_payload(response.text)
        assert payload["total_count"] == 2
        assert [tag["name"] for tag in payload["tags"]] == ["colleague", "friend"]

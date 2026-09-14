"""
Integration tests for MCP contact tools.

Tests the full MCP contact tools with real database and search service integration
using Dishka dependency injection patterns.
"""

from datetime import UTC, date, datetime, timedelta
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services import ContactRelationshipService, ContactService
from app.infrastructure.search.search_service import SearchService
from app.mcp.domains.contacts.tools import register_contact_tools
from tests.fixtures.contact_fixtures import create_basic_contact, create_full_contact
from tests.integration.mcp.http_helpers import (
    call_mcp_tool_sessionless,
    post_mcp_tool,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)


async def _update_contact_tag(authenticated_lifespan_client, arguments):
    """Call ``update_contact_tag`` and return the raw HTTP response.

    The tag tests inspect the response itself (a refusal's text) or only the
    stored tag afterwards, so this stops short of extracting a payload.
    """
    async with authenticated_lifespan_client() as authenticated_client:
        return await post_mcp_tool(
            authenticated_client, "update_contact_tag", arguments, request_id=2
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

    @provide(scope=Scope.REQUEST)
    def get_contact_relationship_service(
        self, connection: AsyncConnection
    ) -> ContactRelationshipService:
        from app.core.contacts.adapters.sql import (
            SqlContactEventPublisher,
            SqlContactRelationshipRepository,
            SqlContactRepository,
        )
        from app.core.contacts.services import ContactRelationshipService

        return ContactRelationshipService(
            contact_repo=SqlContactRepository(connection),
            relationship_repo=SqlContactRelationshipRepository(connection),
            event_publisher=SqlContactEventPublisher(connection),
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
                "get_contact_by_external_id",
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
                "list_contact_tags",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names, (
                    f"Tool {expected_tool} not registered"
                )

            # Verify tool descriptions are present
            for tool in tools:
                assert tool.description is not None
                assert len(tool.description) > 0
                assert tool.input_schema is not None

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
    async def test_list_contact_tags_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        tag_repo,
    ):
        """Mounted MCP HTTP calls should resolve request-scoped dependencies."""
        await tag_repo.save(Tag(name=TagName("friend")))
        await tag_repo.save(Tag(name=TagName("colleague")))

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client, "list_contact_tags", {"limit": 10}, request_id=2
            )

        assert payload["total_count"] == 2
        assert [tag["name"] for tag in payload["tags"]] == ["colleague", "friend"]

    @pytest.mark.asyncio
    async def test_list_contact_tags_stringifies_ids_and_parent_ids(
        self,
        authenticated_lifespan_client,
        tag_repo,
    ):
        """Both id and parent_id are strings so they round-trip into write tools.

        parent_id was previously emitted as a raw int while id was stringified,
        leaving the same tool internally inconsistent (issue #1139).
        """
        parent = await tag_repo.save(Tag(name=TagName("work")))
        child = await tag_repo.save(Tag(name=TagName("colleague"), parent_id=parent.id))

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client, "list_contact_tags", {"limit": 10}, request_id=2
            )

        tags_by_name = {tag["name"]: tag for tag in payload["tags"]}

        assert tags_by_name["colleague"]["id"] == str(child.id)
        # parent_id is a string, matching id, so a caller can feed it straight
        # back into update_contact_tag as the parent.
        assert tags_by_name["colleague"]["parent_id"] == str(parent.id)
        # A root tag reports a null parent, not the string "None".
        assert tags_by_name["work"]["parent_id"] is None

    @pytest.mark.asyncio
    async def test_update_contact_tag_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        tag_repo,
    ):
        """The update_contact_tag tool updates a tag and commits the write."""
        tag = await tag_repo.save(Tag(name=TagName("friend"), color="#00FF00"))

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "update_contact_tag",
                {
                    "tag_id": str(tag.id),
                    "name": "close-friend",
                    "color": "#123456",
                    "description": "People I see often",
                },
                request_id=2,
            )

        # The id round-trips as the string the caller passed in (issue #1139).
        assert payload["id"] == str(tag.id)
        assert payload["name"] == "close-friend"
        assert payload["color"] == "#123456"
        assert payload["description"] == "People I see often"

        persisted = await tag_repo.find_by_id(tag.id)
        assert persisted is not None
        assert str(persisted.name) == "close-friend"

    @pytest.mark.asyncio
    async def test_update_contact_tag_unknown_tag_reports_not_found(
        self,
        authenticated_lifespan_client,
        clean_database,
    ):
        """An unknown tag id is reported as not-found, not a generic failure.

        Callers need to distinguish a missing tag from a server error, so the
        error handler must recognise TagNotFoundError rather than letting it
        fall through to the catch-all.
        """
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "update_contact_tag",
                {"tag_id": "999999", "name": "ghost"},
                request_id=2,
            )

        assert "not found" in payload["error"].lower()
        # The id must be reported as the id, so a client can surface or retry
        # with it rather than parsing it back out of a message.
        assert payload["tag_id"] == 999999

    @pytest.mark.asyncio
    async def test_update_contact_tag_non_numeric_id_is_a_validation_error(
        self,
        authenticated_lifespan_client,
        clean_database,
    ):
        """A non-numeric tag id is rejected as bad input, not a server error.

        Contact tag ids are strings on the wire but int-keyed underneath, so the
        tool converts at the edge and must report an unparseable id clearly
        rather than letting the int() cast surface as a generic failure.
        """
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "update_contact_tag",
                {"tag_id": "not-a-number", "name": "ghost"},
                request_id=2,
            )

        assert payload["error"] == "Validation error"
        # The offending field is named so the caller knows what to fix.
        assert payload["field"] == "tag_id"

    @pytest.mark.asyncio
    async def test_update_contact_tag_reparent_and_move_to_root(
        self,
        authenticated_lifespan_client,
        tag_repo,
    ):
        """The tool can re-parent a tag and then move it back to the root."""
        parent = await tag_repo.save(Tag(name=TagName("work")))
        child = await tag_repo.save(Tag(name=TagName("colleague")))

        await _update_contact_tag(
            authenticated_lifespan_client,
            {"tag_id": str(child.id), "parent_id": str(parent.id)},
        )
        reparented = await tag_repo.find_by_id(child.id)
        assert reparented is not None
        assert reparented.parent_id == parent.id

        await _update_contact_tag(
            authenticated_lifespan_client,
            {"tag_id": str(child.id), "move_to_root": True},
        )
        cleared = await tag_repo.find_by_id(child.id)
        assert cleared is not None
        assert cleared.parent_id is None

    @pytest.mark.asyncio
    async def test_update_contact_tag_explicit_parent_wins_over_move_to_root(
        self,
        authenticated_lifespan_client,
        tag_repo,
    ):
        """Supplying the current parent alongside move_to_root keeps the parent.

        A flat parent/clear precedence would treat the unchanged parent_id as
        "no parent supplied" and clear it instead.
        """
        parent = await tag_repo.save(Tag(name=TagName("work")))
        child = await tag_repo.save(Tag(name=TagName("colleague"), parent_id=parent.id))

        response = await _update_contact_tag(
            authenticated_lifespan_client,
            {
                "tag_id": str(child.id),
                "parent_id": str(parent.id),
                "move_to_root": True,
            },
        )

        assert response.status_code == 200
        persisted = await tag_repo.find_by_id(child.id)
        assert persisted is not None
        assert persisted.parent_id == parent.id

    @pytest.mark.asyncio
    async def test_update_contact_tag_duplicate_name_errors(
        self,
        authenticated_lifespan_client,
        tag_repo,
    ):
        """A name held by another tag is rejected and nothing is written."""
        await tag_repo.save(Tag(name=TagName("friend")))
        other = await tag_repo.save(Tag(name=TagName("colleague")))

        response = await _update_contact_tag(
            authenticated_lifespan_client,
            {"tag_id": str(other.id), "name": "friend"},
        )

        assert response.status_code == 200
        assert "already exists" in response.text.lower()

        persisted = await tag_repo.find_by_id(other.id)
        assert persisted is not None
        assert str(persisted.name) == "colleague"

    @pytest.mark.asyncio
    async def test_delete_contact_tag_removes_it_from_contacts(
        self,
        authenticated_lifespan_client,
        tag_repo,
        contact_service: ContactService,
        clean_database,
    ):
        """The delete_contact_tag tool deletes a tag that is still assigned."""
        from core_shared.models.contacts.entities import Contact
        from sqlalchemy import text

        contact = await contact_service.create_contact(
            Contact(first_name="Jane", last_name="Doe"), clean_database
        )
        tag = await tag_repo.save(Tag(name=TagName("friend")))
        await clean_database.execute(
            text(
                "INSERT INTO contact_tags (contact_id, tag_id) "
                "VALUES (:contact_id, :tag_id)"
            ),
            {"contact_id": contact.id, "tag_id": tag.id},
        )

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "delete_contact_tag",
                {"tag_id": str(tag.id)},
                request_id=2,
            )

        assert payload["status"] == "success"

        assert await tag_repo.find_by_id(tag.id) is None
        remaining = await clean_database.execute(
            text("SELECT COUNT(*) FROM contact_tags WHERE contact_id = :contact_id"),
            {"contact_id": contact.id},
        )
        assert remaining.scalar() == 0

    @pytest.mark.asyncio
    async def test_delete_contact_tag_unknown_tag_reports_not_found(
        self,
        authenticated_lifespan_client,
        clean_database,
    ):
        """An unknown tag id is reported as not-found, not a generic failure."""
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "delete_contact_tag",
                {"tag_id": "999999"},
                request_id=2,
            )

        assert "not found" in payload["error"].lower()
        assert payload["tag_id"] == 999999

    @pytest.mark.asyncio
    async def test_merge_contact_tags_moves_assignments_and_children(
        self,
        authenticated_lifespan_client,
        tag_repo,
        contact_service: ContactService,
        clean_database,
    ):
        """The renamed merge_contact_tags tool still performs the merge.

        Registered as ``merge_contact_tags`` (was the unscoped ``merge_tags``)
        so it sits symmetrically beside ``merge_journal_tag``.
        """
        from core_shared.models.contacts.entities import Contact
        from sqlalchemy import text

        contact = await contact_service.create_contact(
            Contact(first_name="Jane", last_name="Doe"), clean_database
        )
        source = await tag_repo.save(Tag(name=TagName("colleague")))
        target = await tag_repo.save(Tag(name=TagName("work")))
        child = await tag_repo.save(Tag(name=TagName("team"), parent_id=source.id))
        await clean_database.execute(
            text(
                "INSERT INTO contact_tags (contact_id, tag_id) "
                "VALUES (:contact_id, :tag_id)"
            ),
            {"contact_id": contact.id, "tag_id": source.id},
        )

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "merge_contact_tags",
                {
                    "source_id": str(source.id),
                    "target_id": str(target.id),
                },
                request_id=2,
            )

        assert payload["status"] == "success"

        assert await tag_repo.find_by_id(source.id) is None
        assigned = await clean_database.execute(
            text("SELECT tag_id FROM contact_tags WHERE contact_id = :contact_id"),
            {"contact_id": contact.id},
        )
        assert [row.tag_id for row in assigned.fetchall()] == [target.id]
        surviving_child = await tag_repo.find_by_id(child.id)
        assert surviving_child is not None
        assert surviving_child.parent_id == target.id

    @pytest.mark.asyncio
    async def test_merge_tags_old_tool_name_is_gone(
        self,
        authenticated_lifespan_client,
        clean_database,
    ):
        """The pre-rename tool name is no longer registered."""
        async with authenticated_lifespan_client() as authenticated_client:
            response = await authenticated_client.post(
                "/mcp-server/mcp",
                json=sessionless_mcp_request("tools/list", {}, request_id=2),
                headers=sessionless_mcp_headers("tools/list"),
            )

        assert response.status_code == 200
        assert '"merge_tags"' not in response.text
        assert "merge_contact_tags" in response.text

    @pytest.mark.asyncio
    async def test_contact_relationships_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        contact_service: ContactService,
        clean_database,
    ):
        """Mounted MCP HTTP calls should resolve and execute relationship tools correctly."""
        # Create two contacts first using the service
        from core_shared.models.contacts.entities import Contact

        c1 = await contact_service.create_contact(
            Contact(first_name="Jane", last_name="Doe"), clean_database
        )
        c2 = await contact_service.create_contact(
            Contact(first_name="John", last_name="Smith"), clean_database
        )

        async with authenticated_lifespan_client() as authenticated_client:
            import typing

            async def call_mcp(name: str, args: dict[str, typing.Any]):
                return await call_mcp_tool_sessionless(authenticated_client, name, args)

            # 1. Add relationship
            add_payload = await call_mcp(
                "add_contact_relationship",
                {
                    "request": {
                        "contact_id": c1.id,
                        "target_contact_id": c2.id,
                        "relationship_type": "parent",
                    }
                },
            )
            assert add_payload["relationship_type"] == "parent"
            assert add_payload["other_contact_id"] == c2.id

            # 2. Get relationships for c1
            get1_payload = await call_mcp(
                "get_contact_relationships", {"contact_id": c1.id}
            )
            assert get1_payload["total_count"] == 1
            assert get1_payload["relationships"][0]["relationship_type"] == "parent"

            # 3. Get relationships for c2 (should be inverted)
            get2_payload = await call_mcp(
                "get_contact_relationships", {"contact_id": c2.id}
            )
            assert get2_payload["total_count"] == 1
            assert get2_payload["relationships"][0]["relationship_type"] == "child"

            rel_id = get2_payload["relationships"][0]["id"]

            # 4. Update relationship
            update_payload = await call_mcp(
                "update_contact_relationship",
                {
                    "request": {
                        "contact_id": c2.id,
                        "relationship_id": rel_id,
                        "relationship_type": "friend",
                    }
                },
            )
            assert update_payload["relationship_type"] == "friend"

            # Verify update reflected in c1
            get1_after_update = await call_mcp(
                "get_contact_relationships", {"contact_id": c1.id}
            )
            assert (
                get1_after_update["relationships"][0]["relationship_type"] == "friend"
            )

            # 5. Remove relationship
            await call_mcp(
                "remove_contact_relationship",
                {"contact_id": c1.id, "relationship_id": rel_id},
            )

            get1_after_remove = await call_mcp(
                "get_contact_relationships", {"contact_id": c1.id}
            )
            assert get1_after_remove["total_count"] == 0

    @pytest.mark.asyncio
    async def test_merge_contacts_tool_registered_with_schema(self):
        """merge_contacts is registered with explicit survivor + source IDs."""
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_contact_tools(mcp)

        async with Client(mcp) as client:
            tools = await client.list_tools()
            merge_tool = next((t for t in tools if t.name == "merge_contacts"), None)
            assert merge_tool is not None, "merge_contacts tool not registered"
            assert merge_tool.description is not None
            assert "merge" in merge_tool.description.lower()
            properties = merge_tool.input_schema.get("properties", {})
            assert "survivor_contact_id" in properties
            assert "source_contact_id" in properties
            # ITER13-002: the optional per-field overrides mapping is advertised.
            assert "overrides" in properties

    @pytest.mark.asyncio
    async def test_merge_contacts_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        contact_service: ContactService,
        clean_database,
    ):
        """The merge_contacts tool consolidates and deletes the source contact."""
        from core_shared.models.contacts.entities import Contact

        survivor = await contact_service.create_contact(
            Contact(first_name="Jane", last_name="Survivor", middle_name=None),
            clean_database,
        )
        source = await contact_service.create_contact(
            Contact(first_name="Janet", last_name="Source", middle_name="Mariposa"),
            clean_database,
        )

        async with authenticated_lifespan_client() as authenticated_client:

            async def call_mcp(name, args):
                return await call_mcp_tool_sessionless(authenticated_client, name, args)

            # Happy path: survivor absorbs the source and is returned.
            merged = await call_mcp(
                "merge_contacts",
                {"survivor_contact_id": survivor.id, "source_contact_id": source.id},
            )
            assert merged["id"] == str(survivor.id)

            # The source contact is deleted — fetching it now errors.
            missing = await call_mcp("get_contact", {"contact_id": source.id})
            assert "error" in missing

            # Self-merge is rejected.
            self_merge = await call_mcp(
                "merge_contacts",
                {
                    "survivor_contact_id": survivor.id,
                    "source_contact_id": survivor.id,
                },
            )
            assert "error" in self_merge

            # A missing source is rejected.
            not_found = await call_mcp(
                "merge_contacts",
                {"survivor_contact_id": survivor.id, "source_contact_id": 999999},
            )
            assert "error" in not_found

    @pytest.mark.asyncio
    async def test_merge_contacts_applies_overrides_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        contact_service: ContactService,
        clean_database,
    ):
        """ITER13-002: merge_contacts applies per-field overrides via MCP."""
        from core_shared.models.contacts.entities import Contact

        survivor = await contact_service.create_contact(
            Contact(
                first_name="Jane",
                last_name="Survivor",
                company="SurvivorCo",
                job_title="Survivor Title",
            ),
            clean_database,
        )
        source = await contact_service.create_contact(
            Contact(
                first_name="Janet",
                last_name="Source",
                company="SourceCo",
                job_title="Source Title",
            ),
            clean_database,
        )

        async with authenticated_lifespan_client() as authenticated_client:

            async def call_mcp(name, args):
                return await call_mcp_tool_sessionless(authenticated_client, name, args)

            merged = await call_mcp(
                "merge_contacts",
                {
                    "survivor_contact_id": survivor.id,
                    "source_contact_id": source.id,
                    "overrides": {
                        "company": "SourceCo",  # take source value
                        "job_title": "Custom Title",  # custom value
                    },
                },
            )

            assert merged["id"] == str(survivor.id)
            # company override picks the source value; job_title takes a custom value.
            assert merged["company"] == "SourceCo"
            assert merged["job_title"] == "Custom Title"
            # first/last names had no override -> survivor wins by default
            # (the MCP response exposes the combined full name).
            assert merged["name"] == "Jane Survivor"

            # The source contact is deleted.
            missing = await call_mcp("get_contact", {"contact_id": source.id})
            assert "error" in missing


class TestMCPTagParity:
    """Integration tests verifying MCP update_contact tag parity with REST API.

    The MCP update_contact tool uses a replacement strategy for tags:
    providing a tag list replaces all existing tags. Tags referenced by name
    are found-or-created automatically. These tests formally verify that
    behaviour and its parity with the REST tag CRUD endpoints.
    """

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

    @pytest.mark.asyncio
    async def test_update_contact_replaces_tags_via_mcp(
        self,
        contact_service: ContactService,
        tag_repo,
        clean_database: AsyncConnection,
    ):
        """Verify that update_contact replaces all tags (not appends).

        When the MCP tool provides a new set of tags, existing tags
        on the contact should be fully replaced.
        """
        # Setup: create tags and contact with initial tags
        tag_a = await tag_repo.save(Tag(name=TagName("alpha")))
        tag_b = await tag_repo.save(Tag(name=TagName("bravo")))
        tag_c = await tag_repo.save(Tag(name=TagName("charlie")))

        contact = Contact(first_name="Replace", last_name="Test", tags=[tag_a, tag_b])
        saved = await contact_service.create_contact(contact, clean_database)
        assert saved.id is not None

        # Verify initial state
        retrieved = await contact_service.get_contact_by_id(saved.id)
        assert retrieved is not None
        assert retrieved.tags is not None
        assert len(retrieved.tags) == 2
        initial_names = sorted(str(t.name) for t in retrieved.tags)
        assert initial_names == ["alpha", "bravo"]

        # Act: update with replacement tags (bravo → charlie via replacement)
        updated_contact = Contact(
            id=saved.id,
            first_name="Replace",
            last_name="Test",
            tags=[tag_b, tag_c],
        )
        await contact_service.update_contact(updated_contact, clean_database)

        # Assert: tags fully replaced
        final = await contact_service.get_contact_by_id(saved.id)
        assert final is not None
        assert final.tags is not None
        assert len(final.tags) == 2
        final_names = sorted(str(t.name) for t in final.tags)
        assert final_names == ["bravo", "charlie"]

    @pytest.mark.asyncio
    async def test_update_contact_creates_missing_tags_via_mcp(
        self,
        contact_service: ContactService,
        tag_repo,
        clean_database: AsyncConnection,
    ):
        """Verify MCP find-or-create semantics for tags.

        When the MCP tool references tags by name that don't exist,
        they should be auto-created and assigned to the contact.
        """
        # Setup: create one existing tag
        existing_tag = await tag_repo.save(Tag(name=TagName("existing")))

        contact = Contact(
            first_name="AutoCreate", last_name="Tags", tags=[existing_tag]
        )
        saved = await contact_service.create_contact(contact, clean_database)
        assert saved.id is not None

        # Act: simulate MCP tool tag handling — mix existing + new
        tag_names = ["existing", "brand-new", "also-new"]
        resolved_tags = []
        for name in tag_names:
            found = await tag_repo.find_by_name(name)
            if found:
                resolved_tags.append(found)
            else:
                new_tag = Tag(name=TagName(name))
                saved_tag = await tag_repo.save(new_tag)
                resolved_tags.append(saved_tag)

        updated_contact = Contact(
            id=saved.id,
            first_name="AutoCreate",
            last_name="Tags",
            tags=resolved_tags,
        )
        await contact_service.update_contact(updated_contact, clean_database)

        # Assert: all three tags present
        final = await contact_service.get_contact_by_id(saved.id)
        assert final is not None
        assert final.tags is not None
        assert len(final.tags) == 3
        final_names = sorted(str(t.name) for t in final.tags)
        assert final_names == ["also-new", "brand-new", "existing"]

        # Assert: existing tag was reused (same ID)
        existing_in_final = next(t for t in final.tags if str(t.name) == "existing")
        assert existing_in_final.id == existing_tag.id

    @pytest.mark.asyncio
    async def test_update_contact_empty_tags_clears_all(
        self,
        contact_service: ContactService,
        tag_repo,
        clean_database: AsyncConnection,
    ):
        """Verify that providing an empty tag list clears all tags."""
        # Setup: contact with tags
        tag_x = await tag_repo.save(Tag(name=TagName("x-ray")))
        tag_y = await tag_repo.save(Tag(name=TagName("yankee")))

        contact = Contact(first_name="Clear", last_name="Tags", tags=[tag_x, tag_y])
        saved = await contact_service.create_contact(contact, clean_database)
        assert saved.id is not None

        # Verify initial state
        retrieved = await contact_service.get_contact_by_id(saved.id)
        assert retrieved is not None
        assert retrieved.tags is not None
        assert len(retrieved.tags) == 2

        # Act: update with empty tags list
        updated_contact = Contact(
            id=saved.id,
            first_name="Clear",
            last_name="Tags",
            tags=[],
        )
        await contact_service.update_contact(updated_contact, clean_database)

        # Assert: all tags removed
        final = await contact_service.get_contact_by_id(saved.id)
        assert final is not None
        assert final.tags is not None
        assert len(final.tags) == 0

    @pytest.mark.asyncio
    async def test_mcp_tag_update_parity_with_rest(
        self,
        contact_service: ContactService,
        tag_repo,
        clean_database: AsyncConnection,
    ):
        """Verify MCP and REST produce identical outcomes.

        Creates tags via REST-equivalent repo calls, then applies an MCP-style
        replacement update. The resulting state should match what would happen
        if the same tags were assigned via the REST tag API.
        """
        # Setup via REST-equivalent: create tags
        rest_tag_a = await tag_repo.save(Tag(name=TagName("rest-a")))
        rest_tag_b = await tag_repo.save(Tag(name=TagName("rest-b")))

        # Create contact with tag-a (simulating REST assignment)
        contact = Contact(
            first_name="Parity",
            last_name="Check",
            tags=[rest_tag_a],
        )
        saved = await contact_service.create_contact(contact, clean_database)
        assert saved.id is not None

        # MCP-style update: replace tags with [rest-b]
        # This mirrors what update_contact MCP tool does
        updated_contact = Contact(
            id=saved.id,
            first_name="Parity",
            last_name="Check",
            tags=[rest_tag_b],
        )
        await contact_service.update_contact(updated_contact, clean_database)

        # Verify: contact has only rest-b (same outcome as REST assignment)
        final = await contact_service.get_contact_by_id(saved.id)
        assert final is not None
        assert final.tags is not None
        assert len(final.tags) == 1
        assert str(final.tags[0].name) == "rest-b"
        assert final.tags[0].id == rest_tag_b.id


class TestContactConverterAISummaryIntegration:
    """Integration tests verifying ContactConverter populates AI summary fields from real DB data."""

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
            yield await request_container.get(ContactService)

    @pytest.mark.asyncio
    async def test_converter_includes_generated_summary(
        self, contact_service: ContactService, clean_database: AsyncConnection
    ):
        """Test that converter populates interaction_summary and follow_up_suggestions for a GENERATED summary."""
        from datetime import datetime

        from core_shared.models.contacts.entities import ContactSummary, SummaryStatus

        from app.core.contacts.adapters.sql import SqlContactSummaryRepository
        from app.mcp.shared.converters import ContactConverter

        # Create contact
        contact = create_basic_contact(first_name="Alice", last_name="Summary")
        saved = await contact_service.create_contact(contact, clean_database)
        assert saved.id is not None

        # Insert a GENERATED summary
        summary_repo = SqlContactSummaryRepository(clean_database)
        summary = ContactSummary(
            contact_id=saved.id,
            summary_text="Alice is a close colleague we meet weekly.",
            follow_up_suggestions=["Schedule coffee", "Send project update"],
            status=SummaryStatus.GENERATED,
            generated_at=datetime(2026, 4, 20, 10, 0, 0),
        )
        await summary_repo.upsert(summary)

        # Retrieve the contact with summary loaded
        retrieved = await contact_service.get_contact_by_id(saved.id)
        assert retrieved is not None
        assert retrieved.summary is not None

        # Convert to MCP response
        response = ContactConverter.to_contact_response(retrieved)

        # Verify AI summary fields
        assert (
            response.interaction_summary == "Alice is a close colleague we meet weekly."
        )
        assert response.follow_up_suggestions == [
            "Schedule coffee",
            "Send project update",
        ]
        assert "Alice is a close colleague we meet weekly." in response.summary

    @pytest.mark.asyncio
    async def test_converter_no_summary_has_empty_ai_fields(
        self, contact_service: ContactService, clean_database: AsyncConnection
    ):
        """Test that converter returns None/empty for contacts without a summary entity."""
        from app.mcp.shared.converters import ContactConverter

        # Create contact without summary
        contact = create_basic_contact(first_name="Bob", last_name="NoSummary")
        saved = await contact_service.create_contact(contact, clean_database)
        assert saved.id is not None

        retrieved = await contact_service.get_contact_by_id(saved.id)
        assert retrieved is not None

        response = ContactConverter.to_contact_response(retrieved)

        assert response.interaction_summary is None
        assert response.follow_up_suggestions == []

    @pytest.mark.asyncio
    async def test_converter_user_override_takes_precedence(
        self, contact_service: ContactService, clean_database: AsyncConnection
    ):
        """Test that user override text is used instead of AI-generated text."""
        from datetime import datetime

        from core_shared.models.contacts.entities import ContactSummary, SummaryStatus

        from app.core.contacts.adapters.sql import SqlContactSummaryRepository
        from app.mcp.shared.converters import ContactConverter

        # Create contact
        contact = create_basic_contact(first_name="Diana", last_name="Override")
        saved = await contact_service.create_contact(contact, clean_database)
        assert saved.id is not None

        # Insert summary with user override
        summary_repo = SqlContactSummaryRepository(clean_database)
        summary = ContactSummary(
            contact_id=saved.id,
            summary_text="AI generated text",
            user_override_text="My custom description of Diana",
            is_user_override=True,
            follow_up_suggestions=["Follow up soon"],
            status=SummaryStatus.GENERATED,
            generated_at=datetime(2026, 4, 15, 8, 0, 0),
        )
        await summary_repo.upsert(summary)

        retrieved = await contact_service.get_contact_by_id(saved.id)
        assert retrieved is not None

        response = ContactConverter.to_contact_response(retrieved)

        assert response.interaction_summary == "My custom description of Diana"
        assert response.follow_up_suggestions == ["Follow up soon"]
        assert "My custom description of Diana" in response.summary

    @pytest.mark.asyncio
    async def test_get_contact_with_external_links_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        contact_service: ContactService,
        clean_database: AsyncConnection,
    ):
        """Mounted MCP HTTP calls should return external_links for get_contact."""
        from core_shared.models.contacts.entities import Contact
        from sqlalchemy import text

        c1 = await contact_service.create_contact(
            Contact(first_name="Jane", last_name="Doe"), clean_database
        )
        assert c1.id is not None
        # Seed the canonical link in sync_metadata (the read path's source).
        await clean_database.execute(
            text(
                "INSERT INTO sync_metadata (internal_id, integration_source, "
                "external_id, last_synced_at, version_hash, sync_status, "
                "internal_entity_type, external_entity_type) "
                "VALUES (:internal_id, 'google', 'people/c123456789', now(), 'h', "
                "'success', 'contact', 'person')"
            ),
            {"internal_id": int(c1.id)},
        )

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client, "get_contact", {"contact_id": c1.id}
            )

            assert "external_links" in payload
            links = payload["external_links"]
            assert len(links) == 1
            assert links[0]["source"] == "google_contacts"
            assert links[0]["external_id"] == "people/c123456789"
            assert links[0]["url"] == "https://contacts.google.com/person/c123456789"

    @pytest.mark.asyncio
    async def test_get_contact_includes_immich_person_link_via_http_session(
        self,
        authenticated_lifespan_client,
        contact_service: ContactService,
        clean_database: AsyncConnection,
    ):
        """get_contact returns an Immich person link with a server-derived URL."""
        from core_shared.models.contacts.entities import Contact
        from sqlalchemy import text

        c1 = await contact_service.create_contact(
            Contact(first_name="Imo", last_name="Immich"), clean_database
        )
        assert c1.id is not None

        await clean_database.execute(
            text(
                "INSERT INTO user_immich_auth "
                "(user_id, server_url, encrypted_api_key) "
                "VALUES ('test-user-123', :server_url, :api_key)"
            ),
            {
                "server_url": "https://immich.example.com",
                "api_key": b"encrypted-placeholder",
            },
        )
        await clean_database.execute(
            text(
                "INSERT INTO sync_metadata (internal_id, integration_source, "
                "external_id, last_synced_at, version_hash, sync_status, "
                "internal_entity_type, external_entity_type) "
                "VALUES (:internal_id, 'immich', 'person-uuid-1', now(), 'h', "
                "'success', 'contact', 'person')"
            ),
            {"internal_id": int(c1.id)},
        )

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client, "get_contact", {"contact_id": c1.id}
            )

            links = payload["external_links"]
            assert len(links) == 1
            assert links[0]["source"] == "immich"
            assert links[0]["external_id"] == "person-uuid-1"
            assert links[0]["url"] == "https://immich.example.com/people/person-uuid-1"


@pytest.mark.integration
class TestContactHistoryOverMCPCountsTaskRecords:
    """MCP parity for the record a task leaves on a person's history.

    Contact history reaches agents only as a count inside
    ``get_contact(include_history=True)`` — there is no contact-history tool, and
    ITER18-003 Phase 9 does not add one (a contacts-domain capability, not this
    phase's). What this phase does owe is that the count is not blind to the new
    record: an agent told "3 changes recorded" when the fourth is a commitment
    to this person would be reporting a different history from the one the UI
    shows.
    """

    @pytest_asyncio.fixture
    async def test_container(self, clean_database: AsyncConnection):
        container = make_async_container(ContactTestProvider(clean_database))
        yield container
        await container.close()

    @pytest_asyncio.fixture
    async def contact_service(self, test_container):
        async with test_container() as request_container:
            return await request_container.get(ContactService)

    @pytest.mark.asyncio
    async def test_the_change_count_includes_a_linked_tasks_record(
        self,
        authenticated_lifespan_client,
        contact_service: ContactService,
        clean_database: AsyncConnection,
        task_anchors,
    ):
        from core_shared.models.contacts.entities import Contact
        from core_shared.models.history import Provenance

        from app.core.history.adapters.sql.field_history_repository import (
            SqlFieldHistoryRepository,
        )
        from app.core.history.models import FieldHistoryEntry
        from app.core.tasks.models.events import contact_field_name
        from tests.integration.tasks.task_seeding import create_task

        contact = await contact_service.create_contact(
            Contact(first_name="Agent", last_name="Visible"), clean_database
        )
        assert contact.id is not None
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await SqlFieldHistoryRepository(clean_database).record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=contact_field_name(int(contact.id)),
                old_value=None,
                new_value=str(contact.id),
                changed_by="ui",
                source=Provenance.UI,
                event_id=f"evt-mcp-{task_id}-{contact.id}",
                user_id="test-user-123",
            )
        )

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "get_contact",
                {
                    "contact_id": contact.id,
                    "include_history": True,
                },
            )

            assert "Recent changes: 1 field updates recorded" in payload["summary"]

    @pytest.mark.asyncio
    async def test_a_task_linked_to_somebody_else_does_not_inflate_the_count(
        self,
        authenticated_lifespan_client,
        contact_service: ContactService,
        clean_database: AsyncConnection,
        task_anchors,
    ):
        """The positive test alone would pass for a predicate matching every task."""
        from core_shared.models.contacts.entities import Contact
        from core_shared.models.history import Provenance

        from app.core.history.adapters.sql.field_history_repository import (
            SqlFieldHistoryRepository,
        )
        from app.core.history.models import FieldHistoryEntry
        from app.core.tasks.models.events import contact_field_name
        from tests.integration.tasks.task_seeding import create_task

        subject = await contact_service.create_contact(
            Contact(first_name="Not", last_name="Involved"), clean_database
        )
        other = await contact_service.create_contact(
            Contact(first_name="Someone", last_name="Else"), clean_database
        )
        assert subject.id is not None
        assert other.id is not None
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await SqlFieldHistoryRepository(clean_database).record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=contact_field_name(int(other.id)),
                old_value=None,
                new_value=str(other.id),
                changed_by="ui",
                source=Provenance.UI,
                event_id=f"evt-mcp-other-{task_id}-{other.id}",
                user_id="test-user-123",
            )
        )

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "get_contact",
                {
                    "contact_id": subject.id,
                    "include_history": True,
                },
            )

            assert "No recent changes" in payload["summary"]


@pytest.mark.integration
class TestListUpcomingImportantDatesTool:
    """The window an agent sees, against a real database.

    The parity claim is the point of this class. The specification has agents
    compose the dashboard's view from the contacts tools, so what comes back
    here must be the same window, the same order and the same resolved days the
    page shows a browser — an agent that reported a different week, or a
    birthday on the day it was stored rather than the day it next falls, would
    be confidently wrong in a way the user could not check.

    The dates are seeded relative to an instant read inside the test and placed
    mid-window, where a midnight crossing mid-test cannot turn a correct answer
    into a failure.
    """

    @staticmethod
    def in_days(offset: int) -> date:
        """A day this many days after UTC's today — the test user's own day."""
        return datetime.now(UTC).date() + timedelta(days=offset)

    @staticmethod
    async def seed_contact(
        connection: AsyncConnection,
        contact_id: int,
        *,
        first_name: str = "Ada",
        is_favourite: bool = False,
    ) -> None:
        await connection.execute(
            text("""
                INSERT INTO contacts (
                    id, first_name, last_name, is_favourite, created_at, updated_at
                )
                VALUES (:id, :first_name, 'Lovelace', :is_favourite, NOW(), NOW())
            """),
            {
                "id": contact_id,
                "first_name": first_name,
                "is_favourite": is_favourite,
            },
        )

    @staticmethod
    async def seed_date(
        connection: AsyncConnection,
        date_id: int,
        contact_id: int,
        *,
        on: date,
        year: int | None = None,
    ) -> None:
        await connection.execute(
            text("""
                INSERT INTO contact_important_dates (
                    id, contact_id, date_type, precision, year, month, day,
                    created_at, updated_at
                )
                VALUES (:id, :contact_id, 'birthday', :precision, :year,
                        :month, :day, NOW(), NOW())
            """),
            {
                "id": date_id,
                "contact_id": contact_id,
                "precision": "full" if year else "day_month",
                "year": year,
                "month": on.month,
                "day": on.day,
            },
        )

    @staticmethod
    async def call(client, **arguments):
        return await call_mcp_tool_sessionless(
            client, "list_upcoming_important_dates", arguments, request_id=2
        )

    @pytest.mark.asyncio
    async def test_it_returns_the_window_the_total_and_the_dates(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ):
        """The full read shape per row, so no follow-up call is needed."""
        occurs_on = self.in_days(3)
        await self.seed_contact(clean_database, 1)
        await self.seed_date(clean_database, 10, 1, on=occurs_on, year=1991)

        async with authenticated_lifespan_client() as client:
            payload = await self.call(client)

        assert payload["window"]["days_ahead"] == 7
        assert payload["total_count"] == 1
        (row,) = payload["dates"]
        assert row["contact_id"] == 1
        assert row["contact_name"] == "Ada Lovelace"
        assert row["date_type"] == "birthday"
        assert row["occurs_on"] == occurs_on.isoformat()
        assert row["years"] == occurs_on.year - 1991
        assert row["observed_for_leap_day"] is False

    @pytest.mark.asyncio
    async def test_a_shorter_window_leaves_a_later_date_out(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ):
        """``days_ahead`` reaches the query rather than being echoed back."""
        await self.seed_contact(clean_database, 1)
        await self.seed_date(clean_database, 10, 1, on=self.in_days(5))

        async with authenticated_lifespan_client() as client:
            narrow = await self.call(client, days_ahead=2)
            wide = await self.call(client, days_ahead=7)

        assert narrow["window"]["days_ahead"] == 2
        assert narrow["dates"] == []
        assert len(wide["dates"]) == 1

    @pytest.mark.asyncio
    async def test_the_order_is_the_one_the_dashboard_shows(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ):
        """Soonest first, and within a day the contact who matters most."""
        shared_day = self.in_days(3)
        await self.seed_contact(clean_database, 1, first_name="Ordinary")
        await self.seed_contact(
            clean_database, 2, first_name="Favourite", is_favourite=True
        )
        await self.seed_contact(clean_database, 3, first_name="Sooner")
        await self.seed_date(clean_database, 10, 1, on=shared_day)
        await self.seed_date(clean_database, 11, 2, on=shared_day)
        await self.seed_date(clean_database, 12, 3, on=self.in_days(1))

        async with authenticated_lifespan_client() as client:
            payload = await self.call(client)

        assert [row["contact_id"] for row in payload["dates"]] == [3, 2, 1]

    @pytest.mark.asyncio
    async def test_a_quiet_week_is_an_ordinary_answer(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ):
        """Empty, with a window and a summary that say so rather than an error —
        an agent told nothing at all would report a failure instead of a fact."""
        async with authenticated_lifespan_client() as client:
            payload = await self.call(client)

        assert payload["dates"] == []
        assert payload["total_count"] == 0
        assert payload["window"]["start_date"]
        assert "No important contact dates" in payload["summary"]

    @pytest.mark.asyncio
    async def test_a_date_recorded_without_a_year_carries_no_count(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ):
        """So an agent says "birthday" rather than inventing an age."""
        await self.seed_contact(clean_database, 1)
        await self.seed_date(clean_database, 10, 1, on=self.in_days(3))

        async with authenticated_lifespan_client() as client:
            payload = await self.call(client)

        assert payload["dates"][0]["years"] is None

"""
Integration tests for MCP journal tools.

Tests the full MCP journal tools with real database integration
using Dishka dependency injection patterns.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
import pytest_asyncio
from dishka import Provider, Scope, make_async_container, provide
from fastmcp import FastMCP
from fastmcp.client import Client
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.entities import Journal
from app.core.journal.models.journal_contact_relationship import (
    JournalContactRelationship,
)
from app.core.journal.models.journal_relationship_types import (
    JournalContactRelationshipType,
)
from app.core.journal.models.value_objects import EventDateRange
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.mcp.domains.journals.tools import register_journal_tools


class JournalTestProvider(Provider):
    """Test provider for journal services with mocked dependencies."""

    def __init__(self, connection: AsyncConnection):
        super().__init__()
        self.connection = connection

    @provide(scope=Scope.REQUEST)
    def get_connection(self) -> AsyncConnection:
        return self.connection

    @provide(scope=Scope.REQUEST)
    def get_event_publisher(self, connection: AsyncConnection) -> OutboxEventPublisher:
        # Return a mock event publisher for testing
        from unittest.mock import AsyncMock

        mock_publisher = Mock(spec=OutboxEventPublisher)
        mock_publisher.publish = AsyncMock(return_value=None)
        return mock_publisher

    @provide(scope=Scope.REQUEST)
    def get_journal_service(
        self, connection: AsyncConnection, event_publisher: OutboxEventPublisher
    ) -> JournalService:
        # Create JournalService using the same factory logic
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        # Create repositories
        journal_repository = SqlJournalRepository(connection)

        # Create and return journal service
        return JournalService(
            journal_repo=journal_repository,
            event_publisher=event_publisher,
        )


class TestJournalToolsIntegration:
    """Integration tests for MCP journal tools with real services."""

    @pytest_asyncio.fixture
    async def test_container(self, clean_database: AsyncConnection):
        """Create test container with mocked dependencies."""
        container = make_async_container(JournalTestProvider(clean_database))
        yield container
        await container.close()

    @pytest_asyncio.fixture
    async def journal_service(self, test_container):
        """Get journal service from test container."""
        async with test_container() as request_container:
            return await request_container.get(JournalService)

    @pytest_asyncio.fixture
    async def sample_journal_id(self, clean_database: AsyncConnection) -> int:
        """Create a sample journal for testing and return its ID."""
        from sqlalchemy import text

        now = datetime.now(UTC)
        query = text("""
            INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
        """)

        result = await clean_database.execute(
            query,
            {
                "user_id": "current_user",
                "title": "Test Journal",
                "content": "Test content for integration testing",
                "start": now,
                "end": now + timedelta(hours=1),
            },
        )
        row = result.fetchone()
        assert row is not None
        return int(row[0])

    @pytest.mark.asyncio
    async def test_mcp_server_tool_registration_integration(self):
        """Test that all journal tools are properly registered with the MCP server."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_journal_tools(mcp)

        # Use FastMCP Client to test tool registration
        async with Client(mcp) as client:
            # Get list of available tools
            tools = await client.list_tools()

            # Verify all expected tools are registered
            tool_names = [tool.name for tool in tools]
            expected_tools = [
                "create_journal_entry",
                "get_journal",
                "update_journal_entry",
                "delete_journal",
                "search_journals",
                "link_journal_to_contact",
                "get_contact_journals",
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
    async def test_create_journal_integration_real_db(
        self, journal_service: JournalService, clean_database: AsyncConnection
    ):
        """Test creating a journal entry with real database integration."""
        # Test creating a journal directly with the service
        now = datetime.now(UTC)

        # Create a test journal
        journal = Journal(
            user_id="current_user",
            title="Integration Test Journal",
            content="This is a test journal entry",
            event_date_range=EventDateRange(
                start=now,
                end=now + timedelta(hours=2),
            ),
        )

        # Save the journal
        saved_journal = await journal_service.create_journal(journal, clean_database)

        # Verify the journal was created
        assert saved_journal is not None
        assert saved_journal.id is not None
        assert saved_journal.title == "Integration Test Journal"
        assert saved_journal.content == "This is a test journal entry"
        assert saved_journal.user_id == "current_user"

    @pytest.mark.asyncio
    async def test_get_journal_integration_real_db(
        self, journal_service: JournalService, sample_journal_id: int
    ):
        """Test getting a journal entry with real database integration."""
        # Retrieve the journal
        retrieved_journal = await journal_service.get_journal(sample_journal_id)

        # Verify the journal was retrieved
        assert retrieved_journal is not None
        assert retrieved_journal.id == sample_journal_id
        assert retrieved_journal.title == "Test Journal"
        assert retrieved_journal.content == "Test content for integration testing"

    @pytest.mark.asyncio
    async def test_update_journal_integration_real_db(
        self,
        journal_service: JournalService,
        sample_journal_id: int,
        clean_database: AsyncConnection,
    ):
        """Test updating a journal entry with real database integration."""
        # Get the existing journal
        existing_journal = await journal_service.get_journal(sample_journal_id)
        assert existing_journal is not None

        # Update the journal fields
        existing_journal.title = "Updated Test Journal"
        existing_journal.content = "Updated content via integration test"

        # Track changed fields
        changed_fields = {
            "title": "Updated Test Journal",
            "content": "Updated content via integration test",
        }

        # Save the updated journal
        updated_journal = await journal_service.update_journal(
            existing_journal, changed_fields, clean_database
        )

        # Verify the journal was updated
        assert updated_journal is not None
        assert updated_journal.id == sample_journal_id
        assert updated_journal.title == "Updated Test Journal"
        assert updated_journal.content == "Updated content via integration test"

        # Retrieve the journal again to verify persistence
        retrieved_journal = await journal_service.get_journal(sample_journal_id)
        assert retrieved_journal is not None
        assert retrieved_journal.title == "Updated Test Journal"
        assert retrieved_journal.content == "Updated content via integration test"

    @pytest.mark.asyncio
    async def test_delete_journal_integration_real_db(
        self,
        journal_service: JournalService,
        sample_journal_id: int,
        clean_database: AsyncConnection,
    ):
        """Test deleting a journal entry with real database integration."""
        # Delete the journal
        await journal_service.delete_journal(sample_journal_id, clean_database)

        # Verify the journal was deleted
        deleted_journal = await journal_service.get_journal(sample_journal_id)
        assert deleted_journal is None

    @pytest.mark.asyncio
    async def test_link_journal_to_contact_integration_real_db(
        self,
        journal_service: JournalService,
        sample_journal_id: int,
        clean_database: AsyncConnection,
    ):
        """Test linking a journal to a contact with real database integration."""
        from sqlalchemy import text

        from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
            SqlJournalContactRelationshipRepository,
        )

        # Create a sample contact first
        contact_query = text("""
            INSERT INTO contacts (first_name, last_name)
            VALUES (:first_name, :last_name)
            RETURNING id
        """)

        contact_result = await clean_database.execute(
            contact_query,
            {
                "first_name": "Test",
                "last_name": "Contact",
            },
        )
        contact_row = contact_result.fetchone()
        assert contact_row is not None
        contact_id = int(contact_row[0])

        # Create a journal-contact relationship
        relationship_repo = SqlJournalContactRelationshipRepository(clean_database)
        relationship = JournalContactRelationship(
            journal_id=sample_journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )

        # Save the relationship using create method
        saved_relationship = await relationship_repo.create(relationship)

        # Verify the relationship was created
        assert saved_relationship is not None
        assert saved_relationship.journal_id == sample_journal_id
        assert saved_relationship.contact_id == contact_id
        assert (
            saved_relationship.relationship_type
            == JournalContactRelationshipType.PARTICIPANT
        )

    @pytest.mark.asyncio
    async def test_get_contact_journals_integration_real_db(
        self,
        journal_service: JournalService,
        sample_journal_id: int,
        clean_database: AsyncConnection,
    ):
        """Test getting journal relationships for a contact with real database integration."""
        from sqlalchemy import text

        from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
            SqlJournalContactRelationshipRepository,
        )

        # Create a sample contact first
        contact_query = text("""
            INSERT INTO contacts (first_name, last_name)
            VALUES (:first_name, :last_name)
            RETURNING id
        """)

        contact_result = await clean_database.execute(
            contact_query,
            {
                "first_name": "Test",
                "last_name": "Contact",
            },
        )
        contact_row = contact_result.fetchone()
        assert contact_row is not None
        contact_id = int(contact_row[0])

        # Create a journal-contact relationship
        relationship_repo = SqlJournalContactRelationshipRepository(clean_database)
        relationship = JournalContactRelationship(
            journal_id=sample_journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )

        # Save the relationship using create method
        await relationship_repo.create(relationship)

        # Get relationships for the contact
        relationships = await relationship_repo.get_by_contact(contact_id)

        # Verify the relationships were retrieved
        assert len(relationships) >= 1
        assert any(r.journal_id == sample_journal_id for r in relationships)

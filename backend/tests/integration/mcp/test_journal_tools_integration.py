"""
Integration tests for MCP journal tools.

Tests the full MCP journal tools with real database integration
using Dishka dependency injection patterns.
"""

from datetime import UTC, datetime

import pytest
from fastmcp import FastMCP
from fastmcp.client import Client
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.entities import Journal
from app.core.journal.models.value_objects import EventDateRange
from app.core.journal.services.journal_service import JournalService
from app.mcp.domains.journals.tools import register_journal_tools


class TestJournalToolsIntegration:
    """Integration tests for MCP journal tools with real services."""

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
                "get_journal",
                "search_journals",
                "list_journals",
                "create_journal_entry",
                "update_journal_entry",
                "delete_journal",
                "get_contact_journals",
                "link_journal_to_contact",
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
        """Test creating a journal with real database integration."""
        # Create a test journal
        start_date = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end_date = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        journal = Journal(
            user_id="test-user-123",
            title="Test Journal Entry",
            content="This is a test journal entry",
            event_date_range=EventDateRange(start=start_date, end=end_date),
        )

        # Create the journal using the service
        created_journal = await journal_service.create_journal(journal, clean_database)

        # Verify the journal was created
        assert created_journal.id is not None
        assert created_journal.title == "Test Journal Entry"
        assert created_journal.content == "This is a test journal entry"
        assert created_journal.user_id == "test-user-123"

        # Verify the journal was actually saved to the database
        retrieved_journal = await journal_service.get_journal_by_id(created_journal.id)
        assert retrieved_journal is not None
        assert retrieved_journal.title == "Test Journal Entry"

    @pytest.mark.asyncio
    async def test_update_journal_integration_real_db(
        self, journal_service: JournalService, clean_database: AsyncConnection
    ):
        """Test updating a journal with real database integration."""
        # Create a test journal first
        start_date = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end_date = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        journal = Journal(
            user_id="test-user-123",
            title="Original Title",
            content="Original content",
            event_date_range=EventDateRange(start=start_date, end=end_date),
        )

        created_journal = await journal_service.create_journal(journal, clean_database)
        assert created_journal.id is not None

        # Update the journal
        created_journal.title = "Updated Title"
        created_journal.content = "Updated content"

        updated_journal = await journal_service.update_journal(
            created_journal,
            {"title": "Updated Title", "content": "Updated content"},
            clean_database,
        )

        # Verify the journal was updated
        assert updated_journal.title == "Updated Title"
        assert updated_journal.content == "Updated content"

        # Verify the update was persisted
        retrieved_journal = await journal_service.get_journal_by_id(created_journal.id)
        assert retrieved_journal is not None
        assert retrieved_journal.title == "Updated Title"
        assert retrieved_journal.content == "Updated content"

    @pytest.mark.asyncio
    async def test_delete_journal_integration_real_db(
        self, journal_service: JournalService, clean_database: AsyncConnection
    ):
        """Test deleting a journal with real database integration."""
        # Create a test journal first
        start_date = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end_date = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

        journal = Journal(
            user_id="test-user-123",
            title="Journal to Delete",
            content="This will be deleted",
            event_date_range=EventDateRange(start=start_date, end=end_date),
        )

        created_journal = await journal_service.create_journal(journal, clean_database)
        assert created_journal.id is not None

        # Delete the journal
        await journal_service.delete_journal(created_journal.id, clean_database)

        # Verify the journal was deleted
        retrieved_journal = await journal_service.get_journal_by_id(created_journal.id)
        assert retrieved_journal is None

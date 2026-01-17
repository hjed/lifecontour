"""
Integration tests for MCP journal tools.

Tests the full MCP journal tools with real database integration
using Dishka dependency injection patterns.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.entities import Journal
from app.core.journal.models.value_objects import EventDateRange
from app.core.journal.services.journal_service import JournalService


class TestJournalToolsIntegration:
    """Integration tests for MCP journal tools with real services."""

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
        retrieved_journal = await journal_service.get_journal(created_journal.id)
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
        retrieved_journal = await journal_service.get_journal(created_journal.id)
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
        retrieved_journal = await journal_service.get_journal(created_journal.id)
        assert retrieved_journal is None

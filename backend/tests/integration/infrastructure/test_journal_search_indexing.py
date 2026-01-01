"""
Integration tests for journal search indexing.

Tests the JournalIndexingService with real MeiliSearch and PostgreSQL.
"""

from datetime import datetime

import pytest
from meilisearch import Client as MeiliSearchClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.search.journal_indexing_service import JournalIndexingService
from app.infrastructure.search.meilisearch_client import get_index_name


@pytest.mark.integration
@pytest.mark.meilisearch
class TestJournalSearchIndexing:
    """Integration tests for journal search indexing."""

    @pytest.fixture
    async def indexing_service(self, async_connection: AsyncConnection, test_settings):
        """Create a journal indexing service with database connection."""
        # Create a MeiliSearch client with test settings
        client = MeiliSearchClient(
            url=test_settings.meilisearch_url,
            api_key=test_settings.meilisearch_api_key,
        )
        return JournalIndexingService(db_connection=async_connection, client=client)

    @pytest.mark.asyncio
    async def test_index_journal_created_event(
        self, indexing_service: JournalIndexingService
    ):
        """Test indexing a newly created journal."""
        # Create a journal created event
        now = datetime.now()
        event = OutboxEvent(
            id=1,
            event_id="test-event-1",
            aggregate_id=1,
            event_type="JournalCreated",
            event_data={
                "journal_id": 1,
                "user_id": "test-user",
                "title": "My First Journal",
                "content": "This is my first journal entry",
            },
            occurred_at=now,
            processed_at=None,
            retry_count=0,
            created_at=now,
        )

        # Process the event
        await indexing_service.process_event(event)

        # Verify the journal was indexed
        client = indexing_service.client
        index_name = get_index_name("journals")
        index = client.index(index_name)

        # Search for the journal
        results = index.search("My First Journal")
        assert len(results["hits"]) >= 1
        assert any(hit["id"] == 1 for hit in results["hits"])

    @pytest.mark.asyncio
    async def test_index_journal_updated_event(
        self, indexing_service: JournalIndexingService
    ):
        """Test updating an indexed journal."""
        # First, create and index a journal
        now = datetime.now()
        create_event = OutboxEvent(
            id=1,
            event_id="test-event-1",
            aggregate_id=1,
            event_type="JournalCreated",
            event_data={
                "journal_id": 1,
                "user_id": "test-user",
                "title": "Original Title",
                "content": "Original content",
            },
            occurred_at=now,
            processed_at=None,
            retry_count=0,
            created_at=now,
        )
        await indexing_service.process_event(create_event)

        # Update the journal
        update_event = OutboxEvent(
            id=2,
            event_id="test-event-2",
            aggregate_id=1,
            event_type="JournalUpdated",
            event_data={
                "journal_id": 1,
                "user_id": "test-user",
                "title": "Updated Title",
                "content": "Updated content",
            },
            occurred_at=now,
            processed_at=None,
            retry_count=0,
            created_at=now,
        )
        await indexing_service.process_event(update_event)

        # Verify the update
        client = indexing_service.client
        index_name = get_index_name("journals")
        index = client.index(index_name)

        results = index.search("Updated Title")
        assert len(results["hits"]) >= 1
        assert results["hits"][0]["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_index_journal_deleted_event(
        self, indexing_service: JournalIndexingService
    ):
        """Test deleting a journal from the index."""
        # Create and index a journal
        now = datetime.now()
        create_event = OutboxEvent(
            id=1,
            event_id="test-event-1",
            aggregate_id=1,
            event_type="JournalCreated",
            event_data={
                "journal_id": 1,
                "user_id": "test-user",
                "title": "To Be Deleted",
                "content": "This will be deleted",
            },
            occurred_at=now,
            processed_at=None,
            retry_count=0,
            created_at=now,
        )
        await indexing_service.process_event(create_event)

        # Delete the journal
        delete_event = OutboxEvent(
            id=2,
            event_id="test-event-2",
            aggregate_id=1,
            event_type="JournalDeleted",
            event_data={"journal_id": 1},
            occurred_at=now,
            processed_at=None,
            retry_count=0,
            created_at=now,
        )
        await indexing_service.process_event(delete_event)

        # Verify deletion
        client = indexing_service.client
        index_name = get_index_name("journals")
        index = client.index(index_name)

        results = index.search("To Be Deleted")
        assert len(results["hits"]) == 0

"""
Integration tests for journal search indexing.

Tests the JournalIndexingService with real MeiliSearch and PostgreSQL.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from core_shared.models.journals import EventDateRange, Journal
from meilisearch import Client as MeiliSearchClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.models.journal_tag import JournalTag
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
        now = datetime.now(UTC)
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


@pytest.mark.integration
@pytest.mark.meilisearch
class TestJournalTagReindexing:
    """Journal tag events keep the indexed ``tag_ids`` in step with the database.

    Unlike the tests above, these create **real** journal and tag rows: the tag
    path deliberately has no fallback document, so the assertions are only about
    something if ``_fetch_complete_journal_data`` returns real data.
    """

    @pytest.fixture
    def indexing_service(self, async_connection: AsyncConnection, test_settings):
        """Journal indexing service wired to the test MeiliSearch instance."""
        client = MeiliSearchClient(
            url=test_settings.meilisearch_url,
            api_key=test_settings.meilisearch_api_key,
        )
        return JournalIndexingService(db_connection=async_connection, client=client)

    async def _journal_id(self, conn: AsyncConnection) -> int:
        saved = await SqlJournalRepository(conn).save(
            Journal(
                id=None,
                user_id="user-tag-reindex",
                title=f"Tag reindex subject {uuid4()}",
                content="Body",
                event_date_range=EventDateRange(
                    start=datetime(2026, 4, 1, tzinfo=UTC),
                    end=datetime(2026, 4, 1, tzinfo=UTC),
                ),
            )
        )
        assert saved.id is not None
        return saved.id

    async def _tag_id(self, conn: AsyncConnection, prefix: str) -> UUID:
        # The journal tag namespace is global and its names are unique, so a
        # fixed name would collide with a concurrently running test.
        saved = await SqlJournalTagRepository(conn).save(
            JournalTag(name=f"{prefix}-{uuid4()}")
        )
        assert saved.id is not None
        return saved.id

    def _indexed_tag_ids(
        self, indexing_service: JournalIndexingService, journal_id: int
    ) -> list[str]:
        index = indexing_service.client.index(get_index_name("journals"))
        return list(index.get_document(journal_id).tag_ids)

    def _tag_event(
        self, event_type: str, journal_id: int, tag_id: UUID, **extra: object
    ) -> OutboxEvent:
        now = datetime.now(UTC)
        return OutboxEvent(
            id=1,
            event_id=f"{event_type}-{uuid4()}",
            aggregate_id=journal_id,
            event_type=event_type,
            event_data={
                "journal_id": journal_id,
                "tag_id": str(tag_id),
                "tag_name": "Reindexed",
                "source": "ui",
                "changed_by": "ui",
                **extra,
            },
            occurred_at=now,
            retry_count=0,
            created_at=now,
        )

    @pytest.mark.asyncio
    async def test_assignment_indexes_the_tag(
        self,
        indexing_service: JournalIndexingService,
        async_connection: AsyncConnection,
    ) -> None:
        """Assigning a tag puts its id on the journal's search document.

        Before this event drove re-indexing, a tag added through the detail-page
        editor left MeiliSearch pointing at the pre-assignment tag set until some
        unrelated edit re-indexed the journal.
        """
        journal_id = await self._journal_id(async_connection)
        tag_id = await self._tag_id(async_connection, "Assign")
        repo = SqlJournalTagRepository(async_connection)
        await repo.assign_tag(journal_id, tag_id)

        await indexing_service.process_event(
            self._tag_event("JournalTagAssigned", journal_id, tag_id)
        )

        assert self._indexed_tag_ids(indexing_service, journal_id) == [str(tag_id)]

    @pytest.mark.asyncio
    async def test_removal_drops_the_tag_from_the_index(
        self,
        indexing_service: JournalIndexingService,
        async_connection: AsyncConnection,
    ) -> None:
        """Removing a tag takes its id off the document, leaving the others."""
        journal_id = await self._journal_id(async_connection)
        kept_id = await self._tag_id(async_connection, "Kept")
        dropped_id = await self._tag_id(async_connection, "Dropped")
        repo = SqlJournalTagRepository(async_connection)
        await repo.assign_tag(journal_id, kept_id)
        await repo.assign_tag(journal_id, dropped_id)
        await indexing_service.process_event(
            self._tag_event("JournalTagAssigned", journal_id, kept_id)
        )

        await repo.remove_tag(journal_id, dropped_id)
        await indexing_service.process_event(
            self._tag_event("JournalTagRemoved", journal_id, dropped_id)
        )

        assert self._indexed_tag_ids(indexing_service, journal_id) == [str(kept_id)]

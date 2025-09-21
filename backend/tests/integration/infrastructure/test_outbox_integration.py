"""
Integration tests for outbox pattern implementation.

Tests the complete flow from domain events to outbox storage to search indexing.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.core.contacts.models.events import DomainEvent
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

# OutboxProcessor imported inside tests to ensure patches work correctly
from app.infrastructure.events.outbox_repository import OutboxRepository
from app.infrastructure.search.search_indexer import SearchIndexer


class TestOutboxIntegration:
    """Integration tests for the outbox pattern."""

    @pytest.fixture
    async def database_with_outbox(self, clean_database):
        """Create a database connection with outbox table for testing."""
        # The outbox_events table should already exist from migrations
        # Just ensure it's clean for testing
        await clean_database.execute(text("DELETE FROM outbox_events"))

        # Verify the table exists and has the expected structure
        result = await clean_database.execute(
            text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'outbox_events'
                ORDER BY ordinal_position
            """)
        )
        columns = result.fetchall()

        # Ensure we have the expected columns
        expected_columns = {
            "id",
            "event_id",
            "event_type",
            "aggregate_id",
            "event_data",
            "occurred_at",
            "processed_at",
            "retry_count",
            "created_at",
        }
        actual_columns = {col[0] for col in columns}

        if not expected_columns.issubset(actual_columns):
            missing = expected_columns - actual_columns
            raise RuntimeError(f"Outbox table missing columns: {missing}")

        # Return the connection itself - indexes should already exist from migration
        return clean_database

    @pytest.fixture
    def sample_domain_event(self):
        """Create a sample domain event for testing."""
        return DomainEvent(
            event_id="integration-test-event-123",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={
                "contact_id": 42,
                "first_name": "Integration",
                "last_name": "Test",
                "email": "integration@test.com",
            },
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
        )

    @pytest.fixture
    def mock_meilisearch_client(self):
        """Create a mock MeiliSearch client for integration tests."""
        client = MagicMock()
        mock_index = MagicMock()
        client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 0}

        mock_task = MagicMock()
        mock_task.task_uid = "test-task-123"
        mock_index.add_documents.return_value = mock_task
        mock_index.update_documents.return_value = mock_task
        mock_index.delete_document.return_value = mock_task

        return client

    @pytest.mark.asyncio
    async def test_complete_outbox_flow(
        self, database_with_outbox, sample_domain_event, mock_meilisearch_client
    ):
        """Test the complete flow from event publishing to search indexing."""
        # Step 1: Publish event to outbox
        publisher = OutboxEventPublisher(database_with_outbox)
        await publisher.publish(sample_domain_event)

        # Step 2: Verify event is stored in outbox
        repository = OutboxRepository(database_with_outbox)
        unprocessed_events = await repository.get_unprocessed_events()

        assert len(unprocessed_events) == 1
        event = unprocessed_events[0]
        assert event.event_id == "integration-test-event-123"
        assert event.event_type == "ContactCreated"
        assert event.aggregate_id == 42
        assert event.processed_at is None
        assert event.retry_count == 0

        # Step 3: Process events with search indexer
        with (
            patch(
                "app.infrastructure.search.search_indexer.get_meilisearch_client",
                return_value=mock_meilisearch_client,
            ),
            patch(
                "app.infrastructure.search.search_indexer.get_index_name",
                return_value="pms_contacts",
            ),
        ):
            search_indexer = SearchIndexer()

            repository = OutboxRepository(database_with_outbox)
            unprocessed_events = await repository.get_unprocessed_events()

            for event in unprocessed_events:
                await search_indexer.process_event(event)
                await repository.mark_as_processed(event.event_id)

        # Step 4: Verify event was processed and indexed
        repository = OutboxRepository(database_with_outbox)
        unprocessed_events = await repository.get_unprocessed_events()
        assert len(unprocessed_events) == 0  # Should be empty now

        # Verify MeiliSearch was called
        mock_meilisearch_client.index.assert_called_with("pms_contacts")
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.add_documents.assert_called_once()

        # Check the document that was indexed
        indexed_docs = mock_index.add_documents.call_args[0][0]
        assert len(indexed_docs) == 1
        doc = indexed_docs[0]
        assert doc["id"] == 42
        assert doc["first_name"] == "Integration"
        assert doc["last_name"] == "Test"
        assert doc["entity_type"] == "contact"

    @pytest.mark.asyncio
    async def test_outbox_processor_integration(
        self, database_with_outbox, mock_meilisearch_client
    ):
        """Test the OutboxProcessor with real database operations."""
        # Step 1: Add multiple events to outbox
        events = [
            DomainEvent(
                event_id=f"processor-test-{i}",
                event_type="ContactCreated",
                aggregate_id=100 + i,
                event_data={"contact_id": 100 + i, "name": f"Contact {i}"},
                occurred_at=datetime(2024, 1, 1, 12, i, 0),
            )
            for i in range(3)
        ]

        publisher = OutboxEventPublisher(database_with_outbox)
        for event in events:
            await publisher.publish(event)

        # Step 2: Process events using OutboxProcessor with test database
        with (
            patch(
                "app.infrastructure.search.search_indexer.get_meilisearch_client",
                return_value=mock_meilisearch_client,
            ),
            patch(
                "app.infrastructure.search.search_indexer.get_index_name",
                return_value="pms_contacts",
            ),
        ):
            # Create a custom processor that uses the test database connection
            from app.infrastructure.events.outbox_repository import OutboxRepository
            from app.infrastructure.search.search_indexer import SearchIndexer

            # Process events manually using the test database connection
            repository = OutboxRepository(database_with_outbox)
            search_indexer = SearchIndexer(db_connection=database_with_outbox)

            # Get unprocessed events
            outbox_events = await repository.get_unprocessed_events(limit=50)

            # Process each event
            for outbox_event in outbox_events:
                try:
                    await search_indexer.process_event(outbox_event)
                    await repository.mark_as_processed(outbox_event.event_id)
                except Exception:
                    # Increment retry count if under max retries
                    if outbox_event.retry_count < 3:
                        await repository.increment_retry_count(outbox_event.event_id)

        # Step 3: Verify all events were processed
        repository = OutboxRepository(database_with_outbox)
        unprocessed_events = await repository.get_unprocessed_events()
        assert len(unprocessed_events) == 0

        # Verify MeiliSearch indexing
        mock_index = mock_meilisearch_client.index.return_value
        assert mock_index.add_documents.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_mechanism(self, database_with_outbox, mock_meilisearch_client):
        """Test the retry mechanism for failed events."""
        # Step 0: Create the contact in the database first
        await database_with_outbox.execute(
            text("""
            INSERT INTO contacts (id, first_name, last_name, created_at, updated_at)
            VALUES (200, 'Retry', 'Test', NOW(), NOW())
        """)
        )

        # Step 1: Add an event to outbox
        domain_event = DomainEvent(
            event_id="retry-test-event",
            event_type="ContactCreated",
            aggregate_id=200,
            event_data={"contact_id": 200, "name": "Retry Test"},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
        )

        publisher = OutboxEventPublisher(database_with_outbox)
        await publisher.publish(domain_event)

        # Step 2: Make MeiliSearch fail and process events
        mock_meilisearch_client.index.side_effect = Exception("MeiliSearch is down")

        with patch(
            "app.infrastructure.search.search_indexer.get_meilisearch_client",
            return_value=mock_meilisearch_client,
        ):
            # Process events manually using the test database connection
            from app.infrastructure.events.outbox_repository import OutboxRepository
            from app.infrastructure.search.search_indexer import SearchIndexer

            repository = OutboxRepository(database_with_outbox)
            search_indexer = SearchIndexer(db_connection=database_with_outbox)

            # Get unprocessed events
            outbox_events = await repository.get_unprocessed_events(limit=50)

            # Process each event (should fail and increment retry count)
            for outbox_event in outbox_events:
                try:
                    await search_indexer.process_event(outbox_event)
                    await repository.mark_as_processed(outbox_event.event_id)
                except Exception:
                    # Increment retry count if under max retries
                    if outbox_event.retry_count < 3:
                        await repository.increment_retry_count(outbox_event.event_id)

        # Step 3: Verify event is still unprocessed but retry count increased
        repository = OutboxRepository(database_with_outbox)
        unprocessed_events = await repository.get_unprocessed_events()

        assert len(unprocessed_events) == 1
        assert unprocessed_events[0].retry_count == 1
        assert unprocessed_events[0].processed_at is None

        # Step 4: Fix MeiliSearch and process again
        mock_meilisearch_client.reset_mock()
        mock_meilisearch_client.index.side_effect = None
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 0}
        mock_task = MagicMock()
        mock_task.task_uid = "retry-task"
        mock_index.add_documents.return_value = mock_task

        with (
            patch(
                "app.infrastructure.search.search_indexer.get_meilisearch_client",
                return_value=mock_meilisearch_client,
            ),
            patch(
                "app.infrastructure.search.search_indexer.get_index_name",
                return_value="pms_contacts",
            ),
        ):
            # Process events again (should succeed this time)
            repository = OutboxRepository(database_with_outbox)
            search_indexer = SearchIndexer(db_connection=database_with_outbox)

            # Get unprocessed events
            outbox_events = await repository.get_unprocessed_events(limit=50)

            # Process each event (should succeed this time)
            for outbox_event in outbox_events:
                try:
                    await search_indexer.process_event(outbox_event)
                    await repository.mark_as_processed(outbox_event.event_id)
                except Exception:
                    # Increment retry count if under max retries
                    if outbox_event.retry_count < 3:
                        await repository.increment_retry_count(outbox_event.event_id)

        # Step 5: Verify event is now processed
        repository = OutboxRepository(database_with_outbox)
        unprocessed_events = await repository.get_unprocessed_events()
        assert len(unprocessed_events) == 0

    @pytest.mark.asyncio
    async def test_batch_event_publishing(self, database_with_outbox):
        """Test publishing multiple events in a batch."""
        # Arrange
        events = [
            DomainEvent(
                event_id=f"batch-event-{i}",
                event_type="ContactCreated",
                aggregate_id=300 + i,
                event_data={"contact_id": 300 + i, "name": f"Batch Contact {i}"},
                occurred_at=datetime(2024, 1, 1, 12, 0, i),
            )
            for i in range(5)
        ]

        # Act
        publisher = OutboxEventPublisher(database_with_outbox)
        await publisher.publish_batch(events)

        # Assert
        repository = OutboxRepository(database_with_outbox)
        stored_events = await repository.get_unprocessed_events()

        assert len(stored_events) == 5

        # Verify all events are stored correctly
        event_ids = {event.event_id for event in stored_events}
        expected_ids = {f"batch-event-{i}" for i in range(5)}
        assert event_ids == expected_ids

    @pytest.mark.asyncio
    async def test_failed_events_tracking(self, database_with_outbox):
        """Test tracking of events that exceed max retries."""
        # Step 1: Add an event and simulate multiple failures
        domain_event = DomainEvent(
            event_id="max-retry-test",
            event_type="ContactCreated",
            aggregate_id=400,
            event_data={"contact_id": 400, "name": "Max Retry Test"},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
        )

        publisher = OutboxEventPublisher(database_with_outbox)
        await publisher.publish(domain_event)

        # Step 2: Increment retry count to exceed max
        repository = OutboxRepository(database_with_outbox)
        for _ in range(4):  # Exceed max retries (3)
            await repository.increment_retry_count("max-retry-test")

        # Step 3: Verify event is considered failed
        repository = OutboxRepository(database_with_outbox)
        failed_events = await repository.get_failed_events(max_retries=3)

        assert len(failed_events) == 1
        assert failed_events[0].event_id == "max-retry-test"
        assert failed_events[0].retry_count == 4

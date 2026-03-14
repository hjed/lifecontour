"""
Unit tests for OutboxProcessor.

Tests the background processor that handles outbox events and sends them to external systems.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.integrations.outbox_event_processor import (
    PermanentOutboxEventProcessingError,
)
from app.infrastructure.events.outbox_processor import (
    OutboxProcessor,
    get_outbox_processor,
)
from app.infrastructure.events.outbox_repository import OutboxEvent


class TestOutboxProcessor:
    """Test cases for OutboxProcessor."""

    @pytest.fixture
    def mock_search_indexer(self):
        """Create a mock search indexer."""
        indexer = MagicMock()
        indexer.process_event = AsyncMock()
        return indexer

    @pytest.fixture
    def processor(self, mock_search_indexer):
        """Create an OutboxProcessor instance with mock dependencies."""
        with patch(
            "app.infrastructure.events.outbox_processor.SearchIndexer",
            return_value=mock_search_indexer,
        ):
            return OutboxProcessor()

    @pytest.fixture
    def sample_outbox_events(self):
        """Create sample outbox events for testing."""
        return [
            OutboxEvent(
                id=1,
                event_id="event-1",
                event_type="ContactCreated",
                aggregate_id=42,
                event_data={"contact_id": 42, "name": "John"},
                occurred_at=datetime(2024, 1, 1, 12, 0, 0),
                processed_at=None,
                retry_count=0,
                created_at=datetime(2024, 1, 1, 12, 0, 0),
            ),
            OutboxEvent(
                id=2,
                event_id="event-2",
                event_type="ContactUpdated",
                aggregate_id=43,
                event_data={"contact_id": 43, "name": "Jane"},
                occurred_at=datetime(2024, 1, 1, 12, 5, 0),
                processed_at=None,
                retry_count=0,
                created_at=datetime(2024, 1, 1, 12, 5, 0),
            ),
        ]

    @pytest.mark.asyncio
    async def test_process_events_success(
        self, processor, mock_search_indexer, sample_outbox_events
    ):
        """Test successful processing of outbox events."""
        # Arrange
        mock_conn = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        @asynccontextmanager
        async def mock_begin_nested():
            yield mock_conn

        mock_conn.begin_nested = mock_begin_nested

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin

        mock_repository = MagicMock()
        mock_repository.get_unprocessed_events = AsyncMock(
            return_value=sample_outbox_events
        )
        mock_repository.mark_as_processed = AsyncMock()

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.OutboxRepository",
                return_value=mock_repository,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.SearchIndexer",
                return_value=mock_search_indexer,
            ),
        ):
            # Act
            await processor.process_events()

        # Assert
        assert mock_search_indexer.process_event.call_count == 2
        assert mock_repository.mark_as_processed.call_count == 2

        # Verify events were processed in order
        mock_search_indexer.process_event.assert_any_call(sample_outbox_events[0])
        mock_search_indexer.process_event.assert_any_call(sample_outbox_events[1])

        # Verify events were marked as processed
        mock_repository.mark_as_processed.assert_any_call("event-1")
        mock_repository.mark_as_processed.assert_any_call("event-2")

    @pytest.mark.asyncio
    async def test_process_events_no_events(self, processor, mock_search_indexer):
        """Test processing when no events are available."""
        # Arrange
        mock_conn = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        @asynccontextmanager
        async def mock_begin_nested():
            yield mock_conn

        mock_conn.begin_nested = mock_begin_nested

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin

        mock_repository = MagicMock()
        mock_repository.get_unprocessed_events = AsyncMock(return_value=[])

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.OutboxRepository",
                return_value=mock_repository,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.SearchIndexer",
                return_value=mock_search_indexer,
            ),
        ):
            # Act
            await processor.process_events()

        # Assert
        mock_search_indexer.process_event.assert_not_called()
        mock_repository.mark_as_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_events_with_failures(
        self, processor, mock_search_indexer, sample_outbox_events
    ):
        """Test processing events when some fail."""
        # Arrange
        mock_conn = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        @asynccontextmanager
        async def mock_begin_nested():
            yield mock_conn

        mock_conn.begin_nested = mock_begin_nested

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin

        mock_repository = MagicMock()
        mock_repository.get_unprocessed_events = AsyncMock(
            return_value=sample_outbox_events
        )
        mock_repository.mark_as_processed = AsyncMock()
        mock_repository.increment_retry_count = AsyncMock()

        # Make the first event processing fail
        mock_search_indexer.process_event.side_effect = [
            Exception("Processing failed"),
            None,  # Second event succeeds
        ]

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.OutboxRepository",
                return_value=mock_repository,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.SearchIndexer",
                return_value=mock_search_indexer,
            ),
        ):
            # Act
            await processor.process_events()

        # Assert
        assert mock_search_indexer.process_event.call_count == 2
        mock_repository.get_unprocessed_events.assert_called_once_with(
            limit=processor.batch_size, max_retry_count=processor.max_retries
        )

        # First event should have retry count incremented
        mock_repository.increment_retry_count.assert_called_once_with("event-1")

        # Second event should be marked as processed
        mock_repository.mark_as_processed.assert_called_once_with("event-2")

    @pytest.mark.asyncio
    async def test_process_events_marks_permanent_failures_as_failed(
        self, processor, mock_search_indexer, sample_outbox_events
    ):
        """Test permanently invalid events are marked failed without retrying."""
        mock_conn = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        @asynccontextmanager
        async def mock_begin_nested():
            yield mock_conn

        mock_conn.begin_nested = mock_begin_nested

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin

        failed_event = sample_outbox_events[0]
        mock_repository = MagicMock()
        mock_repository.get_unprocessed_events = AsyncMock(return_value=[failed_event])
        mock_repository.increment_retry_count = AsyncMock()
        mock_repository.mark_as_failed = AsyncMock()
        mock_repository.mark_as_processed = AsyncMock()

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.OutboxRepository",
                return_value=mock_repository,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.SearchIndexer",
                return_value=mock_search_indexer,
            ),
            patch.object(
                processor,
                "_process_single_event",
                AsyncMock(
                    side_effect=PermanentOutboxEventProcessingError(
                        "Missing required contact field 'first_name'"
                    )
                ),
            ),
        ):
            await processor.process_events()

        mock_repository.mark_as_failed.assert_called_once_with(
            failed_event.event_id, retry_count=processor.max_retries
        )
        mock_repository.increment_retry_count.assert_not_called()
        mock_repository.mark_as_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_single_event_reraises_permanent_failures_without_logging(
        self, processor, mock_search_indexer
    ):
        """Test permanent failures bubble up without duplicate single-event logs."""
        contact_event = OutboxEvent(
            id=1,
            event_id="contact-event-1",
            event_type="contact.created",
            aggregate_id=42,
            event_data={"contact_id": 42},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        mock_repository = MagicMock()
        mock_repository.mark_as_processed = AsyncMock()

        with (
            patch.object(
                processor,
                "_process_contact_event",
                AsyncMock(
                    side_effect=PermanentOutboxEventProcessingError("invalid payload")
                ),
            ),
            patch(
                "app.infrastructure.events.outbox_processor.logger.error"
            ) as mock_log_error,
        ):
            with pytest.raises(
                PermanentOutboxEventProcessingError, match="invalid payload"
            ):
                await processor._process_single_event(
                    contact_event, mock_repository, mock_search_indexer
                )

        mock_repository.mark_as_processed.assert_not_called()
        mock_log_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_failed_events_summary(self, processor):
        """Test getting a summary of failed events."""
        # Arrange
        failed_events = [
            OutboxEvent(
                id=4,
                event_id="failed-1",
                event_type="ContactCreated",
                aggregate_id=100,
                event_data={"contact_id": 100},
                occurred_at=datetime(2024, 1, 1, 9, 0, 0),
                processed_at=None,
                retry_count=5,
                created_at=datetime(2024, 1, 1, 9, 0, 0),
            )
        ]

        mock_conn = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        @asynccontextmanager
        async def mock_begin_nested():
            yield mock_conn

        mock_conn.begin_nested = mock_begin_nested

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin

        mock_repository = MagicMock()
        mock_repository.get_failed_events = AsyncMock(return_value=failed_events)

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.OutboxRepository",
                return_value=mock_repository,
            ),
        ):
            # Act
            summary = await processor.get_failed_events_summary()

        # Assert
        assert summary["failed_event_count"] == 1
        assert len(summary["failed_events"]) == 1
        assert summary["failed_events"][0]["event_id"] == "failed-1"
        assert summary["failed_events"][0]["retry_count"] == 5

    @pytest.mark.asyncio
    async def test_get_failed_events_summary_error(self, processor):
        """Test getting failed events summary when there's a database error."""

        # Arrange
        class FailingBeginContext:
            async def __aenter__(self):
                raise Exception("Database error")

            async def __aexit__(self, exc_type, exc, tb):
                return None

        mock_engine = MagicMock()
        mock_engine.begin.return_value = FailingBeginContext()

        with patch(
            "app.infrastructure.events.outbox_processor.get_async_database_engine",
            return_value=mock_engine,
        ):
            # Act
            summary = await processor.get_failed_events_summary()

        # Assert
        assert summary["failed_event_count"] == 0
        assert summary["failed_events"] == []

    def test_get_outbox_processor_singleton(self):
        """Test that get_outbox_processor returns the same instance."""
        # Act
        processor1 = get_outbox_processor()
        processor2 = get_outbox_processor()

        # Assert
        assert processor1 is processor2

    @pytest.mark.asyncio
    async def test_run_outbox_processor_loop_cancellation(self):
        """Test that the processor loop handles cancellation correctly."""
        # Arrange
        mock_processor = MagicMock()
        mock_processor.process_events = AsyncMock()

        with patch(
            "app.infrastructure.events.outbox_processor.get_outbox_processor",
            return_value=mock_processor,
        ):
            # Create a task that we can cancel
            async def run_and_cancel():
                from app.infrastructure.events.outbox_processor import (
                    run_outbox_processor_loop,
                )

                task = asyncio.create_task(
                    run_outbox_processor_loop(interval_seconds=0.1)
                )
                await asyncio.sleep(0.05)  # Let it run briefly
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Act
            await run_and_cancel()

        # Assert
        # Should have called process_events at least once
        assert mock_processor.process_events.call_count >= 1

    @pytest.mark.asyncio
    async def test_process_contact_sync_event(self, processor, mock_search_indexer):
        """Test that contact.* events are routed to OutboxEventProcessor."""
        # Arrange
        contact_event = OutboxEvent(
            id=1,
            event_id="contact-event-1",
            event_type="contact.created",
            aggregate_id=42,
            event_data={
                "integration_source": "google",
                "external_id": "people/c123",
                "contact_data": {
                    "first_name": "Test",
                    "last_name": "User",
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                },
                "sync_timestamp": "2024-01-01T10:00:00Z",
                "sync_type": "created",
                "etag": "etag123",
            },
            occurred_at=datetime(2024, 1, 1, 10, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 10, 0, 0),
        )

        mock_conn = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        @asynccontextmanager
        async def mock_begin_nested():
            yield mock_conn

        mock_conn.begin_nested = mock_begin_nested

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin

        mock_repository = MagicMock()
        mock_repository.get_unprocessed_events = AsyncMock(return_value=[contact_event])
        mock_repository.mark_as_processed = AsyncMock()

        # Mock the OutboxEventProcessor
        mock_event_processor = AsyncMock()
        mock_event_processor.process_event = AsyncMock(
            return_value={"status": "success", "contact_id": 123}
        )

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.OutboxRepository",
                return_value=mock_repository,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.SearchIndexer",
                return_value=mock_search_indexer,
            ),
            patch(
                "app.core.integrations.outbox_event_processor.OutboxEventProcessor",
                return_value=mock_event_processor,
            ),
        ):
            # Act
            await processor.process_events()

        # Assert
        # Contact event should NOT be sent to search indexer
        mock_search_indexer.process_event.assert_not_called()

        # Contact event SHOULD be sent to OutboxEventProcessor
        mock_event_processor.process_event.assert_called_once_with(contact_event)

        # Event should be marked as processed
        mock_repository.mark_as_processed.assert_called_once_with("contact-event-1")

    @pytest.mark.asyncio
    async def test_process_mixed_events(self, processor, mock_search_indexer):
        """Test processing a mix of contact and non-contact events."""
        # Arrange
        events = [
            OutboxEvent(
                id=1,
                event_id="contact-event",
                event_type="contact.created",
                aggregate_id=42,
                event_data={
                    "integration_source": "google",
                    "external_id": "people/c123",
                    "contact_data": {},
                    "sync_timestamp": "2024-01-01T10:00:00Z",
                    "sync_type": "created",
                },
                occurred_at=datetime(2024, 1, 1, 10, 0, 0),
                processed_at=None,
                retry_count=0,
                created_at=datetime(2024, 1, 1, 10, 0, 0),
            ),
            OutboxEvent(
                id=2,
                event_id="search-event",
                event_type="ContactCreated",
                aggregate_id=43,
                event_data={"contact_id": 43, "name": "Jane"},
                occurred_at=datetime(2024, 1, 1, 12, 5, 0),
                processed_at=None,
                retry_count=0,
                created_at=datetime(2024, 1, 1, 12, 5, 0),
            ),
        ]

        mock_conn = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        @asynccontextmanager
        async def mock_begin_nested():
            yield mock_conn

        mock_conn.begin_nested = mock_begin_nested

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin

        mock_repository = MagicMock()
        mock_repository.get_unprocessed_events = AsyncMock(return_value=events)
        mock_repository.mark_as_processed = AsyncMock()

        # Mock the OutboxEventProcessor
        mock_event_processor = AsyncMock()
        mock_event_processor.process_event = AsyncMock(
            return_value={"status": "success", "contact_id": 123}
        )

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.OutboxRepository",
                return_value=mock_repository,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.SearchIndexer",
                return_value=mock_search_indexer,
            ),
            patch(
                "app.core.integrations.outbox_event_processor.OutboxEventProcessor",
                return_value=mock_event_processor,
            ),
        ):
            # Act
            await processor.process_events()

        # Assert
        # Contact event should go to OutboxEventProcessor
        mock_event_processor.process_event.assert_called_once_with(events[0])

        # Non-contact event should go to SearchIndexer
        mock_search_indexer.process_event.assert_called_once_with(events[1])

        # Both events should be marked as processed
        assert mock_repository.mark_as_processed.call_count == 2
        mock_repository.mark_as_processed.assert_any_call("contact-event")
        mock_repository.mark_as_processed.assert_any_call("search-event")

    @pytest.mark.asyncio
    async def test_process_journal_events(self, processor, mock_search_indexer):
        """Test processing journal events routes to TaskQueueService."""
        # Arrange
        events = [
            OutboxEvent(
                id=1,
                event_id="journal-event",
                event_type="JournalUpdated",
                aggregate_id=42,
                event_data={"id": "j1", "changed_fields": ["title"]},
                occurred_at=datetime(2024, 1, 1, 10, 0, 0),
                processed_at=None,
                retry_count=0,
                created_at=datetime(2024, 1, 1, 10, 0, 0),
            )
        ]

        mock_conn = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        @asynccontextmanager
        async def mock_begin_nested():
            yield mock_conn

        mock_conn.begin_nested = mock_begin_nested

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin

        mock_repository = MagicMock()
        mock_repository.get_unprocessed_events = AsyncMock(return_value=events)
        mock_repository.mark_as_processed = AsyncMock()

        mock_task_queue_service = AsyncMock()
        mock_task_queue_service.broadcast_journal_event = AsyncMock()
        mock_task_queue_service.close = AsyncMock()

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.OutboxRepository",
                return_value=mock_repository,
            ),
            patch(
                "app.infrastructure.events.outbox_processor.SearchIndexer",
                return_value=mock_search_indexer,
            ),
            patch(
                "app.core.integrations.task_queue_service.TaskQueueService",
                return_value=mock_task_queue_service,
            ),
            patch("app.infrastructure.config.get_settings"),
            patch("app.core.integrations.task_queue.get_redis_settings"),
            patch("app.core.integrations.database.get_database_manager"),
        ):
            # Act
            await processor.process_events()

        # Assert
        # Journal event should go to TaskQueueService AND SearchIndexer
        mock_task_queue_service.broadcast_journal_event.assert_called_once_with(
            "JournalUpdated", {"id": "j1", "changed_fields": ["title"]}
        )
        mock_task_queue_service.close.assert_called_once()
        mock_search_indexer.process_event.assert_called_once_with(events[0])

        assert mock_repository.mark_as_processed.call_count == 1
        mock_repository.mark_as_processed.assert_called_once_with("journal-event")

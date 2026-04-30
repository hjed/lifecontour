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
    def mock_task_queue_service(self):
        """Create a mock TaskQueueService."""
        service = AsyncMock()
        return service

    @pytest.fixture
    def mock_container(self, mock_task_queue_service):
        """Create a mock dishka container."""
        container = MagicMock()

        class MockContext:
            async def __aenter__(self):
                return container

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass  # Mock implementation for context manager

        container.return_value = MockContext()
        container.get = AsyncMock(return_value=mock_task_queue_service)
        return container

    @pytest.fixture
    def processor(self, mock_search_indexer, mock_container):
        """Create an OutboxProcessor instance with mock dependencies."""
        with patch(
            "app.infrastructure.events.outbox_processor.SearchIndexer",
            return_value=mock_search_indexer,
        ):
            return OutboxProcessor(mock_container)

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

    @pytest.mark.asyncio
    async def test_run_outbox_processor_loop_cancellation(self):
        """Test that the processor loop handles cancellation correctly."""
        # Arrange
        mock_processor = MagicMock()
        mock_processor.process_events = AsyncMock()

        # Create a task that we can cancel
        async def run_and_cancel():
            from app.infrastructure.events.outbox_processor import (
                run_outbox_processor_loop,
            )

            mock_container = MagicMock()
            mock_container.get = AsyncMock(return_value=mock_processor)
            task = asyncio.create_task(
                run_outbox_processor_loop(mock_container, interval_seconds=0.1)
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
    async def test_process_journal_events(
        self, processor, mock_search_indexer, mock_task_queue_service
    ):
        """Test processing journal events routes to TaskQueueService."""
        # Arrange
        events = [
            OutboxEvent(
                id=1,
                event_id="journal-event",
                event_type="JournalUpdated",
                aggregate_id=42,
                event_data={
                    "journal_id": 1,
                    "changed_fields": {"title": ("Old", "New")},
                },
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
                "_invalidate_daily_summary_for_journal_event",
                new_callable=AsyncMock,
            ),
        ):
            # Act
            await processor.process_events()

        # Assert
        # Journal event should go to TaskQueueService AND SearchIndexer
        mock_task_queue_service.broadcast_journal_event.assert_called_once_with(
            "JournalUpdated",
            {"journal_id": 1, "changed_fields": {"title": ("Old", "New")}},
        )
        mock_search_indexer.process_event.assert_called_once_with(events[0])

        assert mock_repository.mark_as_processed.call_count == 1
        mock_repository.mark_as_processed.assert_called_once_with("journal-event")

    @pytest.mark.asyncio
    async def test_process_journal_review_detect_matches(
        self, processor, mock_search_indexer
    ):
        """Test processing journal_review.detect_matches events route to _process_journal_sync_event."""
        # Arrange
        events = [
            OutboxEvent(
                id=1,
                event_id="journal-review-event",
                event_type="journal_review.detect_matches",
                aggregate_id=42,
                event_data={
                    "journal_id": 1,
                    "user_id": "user123",
                    "journal_title": "Test Journal",
                    "event_date_range_start": "2024-01-01T10:00:00Z",
                    "event_date_range_end": "2024-01-01T11:00:00Z",
                },
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
                "_process_journal_sync_event",
                new_callable=AsyncMock,
            ) as mock_process_journal_sync_event,
        ):
            # Act
            await processor.process_events()

        # Assert
        # Should not go to SearchIndexer
        mock_search_indexer.process_event.assert_not_called()

        # Should go to _process_journal_sync_event
        mock_process_journal_sync_event.assert_called_once_with(
            events[0], mock_search_indexer.db_connection
        )

        # Ensure marked as processed
        mock_repository.mark_as_processed.assert_called_once_with(
            "journal-review-event"
        )


class TestOutboxProcessorStreamConsumerGating:
    """Tests for feature flag gating when USE_STREAM_CONSUMERS is enabled."""

    @pytest.fixture
    def mock_search_indexer(self):
        """Create a mock search indexer."""
        indexer = MagicMock()
        indexer.process_event = AsyncMock()
        indexer.db_connection = MagicMock()
        return indexer

    @pytest.fixture
    def mock_task_queue_service(self):
        """Create a mock TaskQueueService."""
        service = AsyncMock()
        return service

    @pytest.fixture
    def mock_container(self, mock_task_queue_service):
        """Create a mock dishka container."""
        container = MagicMock()

        class MockContext:
            async def __aenter__(self):
                return container

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                # Intentionally empty: mock context manager requires no cleanup
                pass

        container.return_value = MockContext()
        container.get = AsyncMock(return_value=mock_task_queue_service)
        return container

    @pytest.fixture
    def processor(self, mock_search_indexer, mock_container):
        """Create an OutboxProcessor instance with mock dependencies."""
        with patch(
            "app.infrastructure.events.outbox_processor.SearchIndexer",
            return_value=mock_search_indexer,
        ):
            return OutboxProcessor(mock_container)

    @pytest.mark.asyncio
    async def test_skips_search_indexing_when_stream_consumers_enabled(
        self, processor, mock_search_indexer
    ):
        """With USE_STREAM_CONSUMERS=true, SearchIndexer.process_event should NOT be called."""
        contact_event = OutboxEvent(
            id=1,
            event_id="event-1",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42, "name": "John"},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        mock_repository = MagicMock()
        mock_repository.mark_as_processed = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.use_stream_consumers = True

        with patch(
            "app.infrastructure.events.outbox_processor.get_settings",
            return_value=mock_settings,
        ):
            await processor._process_single_event(
                contact_event, mock_repository, mock_search_indexer
            )

        # Search indexer should NOT be called — stream consumer handles it
        mock_search_indexer.process_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_summary_generation_when_stream_consumers_enabled(
        self, processor, mock_search_indexer
    ):
        """With USE_STREAM_CONSUMERS=true, _process_summary_generation_event should NOT be called."""
        summary_event = OutboxEvent(
            id=1,
            event_id="event-summary-1",
            event_type="ContactSummaryRefreshRequested",
            aggregate_id=42,
            event_data={"contact_id": 42},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        mock_repository = MagicMock()
        mock_repository.mark_as_processed = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.use_stream_consumers = True

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_settings",
                return_value=mock_settings,
            ),
            patch.object(
                processor,
                "_process_summary_generation_event",
                new_callable=AsyncMock,
            ) as mock_summary,
        ):
            await processor._process_single_event(
                summary_event, mock_repository, mock_search_indexer
            )

        # Summary generation and search indexer should NOT be called
        mock_summary.assert_not_called()
        mock_search_indexer.process_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_daily_summary_invalidation_when_stream_consumers_enabled(
        self, processor, mock_search_indexer, mock_task_queue_service
    ):
        """With USE_STREAM_CONSUMERS=true, daily summary invalidation should be skipped."""
        journal_event = OutboxEvent(
            id=1,
            event_id="event-journal-1",
            event_type="JournalCreated",
            aggregate_id=42,
            event_data={"journal_id": 42},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        mock_repository = MagicMock()
        mock_repository.mark_as_processed = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.use_stream_consumers = True

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_settings",
                return_value=mock_settings,
            ),
            patch.object(
                processor,
                "_invalidate_daily_summary_for_journal_event",
                new_callable=AsyncMock,
            ) as mock_invalidate,
        ):
            await processor._process_single_event(
                journal_event, mock_repository, mock_search_indexer
            )

        # Daily summary invalidation should NOT be called
        mock_invalidate.assert_not_called()
        # Search indexer should NOT be called
        mock_search_indexer.process_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_contact_sync_when_stream_consumers_enabled(
        self, processor, mock_search_indexer
    ):
        """With USE_STREAM_CONSUMERS=true, contact.* sync events should be skipped."""
        contact_sync_event = OutboxEvent(
            id=1,
            event_id="contact-sync-1",
            event_type="contact.created",
            aggregate_id=42,
            event_data={
                "integration_source": "google",
                "external_id": "people/c123",
                "contact_data": {"first_name": "Test"},
                "sync_timestamp": "2024-01-01T10:00:00Z",
                "sync_type": "created",
            },
            occurred_at=datetime(2024, 1, 1, 10, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 10, 0, 0),
        )
        mock_repository = MagicMock()
        mock_repository.mark_as_processed = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.use_stream_consumers = True

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_settings",
                return_value=mock_settings,
            ),
            patch.object(
                processor,
                "_process_contact_event",
                new_callable=AsyncMock,
            ) as mock_contact,
        ):
            await processor._process_single_event(
                contact_sync_event, mock_repository, mock_search_indexer
            )

        # Contact sync should NOT run — stream consumer handles it
        mock_contact.assert_not_called()
        # Event should still be marked as processed
        mock_repository.mark_as_processed.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_journal_sync_when_stream_consumers_enabled(
        self, processor, mock_search_indexer
    ):
        """With USE_STREAM_CONSUMERS=true, journal_event.* sync events should be skipped."""
        journal_sync_event = OutboxEvent(
            id=1,
            event_id="journal-sync-1",
            event_type="journal_event.created",
            aggregate_id=42,
            event_data={
                "journal_id": 1,
                "user_id": "user123",
                "title": "Test Journal",
            },
            occurred_at=datetime(2024, 1, 1, 10, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 10, 0, 0),
        )
        mock_repository = MagicMock()
        mock_repository.mark_as_processed = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.use_stream_consumers = True

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_settings",
                return_value=mock_settings,
            ),
            patch.object(
                processor,
                "_process_journal_sync_event",
                new_callable=AsyncMock,
            ) as mock_journal_sync,
        ):
            await processor._process_single_event(
                journal_sync_event, mock_repository, mock_search_indexer
            )

        # Journal sync should NOT run — stream consumer handles it
        mock_journal_sync.assert_not_called()
        mock_repository.mark_as_processed.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_journal_broadcast_when_stream_consumers_enabled(
        self, processor, mock_search_indexer, mock_task_queue_service
    ):
        """With USE_STREAM_CONSUMERS=true, ARQ journal broadcast should be skipped."""
        journal_event = OutboxEvent(
            id=1,
            event_id="journal-broadcast-1",
            event_type="JournalUpdated",
            aggregate_id=42,
            event_data={"journal_id": 42, "changed_fields": {}},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        mock_repository = MagicMock()
        mock_repository.mark_as_processed = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.use_stream_consumers = True

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_settings",
                return_value=mock_settings,
            ),
            patch.object(
                processor,
                "_process_journal_event",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await processor._process_single_event(
                journal_event, mock_repository, mock_search_indexer
            )

        # ARQ broadcast should NOT run — stream consumer handles it
        mock_broadcast.assert_not_called()
        mock_repository.mark_as_processed.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_tag_broadcast_when_stream_consumers_enabled(
        self, processor, mock_search_indexer, mock_task_queue_service
    ):
        """With USE_STREAM_CONSUMERS=true, ARQ tag broadcast should be skipped."""
        tag_event = OutboxEvent(
            id=1,
            event_id="tag-broadcast-1",
            event_type="TagUpdated",
            aggregate_id=10,
            event_data={"tag_id": 10, "name": "Updated Tag"},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        mock_repository = MagicMock()
        mock_repository.mark_as_processed = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.use_stream_consumers = True

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_settings",
                return_value=mock_settings,
            ),
            patch.object(
                processor,
                "_process_tag_event",
                new_callable=AsyncMock,
            ) as mock_tag_broadcast,
        ):
            await processor._process_single_event(
                tag_event, mock_repository, mock_search_indexer
            )

        # Tag broadcast should NOT run — stream consumer handles it
        mock_tag_broadcast.assert_not_called()
        mock_repository.mark_as_processed.assert_called_once()

    @pytest.mark.asyncio
    async def test_still_processes_all_events_when_stream_consumers_disabled(
        self, processor, mock_search_indexer, mock_task_queue_service
    ):
        """With USE_STREAM_CONSUMERS=false, all processing should run normally (regression)."""
        contact_event = OutboxEvent(
            id=1,
            event_id="contact-sync-1",
            event_type="contact.created",
            aggregate_id=42,
            event_data={
                "integration_source": "google",
                "external_id": "people/c123",
                "contact_data": {"first_name": "Test"},
                "sync_timestamp": "2024-01-01T10:00:00Z",
                "sync_type": "created",
            },
            occurred_at=datetime(2024, 1, 1, 10, 0, 0),
            processed_at=None,
            retry_count=0,
            created_at=datetime(2024, 1, 1, 10, 0, 0),
        )
        mock_repository = MagicMock()
        mock_repository.mark_as_processed = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.use_stream_consumers = False

        with (
            patch(
                "app.infrastructure.events.outbox_processor.get_settings",
                return_value=mock_settings,
            ),
            patch.object(
                processor,
                "_process_contact_event",
                new_callable=AsyncMock,
            ) as mock_contact,
        ):
            await processor._process_single_event(
                contact_event, mock_repository, mock_search_indexer
            )

        # Contact sync should still run when flag is off
        mock_contact.assert_called_once()

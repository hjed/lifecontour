"""
Unit tests for OutboxProcessor.

Tests the background processor that handles outbox events and sends them to external systems.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

        # First event should have retry count incremented
        mock_repository.increment_retry_count.assert_called_once_with("event-1")

        # Second event should be marked as processed
        mock_repository.mark_as_processed.assert_called_once_with("event-2")

    @pytest.mark.asyncio
    async def test_process_events_max_retries_exceeded(
        self, processor, mock_search_indexer
    ):
        """Test processing events that have exceeded max retries."""
        # Arrange
        failed_event = OutboxEvent(
            id=3,
            event_id="failed-event",
            event_type="ContactCreated",
            aggregate_id=99,
            event_data={"contact_id": 99},
            occurred_at=datetime(2024, 1, 1, 10, 0, 0),
            processed_at=None,
            retry_count=3,  # Equals max_retries
            created_at=datetime(2024, 1, 1, 10, 0, 0),
        )

        mock_conn = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin

        mock_repository = MagicMock()
        mock_repository.get_unprocessed_events = AsyncMock(return_value=[failed_event])
        mock_repository.increment_retry_count = AsyncMock()

        mock_search_indexer.process_event.side_effect = Exception("Still failing")

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
        # Should not increment retry count when max retries exceeded
        mock_repository.increment_retry_count.assert_not_called()

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
        @asynccontextmanager
        async def mock_begin_error():
            raise Exception("Database error")

        mock_engine = AsyncMock()
        mock_engine.begin = mock_begin_error

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

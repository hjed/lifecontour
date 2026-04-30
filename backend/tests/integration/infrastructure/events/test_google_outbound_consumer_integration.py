"""
Integration tests for GoogleOutboundConsumer.

Tests the end-to-end flow: Redis stream -> consumer -> TaskQueueService broadcast.
Validates that events flow correctly from Redis Streams through the consumer
and that the appropriate TaskQueueService broadcast method is invoked.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis

from app.infrastructure.events.google_outbound_consumer import GoogleOutboundConsumer

GROUP_NAME = "google-worker"


class TestGoogleOutboundConsumerIntegration:
    """Integration tests for GoogleOutboundConsumer with real Redis."""

    @pytest.fixture
    def mock_task_queue_service(self) -> AsyncMock:
        """Create a mock TaskQueueService."""
        service = AsyncMock()
        service.broadcast_journal_event = AsyncMock(return_value="job-123")
        service.broadcast_tag_event = AsyncMock(return_value="job-456")
        return service

    @pytest.fixture
    def mock_container(self, mock_task_queue_service: AsyncMock) -> MagicMock:
        """Create a mock Dishka AsyncContainer that provides TaskQueueService."""
        container = MagicMock()

        class MockContext:
            async def __aenter__(self):
                return container

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass  # Mock implementation for context manager

        container.return_value = MockContext()
        container.get = AsyncMock(return_value=mock_task_queue_service)
        return container

    @pytest.mark.asyncio
    async def test_consumer_broadcasts_journal_created_event(
        self,
        test_stream_name: str,
        stream_client: StreamClient,
        redis_client: Redis,
        mock_container: MagicMock,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify the consumer reads a JournalCreated event and broadcasts it."""
        event_data = {"journal_id": 42, "title": "Test Journal"}
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="JournalCreated",
            aggregate_id=42,
            event_data=event_data,
            occurred_at="2024-01-01T12:00:00Z",
        )

        consumer = GoogleOutboundConsumer(
            stream_client=stream_client,
            container=mock_container,
            stream_name=test_stream_name,
            consumer_name="test-outbound-1",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        count = await consumer._process_batch()

        assert count == 1

        # Verify pending entries are 0 (all acknowledged)
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

        # Verify TaskQueueService.broadcast_journal_event was called
        mock_task_queue_service.broadcast_journal_event.assert_called_once_with(
            "JournalCreated", event_data
        )

    @pytest.mark.asyncio
    async def test_consumer_broadcasts_tag_updated_event(
        self,
        test_stream_name: str,
        stream_client: StreamClient,
        redis_client: Redis,
        mock_container: MagicMock,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify the consumer reads a TagUpdated event and broadcasts it."""
        event_data = {"tag_id": 10, "name": "Updated Tag"}
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="TagUpdated",
            aggregate_id=10,
            event_data=event_data,
            occurred_at="2024-01-01T12:00:00Z",
        )

        consumer = GoogleOutboundConsumer(
            stream_client=stream_client,
            container=mock_container,
            stream_name=test_stream_name,
            consumer_name="test-outbound-tag",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        count = await consumer._process_batch()

        assert count == 1
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

        mock_task_queue_service.broadcast_tag_event.assert_called_once_with(
            "TagUpdated", event_data
        )

    @pytest.mark.asyncio
    async def test_consumer_acknowledges_irrelevant_events(
        self,
        test_stream_name: str,
        stream_client: StreamClient,
        redis_client: Redis,
        mock_container: MagicMock,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify the consumer acknowledges and skips events it shouldn't process."""
        # Publish an irrelevant event (contact sync, not a domain event)
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="contact.created",
            aggregate_id=1,
            event_data={"contact_id": 1},
            occurred_at="2024-01-01T12:00:00Z",
        )

        consumer = GoogleOutboundConsumer(
            stream_client=stream_client,
            container=mock_container,
            stream_name=test_stream_name,
            consumer_name="test-outbound-skip",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        count = await consumer._process_batch()

        assert count == 1
        # No broadcast should have happened
        mock_task_queue_service.broadcast_journal_event.assert_not_called()
        mock_task_queue_service.broadcast_tag_event.assert_not_called()

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

"""
Unit tests for GoogleOutboundConsumer.

Tests event routing, filtering, and the _handle_event integration with
TaskQueueService for the google-worker consumer group.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.stream_client import StreamClient, StreamEvent

from app.infrastructure.events.google_outbound_consumer import GoogleOutboundConsumer


def _make_stream_event(
    event_type: str = "JournalCreated",
    event_data: dict[str, Any] | None = None,
    aggregate_id: int = 42,
) -> StreamEvent:
    """Create a StreamEvent for testing."""
    return StreamEvent(
        message_id="1234567890-0",
        event_id="evt-test-456",
        event_type=event_type,
        aggregate_id=aggregate_id,
        event_data=event_data or {"journal_id": 42},
        occurred_at="2024-06-15T10:30:00+00:00",
    )


class TestGoogleOutboundConsumerEventMatching:
    """Test event type pattern matching for the Google outbound consumer."""

    @pytest.fixture
    def consumer(self) -> GoogleOutboundConsumer:
        """Create a GoogleOutboundConsumer with a mock stream client."""
        mock_client = MagicMock(spec=StreamClient)
        mock_container = MagicMock()
        return GoogleOutboundConsumer(
            stream_client=mock_client,
            container=mock_container,
            stream_name="pms:domain-events",
        )

    @pytest.mark.parametrize(
        "event_type",
        [
            "JournalCreated",
            "JournalUpdated",
            "JournalDeleted",
        ],
    )
    def test_matches_journal_domain_events(
        self, consumer: GoogleOutboundConsumer, event_type: str
    ) -> None:
        """Verify journal domain events are matched for Google outbound broadcast."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "TagUpdated",
            "TagDeleted",
        ],
    )
    def test_matches_tag_domain_events(
        self, consumer: GoogleOutboundConsumer, event_type: str
    ) -> None:
        """Verify tag domain events are matched for Google outbound broadcast."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            # Inbound sync events — handled by InboundEventConsumer
            "contact.created",
            "contact.updated",
            "contact.deleted",
            "journal_event.created",
            "journal_event.updated",
            "journal_review.detect_matches",
            # Search/summary events — handled by other consumers
            "ContactCreated",
            "ContactUpdated",
            "ContactDeleted",
            "ContactSummaryRefreshRequested",
            "TagAssigned",
            "TagRemoved",
            "ImportantDateAdded",
            "ImportantDateDeleted",
            # Unknown events
            "SomethingElse",
            "route.created",
        ],
    )
    def test_skips_non_matching_events(
        self, consumer: GoogleOutboundConsumer, event_type: str
    ) -> None:
        """Verify inbound, search, and unknown events are not matched."""
        assert consumer._matches_event_type(event_type) is False


class TestGoogleOutboundConsumerHandleEvent:
    """Test the _handle_event implementation.

    Uses shared fixtures from conftest.py for mock_stream_client.
    """

    @pytest.fixture
    def mock_task_queue_service(self) -> AsyncMock:
        """Create a mock TaskQueueService."""
        service = AsyncMock()
        service.broadcast_journal_event = AsyncMock(return_value="job-123")
        service.broadcast_tag_event = AsyncMock(return_value="job-456")
        return service

    @pytest.fixture
    def mock_container(self, mock_task_queue_service: AsyncMock) -> MagicMock:
        """Create a mock Dishka AsyncContainer."""
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
    def consumer(
        self, mock_stream_client: MagicMock, mock_container: MagicMock
    ) -> GoogleOutboundConsumer:
        """Create a GoogleOutboundConsumer with mocks."""
        return GoogleOutboundConsumer(
            stream_client=mock_stream_client,
            container=mock_container,
            stream_name="pms:domain-events",
        )

    @pytest.mark.asyncio
    async def test_journal_created_broadcasts_via_task_queue(
        self,
        consumer: GoogleOutboundConsumer,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify JournalCreated events call TaskQueueService.broadcast_journal_event."""
        event_data = {"journal_id": 1, "title": "New Journal"}
        event = _make_stream_event(
            event_type="JournalCreated",
            event_data=event_data,
        )

        await consumer._handle_event(event)

        mock_task_queue_service.broadcast_journal_event.assert_called_once_with(
            "JournalCreated", event_data
        )

    @pytest.mark.asyncio
    async def test_journal_updated_broadcasts_via_task_queue(
        self,
        consumer: GoogleOutboundConsumer,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify JournalUpdated events call TaskQueueService.broadcast_journal_event."""
        event_data = {"journal_id": 2, "changed_fields": {"title": ("Old", "New")}}
        event = _make_stream_event(
            event_type="JournalUpdated",
            event_data=event_data,
        )

        await consumer._handle_event(event)

        mock_task_queue_service.broadcast_journal_event.assert_called_once_with(
            "JournalUpdated", event_data
        )

    @pytest.mark.asyncio
    async def test_journal_deleted_broadcasts_via_task_queue(
        self,
        consumer: GoogleOutboundConsumer,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify JournalDeleted events call TaskQueueService.broadcast_journal_event."""
        event_data = {"journal_id": 3, "user_id": "user123"}
        event = _make_stream_event(
            event_type="JournalDeleted",
            event_data=event_data,
        )

        await consumer._handle_event(event)

        mock_task_queue_service.broadcast_journal_event.assert_called_once_with(
            "JournalDeleted", event_data
        )

    @pytest.mark.asyncio
    async def test_tag_updated_broadcasts_via_task_queue(
        self,
        consumer: GoogleOutboundConsumer,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify TagUpdated events call TaskQueueService.broadcast_tag_event."""
        event_data = {"tag_id": 10, "name": "Updated Tag"}
        event = _make_stream_event(
            event_type="TagUpdated",
            event_data=event_data,
        )

        await consumer._handle_event(event)

        mock_task_queue_service.broadcast_tag_event.assert_called_once_with(
            "TagUpdated", event_data
        )

    @pytest.mark.asyncio
    async def test_tag_deleted_broadcasts_via_task_queue(
        self,
        consumer: GoogleOutboundConsumer,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify TagDeleted events call TaskQueueService.broadcast_tag_event."""
        event_data = {"tag_id": 11}
        event = _make_stream_event(
            event_type="TagDeleted",
            event_data=event_data,
        )

        await consumer._handle_event(event)

        mock_task_queue_service.broadcast_tag_event.assert_called_once_with(
            "TagDeleted", event_data
        )

    @pytest.mark.asyncio
    async def test_container_creates_request_scope(
        self,
        consumer: GoogleOutboundConsumer,
        mock_container: MagicMock,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify the container is called to create a request scope for DI."""
        event = _make_stream_event(
            event_type="JournalCreated",
            event_data={"journal_id": 1},
        )

        await consumer._handle_event(event)

        # Container should have been used to get TaskQueueService
        mock_container.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_error_propagates(
        self,
        consumer: GoogleOutboundConsumer,
        mock_task_queue_service: AsyncMock,
    ) -> None:
        """Verify errors in broadcasting propagate (event left pending for retry)."""
        mock_task_queue_service.broadcast_journal_event.side_effect = Exception(
            "ARQ broadcast failed"
        )

        event = _make_stream_event(
            event_type="JournalCreated",
            event_data={"journal_id": 1},
        )

        with pytest.raises(Exception, match="ARQ broadcast failed"):
            await consumer._handle_event(event)

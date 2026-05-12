"""Unit tests for GoogleWorkerStreamConsumer.

Tests event routing from the Redis Stream consumer to the
process_journal_event and process_tag_event worker functions.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient, StreamEvent


def _make_stream_event(
    event_type: str = "JournalCreated",
    event_data: dict[str, Any] | None = None,
    event_id: str = "evt-test-456",
    aggregate_id: int = 42,
) -> StreamEvent:
    """Create a StreamEvent for testing."""
    return StreamEvent(
        message_id="1234567890-0",
        event_id=event_id,
        event_type=event_type,
        aggregate_id=aggregate_id,
        event_data=event_data or {"journal_id": 42},
        occurred_at="2024-06-15T10:30:00+00:00",
    )


class TestGoogleWorkerStreamConsumerEventMatching:
    """Test event type pattern matching for the Google worker stream consumer."""

    @pytest.fixture
    def consumer(self) -> Any:
        """Create a GoogleWorkerStreamConsumer with a mock stream client."""
        from stream_consumer_tasks import GoogleWorkerStreamConsumer

        mock_client = MagicMock(spec=StreamClient)
        mock_session_factory = MagicMock()
        return GoogleWorkerStreamConsumer(
            stream_client=mock_client,
            session_factory=mock_session_factory,
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
        self, consumer: Any, event_type: str
    ) -> None:
        """Verify journal domain events are matched."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "TagUpdated",
            "TagDeleted",
        ],
    )
    def test_matches_tag_domain_events(self, consumer: Any, event_type: str) -> None:
        """Verify tag domain events are matched."""
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
    def test_skips_non_matching_events(self, consumer: Any, event_type: str) -> None:
        """Verify inbound, search, and unknown events are not matched."""
        assert consumer._matches_event_type(event_type) is False


class TestGoogleWorkerStreamConsumerHandleEvent:
    """Test the _handle_event implementation routing to worker functions."""

    @pytest.fixture
    def mock_session_factory(self) -> MagicMock:
        """Create a mock session factory."""
        return MagicMock()

    @pytest.fixture
    def consumer(self, mock_session_factory: MagicMock) -> Any:
        """Create a GoogleWorkerStreamConsumer with mocks."""
        from stream_consumer_tasks import GoogleWorkerStreamConsumer

        mock_client = MagicMock(spec=StreamClient)
        return GoogleWorkerStreamConsumer(
            stream_client=mock_client,
            session_factory=mock_session_factory,
            stream_name="pms:domain-events",
        )

    @pytest.mark.asyncio
    async def test_routes_journal_created_to_process_journal_event(
        self,
        consumer: Any,
    ) -> None:
        """Verify JournalCreated events route to process_journal_event."""
        event_data = {"journal_id": 1, "title": "New Journal"}
        event = _make_stream_event(
            event_type="JournalCreated",
            event_data=event_data,
        )

        with patch(
            "stream_consumer_tasks.process_journal_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            mock_fn.assert_called_once()
            call_args = mock_fn.call_args
            assert call_args[1]["event_type"] == "JournalCreated"
            assert call_args[1]["event_data"] == event_data

    @pytest.mark.asyncio
    async def test_routes_journal_updated_to_process_journal_event(
        self,
        consumer: Any,
    ) -> None:
        """Verify JournalUpdated events route to process_journal_event."""
        event_data = {"journal_id": 2, "changed_fields": {"title": ("Old", "New")}}
        event = _make_stream_event(
            event_type="JournalUpdated",
            event_data=event_data,
        )

        with patch(
            "stream_consumer_tasks.process_journal_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            mock_fn.assert_called_once()
            call_args = mock_fn.call_args
            assert call_args[1]["event_type"] == "JournalUpdated"
            assert call_args[1]["event_data"] == event_data

    @pytest.mark.asyncio
    async def test_routes_journal_deleted_to_process_journal_event(
        self,
        consumer: Any,
    ) -> None:
        """Verify JournalDeleted events route to process_journal_event."""
        event_data = {"journal_id": 3, "user_id": "user123"}
        event = _make_stream_event(
            event_type="JournalDeleted",
            event_data=event_data,
        )

        with patch(
            "stream_consumer_tasks.process_journal_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            mock_fn.assert_called_once()
            call_args = mock_fn.call_args
            assert call_args[1]["event_type"] == "JournalDeleted"
            assert call_args[1]["event_data"] == event_data

    @pytest.mark.asyncio
    async def test_routes_tag_updated_to_process_tag_event(
        self,
        consumer: Any,
    ) -> None:
        """Verify TagUpdated events route to process_tag_event."""
        event_data = {"tag_id": 10, "name": "Updated Tag"}
        event = _make_stream_event(
            event_type="TagUpdated",
            event_data=event_data,
        )

        with patch(
            "stream_consumer_tasks.process_tag_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            mock_fn.assert_called_once()
            call_args = mock_fn.call_args
            assert call_args[1]["event_type"] == "TagUpdated"
            assert call_args[1]["event_data"] == event_data

    @pytest.mark.asyncio
    async def test_routes_tag_deleted_to_process_tag_event(
        self,
        consumer: Any,
    ) -> None:
        """Verify TagDeleted events route to process_tag_event."""
        event_data = {"tag_id": 11}
        event = _make_stream_event(
            event_type="TagDeleted",
            event_data=event_data,
        )

        with patch(
            "stream_consumer_tasks.process_tag_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            mock_fn.assert_called_once()
            call_args = mock_fn.call_args
            assert call_args[1]["event_type"] == "TagDeleted"
            assert call_args[1]["event_data"] == event_data

    @pytest.mark.asyncio
    async def test_builds_ctx_with_session_factory_and_event_id(
        self,
        consumer: Any,
        mock_session_factory: MagicMock,
    ) -> None:
        """Verify the ctx dict is built with session_factory and event_id as job_id."""
        event = _make_stream_event(
            event_type="JournalCreated",
            event_data={"journal_id": 1},
            event_id="evt-unique-789",
        )

        with patch(
            "stream_consumer_tasks.process_journal_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            call_args = mock_fn.call_args
            ctx = call_args[1]["ctx"]
            assert ctx["session_factory"] is mock_session_factory
            assert ctx["job_id"] == "evt-unique-789"

    @pytest.mark.asyncio
    async def test_propagates_process_journal_event_exception(
        self,
        consumer: Any,
    ) -> None:
        """Verify exceptions from process_journal_event propagate for retry."""
        event = _make_stream_event(
            event_type="JournalCreated",
            event_data={"journal_id": 1},
        )

        with patch(
            "stream_consumer_tasks.process_journal_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.side_effect = Exception("Database connection failed")

            with pytest.raises(Exception, match="Database connection failed"):
                await consumer._handle_event(event)

    @pytest.mark.asyncio
    async def test_propagates_process_tag_event_exception(
        self,
        consumer: Any,
    ) -> None:
        """Verify exceptions from process_tag_event propagate for retry."""
        event = _make_stream_event(
            event_type="TagUpdated",
            event_data={"tag_id": 10},
        )

        with patch(
            "stream_consumer_tasks.process_tag_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.side_effect = Exception("Google API error")

            with pytest.raises(Exception, match="Google API error"):
                await consumer._handle_event(event)

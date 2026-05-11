"""Unit tests for GoogleWorkerStreamConsumer contact event routing.

Verifies that the stream consumer subscribes to ContactCreated,
ContactUpdated, and ContactDeleted domain events and routes them
to process_contact_event.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient, StreamEvent


def _make_stream_event(
    event_type: str = "ContactUpdated",
    event_data: dict[str, Any] | None = None,
    event_id: str = "evt-contact-test-001",
    aggregate_id: int = 42,
) -> StreamEvent:
    """Create a StreamEvent for testing."""
    return StreamEvent(
        message_id="1234567890-0",
        event_id=event_id,
        event_type=event_type,
        aggregate_id=aggregate_id,
        event_data=event_data or {"contact_id": 42},
        occurred_at="2024-06-15T10:30:00+00:00",
    )


class TestContactEventMatching:
    """Verify contact domain events are matched by the stream consumer."""

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
            "ContactCreated",
            "ContactUpdated",
            "ContactDeleted",
        ],
    )
    def test_matches_contact_domain_events(
        self, consumer: Any, event_type: str
    ) -> None:
        """Verify contact domain events are matched by the consumer."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            # Inbound sync events — handled by InboundEventConsumer
            "contact.created",
            "contact.updated",
            "contact.deleted",
            # Search/summary events — not handled by Google worker
            "ContactSummaryRefreshRequested",
            "TagAssigned",
            "TagRemoved",
            "ImportantDateAdded",
            "ImportantDateDeleted",
        ],
    )
    def test_still_skips_non_matching_events(
        self, consumer: Any, event_type: str
    ) -> None:
        """Verify inbound sync and search events are still not matched."""
        assert consumer._matches_event_type(event_type) is False


class TestContactEventRouting:
    """Verify contact events are routed to process_contact_event."""

    @pytest.fixture
    def mock_session_factory(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def consumer(self, mock_session_factory: MagicMock) -> Any:
        from stream_consumer_tasks import GoogleWorkerStreamConsumer

        mock_client = MagicMock(spec=StreamClient)
        return GoogleWorkerStreamConsumer(
            stream_client=mock_client,
            session_factory=mock_session_factory,
            stream_name="pms:domain-events",
        )

    @pytest.mark.asyncio
    async def test_routes_contact_created_to_process_contact_event(
        self,
        consumer: Any,
    ) -> None:
        """Verify ContactCreated events route to process_contact_event."""
        event_data = {"contact_id": 1, "first_name": "Jane", "last_name": "Doe"}
        event = _make_stream_event(
            event_type="ContactCreated",
            event_data=event_data,
        )

        with patch(
            "stream_consumer_tasks.process_contact_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            mock_fn.assert_called_once()
            call_args = mock_fn.call_args
            assert call_args[1]["event_type"] == "ContactCreated"
            assert call_args[1]["event_data"] == event_data

    @pytest.mark.asyncio
    async def test_routes_contact_updated_to_process_contact_event(
        self,
        consumer: Any,
    ) -> None:
        """Verify ContactUpdated events route to process_contact_event."""
        event_data = {
            "contact_id": 42,
            "changed_fields": {"nick_name": ("Old", "New")},
        }
        event = _make_stream_event(
            event_type="ContactUpdated",
            event_data=event_data,
        )

        with patch(
            "stream_consumer_tasks.process_contact_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            mock_fn.assert_called_once()
            call_args = mock_fn.call_args
            assert call_args[1]["event_type"] == "ContactUpdated"
            assert call_args[1]["event_data"] == event_data

    @pytest.mark.asyncio
    async def test_routes_contact_deleted_to_process_contact_event(
        self,
        consumer: Any,
    ) -> None:
        """Verify ContactDeleted events route to process_contact_event."""
        event_data = {"contact_id": 42}
        event = _make_stream_event(
            event_type="ContactDeleted",
            event_data=event_data,
        )

        with patch(
            "stream_consumer_tasks.process_contact_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            mock_fn.assert_called_once()
            call_args = mock_fn.call_args
            assert call_args[1]["event_type"] == "ContactDeleted"
            assert call_args[1]["event_data"] == event_data

    @pytest.mark.asyncio
    async def test_builds_ctx_with_session_factory_for_contact_event(
        self,
        consumer: Any,
        mock_session_factory: MagicMock,
    ) -> None:
        """Verify the ctx dict is built correctly for contact events."""
        event = _make_stream_event(
            event_type="ContactUpdated",
            event_data={"contact_id": 1},
            event_id="evt-unique-contact-789",
        )

        with patch(
            "stream_consumer_tasks.process_contact_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.return_value = {"status": "success"}
            await consumer._handle_event(event)

            call_args = mock_fn.call_args
            ctx = call_args[1]["ctx"]
            assert ctx["session_factory"] is mock_session_factory
            assert ctx["job_id"] == "evt-unique-contact-789"

    @pytest.mark.asyncio
    async def test_propagates_process_contact_event_exception(
        self,
        consumer: Any,
    ) -> None:
        """Verify exceptions from process_contact_event propagate for retry."""
        event = _make_stream_event(
            event_type="ContactCreated",
            event_data={"contact_id": 1},
        )

        with patch(
            "stream_consumer_tasks.process_contact_event", new_callable=AsyncMock
        ) as mock_fn:
            mock_fn.side_effect = Exception("Database connection failed")

            with pytest.raises(Exception, match="Database connection failed"):
                await consumer._handle_event(event)

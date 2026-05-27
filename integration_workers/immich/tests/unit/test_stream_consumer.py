"""Unit tests for the ImmichWorkerStreamConsumer."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.stream_client import StreamEvent

from stream_consumer_tasks import ImmichWorkerStreamConsumer


@pytest.fixture
def mock_stream_client() -> MagicMock:
    """Return a mocked StreamClient."""
    client = MagicMock()
    client.ensure_group = AsyncMock()
    client.read_events = AsyncMock(return_value=[])
    client.ack = AsyncMock()
    return client


@pytest.fixture
def mock_session_factory() -> AsyncMock:
    """Return a mock session factory."""
    return AsyncMock()


@pytest.fixture
def consumer(
    mock_stream_client: MagicMock,
    mock_session_factory: AsyncMock,
) -> ImmichWorkerStreamConsumer:
    """Return a configured ImmichWorkerStreamConsumer."""
    return ImmichWorkerStreamConsumer(
        stream_client=mock_stream_client,
        session_factory=mock_session_factory,
    )


class TestImmichWorkerStreamConsumer:
    """Tests for ImmichWorkerStreamConsumer."""

    def test_registers_correct_group_name(
        self, consumer: ImmichWorkerStreamConsumer
    ) -> None:
        """Consumer registers with the 'immich-worker' consumer group."""
        assert consumer._group_name == "immich-worker"

    def test_registers_correct_stream_name(
        self, consumer: ImmichWorkerStreamConsumer
    ) -> None:
        """Consumer uses the default domain events stream."""
        assert consumer._stream_name == "pms:domain-events"

    def test_registers_correct_consumer_name(
        self, consumer: ImmichWorkerStreamConsumer
    ) -> None:
        """Consumer uses the default consumer name."""
        assert consumer._consumer_name == "immich-worker-1"

    def test_event_type_patterns(self, consumer: ImmichWorkerStreamConsumer) -> None:
        """Consumer subscribes to the correct event types."""
        expected = [
            "ContactCreated",
            "ContactUpdated",
            "ContactBirthdayChanged",
        ]
        assert consumer._event_type_patterns == expected

    def test_custom_stream_name(
        self,
        mock_stream_client: MagicMock,
        mock_session_factory: AsyncMock,
    ) -> None:
        """Consumer can be configured with a custom stream name."""
        consumer = ImmichWorkerStreamConsumer(
            stream_client=mock_stream_client,
            session_factory=mock_session_factory,
            stream_name="custom:stream",
        )
        assert consumer._stream_name == "custom:stream"

    def test_custom_consumer_name(
        self,
        mock_stream_client: MagicMock,
        mock_session_factory: AsyncMock,
    ) -> None:
        """Consumer can be configured with a custom consumer name."""
        consumer = ImmichWorkerStreamConsumer(
            stream_client=mock_stream_client,
            session_factory=mock_session_factory,
            consumer_name="immich-worker-2",
        )
        assert consumer._consumer_name == "immich-worker-2"


@pytest.mark.asyncio
class TestHandleEvent:
    """Tests for the _handle_event method."""

    async def test_handle_contact_created_event(
        self, consumer: ImmichWorkerStreamConsumer
    ) -> None:
        """ContactCreated event is handled without error."""
        event = StreamEvent(
            message_id="1-0",
            event_id="evt-1",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42, "user_id": 1},
            occurred_at="2024-01-01T00:00:00Z",
        )

        # Phase 2: just logs, should not raise
        await consumer._handle_event(event)

    async def test_handle_contact_updated_event(
        self, consumer: ImmichWorkerStreamConsumer
    ) -> None:
        """ContactUpdated event is handled without error."""
        event = StreamEvent(
            message_id="2-0",
            event_id="evt-2",
            event_type="ContactUpdated",
            aggregate_id=43,
            event_data={"contact_id": 43, "user_id": 1},
            occurred_at="2024-01-01T00:00:00Z",
        )

        await consumer._handle_event(event)

    async def test_handle_contact_birthday_changed_event(
        self, consumer: ImmichWorkerStreamConsumer
    ) -> None:
        """ContactBirthdayChanged event is handled without error."""
        event = StreamEvent(
            message_id="3-0",
            event_id="evt-3",
            event_type="ContactBirthdayChanged",
            aggregate_id=44,
            event_data={"contact_id": 44, "user_id": 1},
            occurred_at="2024-01-01T00:00:00Z",
        )

        await consumer._handle_event(event)

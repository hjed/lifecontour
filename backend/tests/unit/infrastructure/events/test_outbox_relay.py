"""
Unit tests for OutboxRelay.

Tests the relay process that reads unprocessed outbox events from Postgres
and publishes them to the Redis Stream.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.events.outbox_relay import OutboxRelay, run_outbox_relay_loop
from app.infrastructure.events.outbox_repository import OutboxEvent


class TestOutboxRelay:
    """Test cases for OutboxRelay."""

    @pytest.fixture
    def mock_stream_client(self) -> MagicMock:
        """Create a mock StreamClient."""
        client = MagicMock()
        client.publish = AsyncMock(return_value="1234567890-0")
        return client

    @pytest.fixture
    def relay(self, mock_stream_client: MagicMock) -> OutboxRelay:
        """Create an OutboxRelay instance with mock dependencies."""
        return OutboxRelay(
            stream_client=mock_stream_client,
            stream_name="pms:domain-events",
            batch_size=50,
        )

    @pytest.fixture
    def sample_unrelayed_events(self) -> list[OutboxEvent]:
        """Create sample unrelayed outbox events."""
        return [
            OutboxEvent(
                id=1,
                event_id="evt-1",
                event_type="ContactCreated",
                aggregate_id=42,
                event_data={"contact_id": 42, "name": "John"},
                occurred_at=datetime(2024, 1, 1, 12, 0, 0),
                retry_count=0,
                created_at=datetime(2024, 1, 1, 12, 0, 0),
                relayed_at=None,
            ),
            OutboxEvent(
                id=2,
                event_id="evt-2",
                event_type="ContactUpdated",
                aggregate_id=43,
                event_data={"contact_id": 43, "name": "Jane"},
                occurred_at=datetime(2024, 1, 1, 12, 5, 0),
                retry_count=0,
                created_at=datetime(2024, 1, 1, 12, 5, 0),
                relayed_at=None,
            ),
        ]

    @pytest.mark.asyncio
    async def test_relay_batch_publishes_unrelayed_events(
        self,
        relay: OutboxRelay,
        mock_stream_client: MagicMock,
        sample_unrelayed_events: list[OutboxEvent],
    ) -> None:
        """Test relay reads unrelayed events, publishes each to stream, marks as relayed."""
        mock_conn = AsyncMock()
        mock_repository = MagicMock()
        mock_repository.get_unrelayed_events = AsyncMock(
            return_value=sample_unrelayed_events
        )
        mock_repository.mark_as_relayed = AsyncMock()

        with patch(
            "app.infrastructure.events.outbox_relay.OutboxRepository",
            return_value=mock_repository,
        ):
            count = await relay.relay_batch(mock_conn)

        # Should publish both events
        assert mock_stream_client.publish.call_count == 2
        mock_stream_client.publish.assert_any_call(
            stream_name="pms:domain-events",
            event_id="evt-1",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42, "name": "John"},
            occurred_at=sample_unrelayed_events[0].occurred_at.isoformat(),
        )

        # Should mark both as relayed
        assert mock_repository.mark_as_relayed.call_count == 2
        mock_repository.mark_as_relayed.assert_any_call("evt-1")
        mock_repository.mark_as_relayed.assert_any_call("evt-2")

        assert count == 2

    @pytest.mark.asyncio
    async def test_relay_batch_returns_count_of_relayed_events(
        self,
        relay: OutboxRelay,
        mock_stream_client: MagicMock,
        sample_unrelayed_events: list[OutboxEvent],
    ) -> None:
        """Test relay_batch returns the number of successfully relayed events."""
        mock_conn = AsyncMock()
        mock_repository = MagicMock()
        mock_repository.get_unrelayed_events = AsyncMock(
            return_value=sample_unrelayed_events
        )
        mock_repository.mark_as_relayed = AsyncMock()

        with patch(
            "app.infrastructure.events.outbox_relay.OutboxRepository",
            return_value=mock_repository,
        ):
            count = await relay.relay_batch(mock_conn)

        assert count == 2

    @pytest.mark.asyncio
    async def test_relay_batch_no_events_returns_zero(
        self,
        relay: OutboxRelay,
        mock_stream_client: MagicMock,
    ) -> None:
        """Test relay_batch returns 0 when there are no unrelayed events."""
        mock_conn = AsyncMock()
        mock_repository = MagicMock()
        mock_repository.get_unrelayed_events = AsyncMock(return_value=[])

        with patch(
            "app.infrastructure.events.outbox_relay.OutboxRepository",
            return_value=mock_repository,
        ):
            count = await relay.relay_batch(mock_conn)

        assert count == 0
        mock_stream_client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_relay_idempotency_skips_already_relayed(
        self,
        relay: OutboxRelay,
        mock_stream_client: MagicMock,
    ) -> None:
        """Test relay defensively skips events where relayed_at is already set."""
        already_relayed = OutboxEvent(
            id=1,
            event_id="evt-1",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            retry_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            relayed_at=datetime(2024, 1, 1, 12, 1, 0),  # Already relayed
        )
        mock_conn = AsyncMock()
        mock_repository = MagicMock()
        mock_repository.get_unrelayed_events = AsyncMock(return_value=[already_relayed])

        with patch(
            "app.infrastructure.events.outbox_relay.OutboxRepository",
            return_value=mock_repository,
        ):
            count = await relay.relay_batch(mock_conn)

        assert count == 0
        mock_stream_client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_relay_batch_handles_publish_failure(
        self,
        relay: OutboxRelay,
        mock_stream_client: MagicMock,
        sample_unrelayed_events: list[OutboxEvent],
    ) -> None:
        """Test relay continues with next events when one fails to publish."""
        # First event fails, second succeeds
        mock_stream_client.publish.side_effect = [
            Exception("Redis connection error"),
            "1234567890-1",
        ]
        mock_conn = AsyncMock()
        mock_repository = MagicMock()
        mock_repository.get_unrelayed_events = AsyncMock(
            return_value=sample_unrelayed_events
        )
        mock_repository.mark_as_relayed = AsyncMock()

        with patch(
            "app.infrastructure.events.outbox_relay.OutboxRepository",
            return_value=mock_repository,
        ):
            count = await relay.relay_batch(mock_conn)

        # Only second event should be marked as relayed
        assert count == 1
        mock_repository.mark_as_relayed.assert_called_once_with("evt-2")

    @pytest.mark.asyncio
    async def test_relay_loop_runs_periodically(
        self,
        mock_stream_client: MagicMock,
    ) -> None:
        """Test run_outbox_relay_loop calls relay_batch periodically and handles cancellation."""
        mock_relay = MagicMock()
        mock_relay.relay_batch = AsyncMock(return_value=0)

        mock_engine = AsyncMock()

        @asynccontextmanager
        async def mock_begin():
            yield AsyncMock()

        mock_engine.begin = mock_begin

        async def run_and_cancel() -> None:
            with (
                patch(
                    "app.infrastructure.events.outbox_relay.OutboxRelay",
                    return_value=mock_relay,
                ),
                patch(
                    "app.infrastructure.events.outbox_relay.get_async_database_engine",
                    return_value=mock_engine,
                ),
            ):
                task = asyncio.create_task(
                    run_outbox_relay_loop(
                        mock_stream_client,
                        stream_name="pms:domain-events",
                        batch_size=50,
                        interval_seconds=0.05,
                    )
                )
                await asyncio.sleep(0.1)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await run_and_cancel()

        # Should have called relay_batch at least once
        assert mock_relay.relay_batch.call_count >= 1

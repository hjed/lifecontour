"""
Unit tests for StreamClient.

Tests the Redis Streams wrapper that provides XADD, XREADGROUP,
XACK, XPENDING, and XCLAIM operations.
"""

from unittest.mock import AsyncMock

import pytest

from core_shared.stream_client import (
    StreamClient,
    StreamEvent,
    create_stream_redis,
)


class TestStreamClient:
    """Test cases for StreamClient."""

    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        """Create a mock async Redis client."""
        return AsyncMock()

    @pytest.fixture
    def client(self, mock_redis: AsyncMock) -> StreamClient:
        """Create a StreamClient with a mock Redis connection."""
        return StreamClient(mock_redis)

    @pytest.mark.asyncio
    async def test_publish_calls_xadd(
        self, client: StreamClient, mock_redis: AsyncMock
    ) -> None:
        """Test publish calls XADD with correct stream name and data fields."""
        mock_redis.xadd.return_value = b"1234567890-0"

        result = await client.publish(
            stream_name="pms:domain-events",
            event_id="evt-1",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42, "name": "John"},
            occurred_at="2024-01-01T12:00:00Z",
        )

        assert result == "1234567890-0"
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "pms:domain-events"
        fields = call_args[0][1]
        assert fields["event_id"] == "evt-1"
        assert fields["event_type"] == "ContactCreated"
        assert fields["aggregate_id"] == "42"
        assert "contact_id" in fields["event_data"]
        assert fields["occurred_at"] == "2024-01-01T12:00:00Z"
        assert "trace_context" in fields

    @pytest.mark.asyncio
    async def test_ensure_consumer_group_creates_new_group(
        self, client: StreamClient, mock_redis: AsyncMock
    ) -> None:
        """Test ensure_consumer_group creates a new consumer group."""
        mock_redis.xgroup_create.return_value = True

        await client.ensure_consumer_group(
            stream_name="pms:domain-events",
            group_name="search-indexer",
        )

        mock_redis.xgroup_create.assert_called_once_with(
            "pms:domain-events",
            "search-indexer",
            id="0",
            mkstream=True,
        )

    @pytest.mark.asyncio
    async def test_ensure_consumer_group_ignores_existing(
        self, client: StreamClient, mock_redis: AsyncMock
    ) -> None:
        """Test ensure_consumer_group silently catches BUSYGROUP error."""
        from redis.exceptions import ResponseError

        mock_redis.xgroup_create.side_effect = ResponseError(
            "BUSYGROUP Consumer Group name already exists"
        )

        # Should not raise
        await client.ensure_consumer_group(
            stream_name="pms:domain-events",
            group_name="search-indexer",
        )

    @pytest.mark.asyncio
    async def test_ensure_consumer_group_raises_non_busygroup_errors(
        self, client: StreamClient, mock_redis: AsyncMock
    ) -> None:
        """Test ensure_consumer_group re-raises non-BUSYGROUP errors."""
        from redis.exceptions import ResponseError

        mock_redis.xgroup_create.side_effect = ResponseError("SOME_OTHER_ERROR")

        with pytest.raises(ResponseError, match="SOME_OTHER_ERROR"):
            await client.ensure_consumer_group(
                stream_name="pms:domain-events",
                group_name="search-indexer",
            )

    @pytest.mark.asyncio
    async def test_read_events_calls_xreadgroup(
        self, client: StreamClient, mock_redis: AsyncMock
    ) -> None:
        """Test read_events calls XREADGROUP with correct parameters."""
        # XREADGROUP returns: [[stream_name, [(msg_id, {fields}), ...]]]
        mock_redis.xreadgroup.return_value = [
            [
                b"pms:domain-events",
                [
                    (
                        b"1234567890-0",
                        {
                            b"event_id": b"evt-1",
                            b"event_type": b"ContactCreated",
                            b"aggregate_id": b"42",
                            b"event_data": b'{"contact_id": 42}',
                            b"occurred_at": b"2024-01-01T12:00:00Z",
                            b"trace_context": b'{"traceparent": "00-xxx-yyy-01"}',
                        },
                    )
                ],
            ]
        ]

        events = await client.read_events(
            stream_name="pms:domain-events",
            group_name="search-indexer",
            consumer_name="search-1",
            count=10,
            block_ms=5000,
        )

        mock_redis.xreadgroup.assert_called_once_with(
            groupname="search-indexer",
            consumername="search-1",
            streams={"pms:domain-events": ">"},
            count=10,
            block=5000,
        )
        assert len(events) == 1
        assert events[0].event_id == "evt-1"
        assert events[0].event_type == "ContactCreated"
        assert events[0].aggregate_id == 42
        assert events[0].event_data == {"contact_id": 42}
        assert events[0].message_id == "1234567890-0"
        assert events[0].trace_context == {"traceparent": "00-xxx-yyy-01"}

    @pytest.mark.asyncio
    async def test_read_events_returns_empty_on_none(
        self, client: StreamClient, mock_redis: AsyncMock
    ) -> None:
        """Test read_events returns empty list when XREADGROUP returns None."""
        mock_redis.xreadgroup.return_value = None

        events = await client.read_events(
            stream_name="pms:domain-events",
            group_name="search-indexer",
            consumer_name="search-1",
            count=10,
            block_ms=5000,
        )

        assert events == []

    @pytest.mark.asyncio
    async def test_acknowledge_calls_xack(
        self, client: StreamClient, mock_redis: AsyncMock
    ) -> None:
        """Test acknowledge calls XACK with correct parameters."""
        mock_redis.xack.return_value = 1

        await client.acknowledge(
            stream_name="pms:domain-events",
            group_name="search-indexer",
            message_id="1234567890-0",
        )

        mock_redis.xack.assert_called_once_with(
            "pms:domain-events", "search-indexer", "1234567890-0"
        )

    @pytest.mark.asyncio
    async def test_get_pending_entries(
        self, client: StreamClient, mock_redis: AsyncMock
    ) -> None:
        """Test get_pending_entries calls XPENDING with correct range."""
        # XPENDING RANGE returns list of [message_id, consumer, idle_time, delivery_count]
        mock_redis.xpending_range.return_value = [
            {
                "message_id": b"1234567890-0",
                "consumer": b"search-1",
                "time_since_delivered": 120000,
                "times_delivered": 2,
            }
        ]

        entries = await client.get_pending_entries(
            stream_name="pms:domain-events",
            group_name="search-indexer",
            min_idle_time_ms=60000,
            count=10,
        )

        mock_redis.xpending_range.assert_called_once_with(
            "pms:domain-events",
            "search-indexer",
            min="-",
            max="+",
            count=10,
            idle=60000,
        )
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_claim_pending_calls_xclaim(
        self, client: StreamClient, mock_redis: AsyncMock
    ) -> None:
        """Test claim_pending calls XCLAIM with correct parameters."""
        mock_redis.xclaim.return_value = [
            (
                b"1234567890-0",
                {
                    b"event_id": b"evt-1",
                    b"event_type": b"ContactCreated",
                    b"aggregate_id": b"42",
                    b"event_data": b'{"contact_id": 42}',
                    b"occurred_at": b"2024-01-01T12:00:00Z",
                    b"trace_context": b"{}",
                },
            )
        ]

        events = await client.claim_pending(
            stream_name="pms:domain-events",
            group_name="search-indexer",
            consumer_name="search-1",
            min_idle_time_ms=60000,
            message_ids=["1234567890-0"],
        )

        mock_redis.xclaim.assert_called_once_with(
            "pms:domain-events",
            "search-indexer",
            "search-1",
            min_idle_time=60000,
            message_ids=["1234567890-0"],
        )
        assert len(events) == 1
        assert events[0].event_id == "evt-1"


class TestStreamEvent:
    """Test cases for StreamEvent dataclass."""

    def test_stream_event_creation(self) -> None:
        """Test StreamEvent can be created with all fields."""
        event = StreamEvent(
            message_id="1234567890-0",
            event_id="evt-1",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42},
            occurred_at="2024-01-01T12:00:00Z",
            trace_context={"traceparent": "test"},
        )
        assert event.message_id == "1234567890-0"
        assert event.event_id == "evt-1"
        assert event.event_type == "ContactCreated"
        assert event.aggregate_id == 42
        assert event.event_data == {"contact_id": 42}
        assert event.occurred_at == "2024-01-01T12:00:00Z"
        assert event.trace_context == {"traceparent": "test"}


class TestCreateStreamRedis:
    """Tests for the create_stream_redis connection factory.

    Regression coverage for redis-py 8.0.0, which changed the default
    ``socket_timeout`` from ``None`` to 5 seconds. Blocking ``XREADGROUP``
    calls hold the socket open for the full ``BLOCK block_ms`` duration when
    a stream is idle, so the socket read timeout must exceed ``block_ms`` or
    every idle poll raises ``redis.exceptions.TimeoutError``.
    """

    @staticmethod
    def _socket_timeout(redis: object) -> float | None:
        kwargs = redis.connection_pool.connection_kwargs  # type: ignore[attr-defined]
        socket_timeout: float | None = kwargs.get("socket_timeout")
        return socket_timeout

    @pytest.mark.asyncio
    async def test_socket_timeout_exceeds_default_block_duration(self) -> None:
        """Default block_ms (5000) must yield a socket_timeout above 5 seconds."""
        redis = create_stream_redis("redis://localhost:6379")
        try:
            socket_timeout = self._socket_timeout(redis)
            assert socket_timeout is not None
            # block_ms default is 5000ms == 5s; the socket read timeout must be
            # strictly greater so a blocking read of an idle stream never races
            # the socket timeout.
            assert socket_timeout > 5.0
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_socket_timeout_scales_with_block_ms(self) -> None:
        """socket_timeout must stay above the configured block duration."""
        redis = create_stream_redis("redis://localhost:6379", block_ms=30000)
        try:
            socket_timeout = self._socket_timeout(redis)
            assert socket_timeout is not None
            assert socket_timeout > 30.0
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_infinite_block_disables_socket_timeout(self) -> None:
        """block_ms=0 blocks forever, so socket_timeout must be disabled."""
        redis = create_stream_redis("redis://localhost:6379", block_ms=0)
        try:
            assert self._socket_timeout(redis) is None
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_defaults_to_byte_responses(self) -> None:
        """decode_responses defaults to False to match StreamClient parsing."""
        redis = create_stream_redis("redis://localhost:6379")
        try:
            kwargs = redis.connection_pool.connection_kwargs
            assert kwargs.get("decode_responses") is False
        finally:
            await redis.aclose()

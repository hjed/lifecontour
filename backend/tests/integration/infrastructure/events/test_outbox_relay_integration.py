"""
Integration tests for OutboxRelay and StreamConsumer with real Redis and Postgres.

Tests the end-to-end flow: outbox events in Postgres -> relay to Redis Stream
-> consumer reads and acknowledges from stream.
"""

import json
import os
import uuid

import pytest
import pytest_asyncio
from core_shared.stream_client import StreamClient, StreamEvent
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.outbox_relay import OutboxRelay
from app.infrastructure.events.stream_consumer import StreamConsumer


def _get_redis_test_url() -> str:
    """Get Redis URL for integration tests.

    Reuses the workspace_env helper from conftest for consistency.
    """
    # Check CI environment first
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        return os.getenv("REDIS_URL", "redis://localhost:6379")

    # Reuse the workspace_env from conftest
    from tests.integration.conftest import workspace_env

    port = workspace_env.get("REDIS_TEST_PORT", "6380")
    return f"redis://localhost:{port}"


# Unique stream name per test run to avoid collisions
TEST_STREAM = f"pms:test-domain-events-{uuid.uuid4().hex[:8]}"


class ConcreteTestConsumer(StreamConsumer):
    """Concrete consumer for integration testing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handled_events: list[StreamEvent] = []

    async def _handle_event(self, event: StreamEvent) -> None:
        self.handled_events.append(event)


@pytest_asyncio.fixture
async def redis_client():
    """Create a real Redis client for testing."""
    url = _get_redis_test_url()
    client = Redis.from_url(url, decode_responses=False)
    try:
        await client.ping()
    except Exception:
        pytest.skip(f"Redis not available at {url}")
    yield client
    # Cleanup: delete the test stream
    await client.delete(TEST_STREAM)
    await client.aclose()


@pytest.fixture
def stream_client(redis_client: Redis) -> StreamClient:
    """Create a StreamClient wrapping the real Redis connection."""
    return StreamClient(redis_client)


class TestOutboxRelayIntegration:
    """Integration tests for OutboxRelay with real Postgres and Redis."""

    @pytest.mark.asyncio
    async def test_relay_reads_real_outbox_rows_and_publishes_to_redis_stream(
        self,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Insert outbox events into real DB -> relay reads them -> verify in Redis Stream."""
        # Arrange: insert outbox events
        event_id_1 = f"test-evt-{uuid.uuid4().hex[:8]}"
        event_id_2 = f"test-evt-{uuid.uuid4().hex[:8]}"

        await async_connection.execute(
            text(
                """
                INSERT INTO outbox_events (event_id, event_type, aggregate_id, event_data, occurred_at, created_at, retry_count)
                VALUES (:event_id, :event_type, :aggregate_id, :event_data, NOW(), NOW(), 0)
                """
            ),
            {
                "event_id": event_id_1,
                "event_type": "ContactCreated",
                "aggregate_id": 42,
                "event_data": json.dumps({"contact_id": 42, "name": "Alice"}),
            },
        )
        await async_connection.execute(
            text(
                """
                INSERT INTO outbox_events (event_id, event_type, aggregate_id, event_data, occurred_at, created_at, retry_count)
                VALUES (:event_id, :event_type, :aggregate_id, :event_data, NOW(), NOW(), 0)
                """
            ),
            {
                "event_id": event_id_2,
                "event_type": "ContactUpdated",
                "aggregate_id": 43,
                "event_data": json.dumps({"contact_id": 43, "name": "Bob"}),
            },
        )

        # Act: relay the events
        relay = OutboxRelay(
            stream_client=stream_client,
            stream_name=TEST_STREAM,
            batch_size=50,
        )
        count = await relay.relay_batch(async_connection)

        # Assert: events were relayed
        assert count == 2

        # Verify events appear in Redis Stream
        stream_messages = await redis_client.xrange(TEST_STREAM)
        assert len(stream_messages) == 2

        # Verify event data in stream
        event_ids_in_stream = [msg[1][b"event_id"].decode() for msg in stream_messages]
        assert event_id_1 in event_ids_in_stream
        assert event_id_2 in event_ids_in_stream

        # Verify relayed_at is set in DB
        result = await async_connection.execute(
            text("SELECT relayed_at FROM outbox_events WHERE event_id = :event_id"),
            {"event_id": event_id_1},
        )
        row = result.fetchone()
        assert row is not None
        assert row.relayed_at is not None

    @pytest.mark.asyncio
    async def test_relay_idempotency_with_real_database(
        self,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Run relay twice on same events -> second run publishes nothing."""
        # Arrange: insert an outbox event
        event_id = f"test-evt-{uuid.uuid4().hex[:8]}"
        await async_connection.execute(
            text(
                """
                INSERT INTO outbox_events (event_id, event_type, aggregate_id, event_data, occurred_at, created_at, retry_count)
                VALUES (:event_id, :event_type, :aggregate_id, :event_data, NOW(), NOW(), 0)
                """
            ),
            {
                "event_id": event_id,
                "event_type": "ContactCreated",
                "aggregate_id": 42,
                "event_data": json.dumps({"contact_id": 42}),
            },
        )

        relay = OutboxRelay(
            stream_client=stream_client,
            stream_name=TEST_STREAM,
            batch_size=50,
        )

        # Act: first relay
        count1 = await relay.relay_batch(async_connection)
        # Act: second relay
        count2 = await relay.relay_batch(async_connection)

        # Assert
        assert count1 == 1
        assert count2 == 0  # Nothing new to relay

        # Only one message in the stream
        stream_messages = await redis_client.xrange(TEST_STREAM)
        assert len(stream_messages) == 1


class TestBaseConsumerIntegration:
    """Integration tests for StreamConsumer with real Redis."""

    @pytest.mark.asyncio
    async def test_base_consumer_reads_and_acknowledges_from_real_stream(
        self,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Publish events to Redis Stream -> consumer reads, filters, acknowledges."""
        group_name = f"test-group-{uuid.uuid4().hex[:8]}"

        # Publish events to stream
        await stream_client.publish(
            stream_name=TEST_STREAM,
            event_id="evt-contact",
            event_type="contact.created",
            aggregate_id=42,
            event_data={"contact_id": 42},
            occurred_at="2024-01-01T12:00:00Z",
        )
        await stream_client.publish(
            stream_name=TEST_STREAM,
            event_id="evt-journal",
            event_type="JournalCreated",
            aggregate_id=100,
            event_data={"journal_id": 100},
            occurred_at="2024-01-01T12:05:00Z",
        )

        # Create consumer that only cares about contact events
        consumer = ConcreteTestConsumer(
            stream_client=stream_client,
            stream_name=TEST_STREAM,
            group_name=group_name,
            consumer_name="test-consumer-1",
            event_type_patterns=["contact."],
            block_ms=100,  # Short block for testing
        )

        # Create the consumer group
        await stream_client.ensure_consumer_group(TEST_STREAM, group_name)

        # Process one batch
        count = await consumer._process_batch()

        # Assert
        assert count == 2  # Both events were processed (one handled, one skipped)
        assert len(consumer.handled_events) == 1
        assert consumer.handled_events[0].event_type == "contact.created"

        # Verify no pending entries (all acknowledged)
        pending_info = await redis_client.xpending(TEST_STREAM, group_name)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_consumer_group_creation_and_persistence(
        self,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Create consumer group -> restart consumer -> group still exists."""
        group_name = f"test-group-{uuid.uuid4().hex[:8]}"

        # Create group
        await stream_client.ensure_consumer_group(TEST_STREAM, group_name)

        # Verify group exists by trying to create it again (should not raise)
        await stream_client.ensure_consumer_group(TEST_STREAM, group_name)

        # Verify group is listed
        groups = await redis_client.xinfo_groups(TEST_STREAM)
        group_names = [
            g["name"].decode() if isinstance(g["name"], bytes) else g["name"]
            for g in groups
        ]
        assert group_name in group_names

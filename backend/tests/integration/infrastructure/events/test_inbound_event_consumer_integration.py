"""
Integration tests for InboundEventConsumer.

Tests the end-to-end flow: Redis stream -> consumer -> domain processor delegation.
Validates that events flow correctly from Redis Streams through the consumer
and that the appropriate domain processor is invoked with the adapted OutboxEvent.
"""

import os
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.config import Settings
from app.infrastructure.events.inbound_event_consumer import InboundEventConsumer


def _get_redis_test_url() -> str:
    """Get Redis URL for integration tests."""
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        return os.getenv("REDIS_URL", "redis://localhost:6379")

    from tests.integration.conftest import workspace_env

    port = workspace_env.get("REDIS_TEST_PORT", "6380")
    return f"redis://localhost:{port}"


TEST_STREAM = f"pms:test-inbound-events-{uuid.uuid4().hex[:8]}"
GROUP_NAME = "inbound-processor"


@pytest_asyncio.fixture
async def redis_client():
    """Create a real Redis client for testing."""
    url = _get_redis_test_url()
    client = Redis.from_url(url, decode_responses=False)
    await client.ping()
    yield client
    await client.delete(TEST_STREAM)
    await client.close()


@pytest.fixture
def stream_client(redis_client: Redis) -> StreamClient:
    """Create a StreamClient wrapping the real Redis connection."""
    return StreamClient(redis_client)


@pytest.fixture
def mock_settings() -> MagicMock:
    """Create mock Settings for the consumer."""
    settings = MagicMock(spec=Settings)
    settings.gemini_api_key = ""
    settings.gemini_model = "gemini-2.5-flash"
    return settings


class TestInboundEventConsumerIntegration:
    """Integration tests for InboundEventConsumer with real Redis and Postgres."""

    @pytest.mark.asyncio
    async def test_consumer_processes_contact_created_event(
        self,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
        mock_settings: MagicMock,
    ) -> None:
        """Verify the consumer reads a contact.created event from Redis
        and delegates to OutboxEventProcessor."""
        # 1. Arrange: Publish a contact.created event
        await stream_client.publish(
            stream_name=TEST_STREAM,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="contact.created",
            aggregate_id=1,
            event_data={
                "integration_source": "google",
                "external_id": "people/c123",
                "contact_data": {"first_name": "Test", "last_name": "Contact"},
                "sync_timestamp": "2024-01-01T10:00:00Z",
                "sync_type": "created",
                "etag": "etag123",
            },
            occurred_at="2024-01-01T12:00:00Z",
        )

        # 2. Setup the consumer
        mock_container = MagicMock()
        consumer = InboundEventConsumer(
            stream_client=stream_client,
            container=mock_container,
            settings=mock_settings,
            stream_name=TEST_STREAM,
            consumer_name="test-inbound-1",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(TEST_STREAM, GROUP_NAME)

        # Mock the engine so the consumer uses our test connection
        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield async_connection

        mock_engine.begin = mock_begin

        # Mock the OutboxEventProcessor to verify delegation
        mock_processor = AsyncMock()
        mock_processor.process_event = AsyncMock(
            return_value={"status": "success", "contact_id": 123}
        )

        # 3. Act: Process the batch
        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.core.integrations.outbox_event_processor.OutboxEventProcessor",
                return_value=mock_processor,
            ),
        ):
            count = await consumer._process_batch()

        # 4. Assert: Event was processed from the stream
        assert count == 1

        # Verify pending entries are 0 (all acknowledged)
        pending_info = await redis_client.xpending(TEST_STREAM, GROUP_NAME)
        assert pending_info["pending"] == 0

        # Verify OutboxEventProcessor was called with the adapted OutboxEvent
        mock_processor.process_event.assert_called_once()
        call_args = mock_processor.process_event.call_args[0]
        outbox_event = call_args[0]
        assert outbox_event.event_type == "contact.created"
        assert outbox_event.event_data["integration_source"] == "google"

    @pytest.mark.asyncio
    async def test_consumer_processes_journal_event(
        self,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
        mock_settings: MagicMock,
    ) -> None:
        """Verify journal_event.created events delegate to JournalOutboxEventProcessor."""
        await stream_client.publish(
            stream_name=TEST_STREAM,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="journal_event.created",
            aggregate_id=1,
            event_data={
                "journal_id": 1,
                "user_id": "user123",
                "title": "Test Journal",
            },
            occurred_at="2024-01-01T12:00:00Z",
        )

        mock_container = MagicMock()
        consumer = InboundEventConsumer(
            stream_client=stream_client,
            container=mock_container,
            settings=mock_settings,
            stream_name=TEST_STREAM,
            consumer_name="test-inbound-journal",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(TEST_STREAM, GROUP_NAME)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield async_connection

        mock_engine.begin = mock_begin

        mock_journal_processor = AsyncMock()
        mock_journal_processor.process_event = AsyncMock(
            return_value={"status": "success"}
        )

        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.core.integrations.journal_outbox_event_processor.JournalOutboxEventProcessor",
                return_value=mock_journal_processor,
            ),
        ):
            count = await consumer._process_batch()

        assert count == 1
        mock_journal_processor.process_event.assert_called_once()

        pending_info = await redis_client.xpending(TEST_STREAM, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_consumer_acknowledges_irrelevant_events(
        self,
        stream_client: StreamClient,
        redis_client: Redis,
        mock_settings: MagicMock,
    ) -> None:
        """Verify the consumer acknowledges and skips events it shouldn't process."""
        # Publish an irrelevant event (domain event, not a sync event)
        await stream_client.publish(
            stream_name=TEST_STREAM,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="ContactCreated",
            aggregate_id=1,
            event_data={"contact_id": 1},
            occurred_at="2024-01-01T12:00:00Z",
        )

        mock_container = MagicMock()
        consumer = InboundEventConsumer(
            stream_client=stream_client,
            container=mock_container,
            settings=mock_settings,
            stream_name=TEST_STREAM,
            consumer_name="test-inbound-skip",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(TEST_STREAM, GROUP_NAME)

        count = await consumer._process_batch()

        # It processed the batch (read the event)
        assert count == 1

        # And it acknowledged the event without processing
        pending_info = await redis_client.xpending(TEST_STREAM, GROUP_NAME)
        assert pending_info["pending"] == 0

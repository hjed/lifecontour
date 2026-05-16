"""
Integration tests for Snipe-IT webhook endpoint.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from core_shared.stream_client import StreamClient
from httpx import AsyncClient

from app.infrastructure.config import Settings


@pytest_asyncio.fixture
async def cleanup_stream(test_settings: Settings) -> AsyncGenerator[None, None]:
    """Cleanup stream after test."""
    yield
    # No standard way to delete stream entirely in test client, but tests use isolated redis DBs usually.


@pytest.mark.asyncio
async def test_snipeit_webhook_publishes_to_stream(
    authenticated_client: AsyncClient,
    test_settings: Settings,
) -> None:
    """Test that a valid webhook POST results in a message in the Redis stream."""
    from redis.asyncio import Redis

    redis_client = Redis.from_url(test_settings.redis_url, decode_responses=False)
    stream_client = StreamClient(redis_client)

    try:
        # Clear the stream to ensure isolation for this test
        await redis_client.delete(test_settings.stream_name)

        # Ensure consumer group exists to track messages
        await stream_client.ensure_consumer_group(
            test_settings.stream_name, "test-group"
        )

        payload = {"action": "checkout", "item": {"id": 123, "name": "Test Asset"}}

        response = await authenticated_client.post(
            "/api/integrations/snipeit/webhook",
            json=payload,
        )

        assert response.status_code == 200

        # Read from stream to verify message was published
        events = await stream_client.read_events(
            stream_name=test_settings.stream_name,
            group_name="test-group",
            consumer_name="test-consumer",
            count=10,
            block_ms=100,
        )

        assert len(events) >= 1
        # Find our event
        webhook_event = next(
            (
                e
                for e in events
                if e.event_type == "snipeit.webhook_received"
                and e.event_data.get("action") == "checkout"
            ),
            None,
        )
        assert webhook_event is not None
        assert webhook_event.event_data == payload

        # Clean up
        await stream_client.acknowledge(
            test_settings.stream_name, "test-group", webhook_event.message_id
        )
    finally:
        await redis_client.close()

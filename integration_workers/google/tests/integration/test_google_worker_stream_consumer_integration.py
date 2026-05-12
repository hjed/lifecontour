"""
Integration tests for GoogleWorkerStreamConsumer.

Tests the full broadcast flow: publish domain event to Redis Stream →
Google worker stream consumer reads → process_journal_event/process_tag_event
called directly.

Uses real Redis from Docker test profile.
"""

import asyncio
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import redis.asyncio as redis_async
from core_shared.stream_client import StreamClient

from stream_consumer_tasks import GoogleWorkerStreamConsumer


def _get_redis_url() -> str:
    """Get Redis URL for integration tests."""
    import os

    return os.environ.get("REDIS_URL", "redis://localhost:6379")


@pytest_asyncio.fixture
async def redis_client() -> Any:
    """Create a real Redis client for testing."""
    client = redis_async.from_url(_get_redis_url())
    yield client
    await client.close()


@pytest_asyncio.fixture
async def stream_client(redis_client: Any) -> StreamClient:
    """Create a real StreamClient for testing."""
    return StreamClient(redis_client)


@pytest_asyncio.fixture
async def unique_stream_name() -> str:
    """Generate a unique stream name for test isolation."""
    return f"test:stream-consumer:{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def cleanup_stream(redis_client: Any, unique_stream_name: str) -> Any:
    """Clean up the test stream after tests."""
    yield
    await redis_client.delete(unique_stream_name)


@pytest.mark.asyncio
class TestGoogleWorkerStreamConsumerIntegration:
    """Integration tests using real Redis for the Google worker stream consumer."""

    async def test_journal_event_flows_through_stream_to_process_function(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
        cleanup_stream: Any,
    ) -> None:
        """Publish JournalCreated to real Redis Stream → consumer reads → process_journal_event called."""
        mock_session_factory = AsyncMock()
        event_id = f"evt-{uuid.uuid4().hex[:8]}"
        event_data = {"journal_id": 42, "title": "Test Journal"}

        # Publish event to real Redis stream
        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": event_id,
                "event_type": "JournalCreated",
                "aggregate_id": "42",
                "event_data": json.dumps(event_data),
                "occurred_at": "2024-06-15T10:30:00+00:00",
            },
        )

        # Create consumer with real Redis
        consumer = GoogleWorkerStreamConsumer(
            stream_client=stream_client,
            session_factory=mock_session_factory,
            stream_name=unique_stream_name,
            batch_size=1,
            block_ms=1000,
        )

        # Ensure consumer group exists
        await stream_client.ensure_consumer_group(unique_stream_name, "google-worker")

        received_calls: list[dict[str, Any]] = []

        async def mock_process_journal(
            ctx: Any, event_type: str, event_data: Any
        ) -> dict[str, str]:
            received_calls.append(
                {"ctx": ctx, "event_type": event_type, "event_data": event_data}
            )
            return {"status": "success"}

        with patch(
            "stream_consumer_tasks.process_journal_event",
            side_effect=mock_process_journal,
        ):
            # Process one batch
            processed = await consumer._process_batch()

        assert processed == 1
        assert len(received_calls) == 1
        assert received_calls[0]["event_type"] == "JournalCreated"
        assert received_calls[0]["event_data"] == event_data
        assert received_calls[0]["ctx"]["session_factory"] is mock_session_factory
        assert received_calls[0]["ctx"]["job_id"] == event_id

    async def test_tag_event_flows_through_stream_to_process_function(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
        cleanup_stream: Any,
    ) -> None:
        """Publish TagUpdated to real Redis Stream → consumer reads → process_tag_event called."""
        mock_session_factory = AsyncMock()
        event_id = f"evt-{uuid.uuid4().hex[:8]}"
        event_data = {"tag_id": 10, "name": "Updated Tag"}

        # Publish event
        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": event_id,
                "event_type": "TagUpdated",
                "aggregate_id": "10",
                "event_data": json.dumps(event_data),
                "occurred_at": "2024-06-15T10:30:00+00:00",
            },
        )

        consumer = GoogleWorkerStreamConsumer(
            stream_client=stream_client,
            session_factory=mock_session_factory,
            stream_name=unique_stream_name,
            batch_size=1,
            block_ms=1000,
        )

        await stream_client.ensure_consumer_group(unique_stream_name, "google-worker")

        received_calls: list[dict[str, Any]] = []

        async def mock_process_tag(
            ctx: Any, event_type: str, event_data: Any
        ) -> dict[str, str]:
            received_calls.append(
                {"ctx": ctx, "event_type": event_type, "event_data": event_data}
            )
            return {"status": "success"}

        with patch(
            "stream_consumer_tasks.process_tag_event",
            side_effect=mock_process_tag,
        ):
            processed = await consumer._process_batch()

        assert processed == 1
        assert len(received_calls) == 1
        assert received_calls[0]["event_type"] == "TagUpdated"
        assert received_calls[0]["event_data"] == event_data

    async def test_irrelevant_event_acknowledged_immediately(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
        cleanup_stream: Any,
    ) -> None:
        """Publish SomethingElse → consumer ACKs without calling any process function."""
        mock_session_factory = AsyncMock()

        # Publish a non-matching event
        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": f"evt-{uuid.uuid4().hex[:8]}",
                "event_type": "SomethingElse",
                "aggregate_id": "99",
                "event_data": json.dumps({"foo": "bar"}),
                "occurred_at": "2024-06-15T10:30:00+00:00",
            },
        )

        consumer = GoogleWorkerStreamConsumer(
            stream_client=stream_client,
            session_factory=mock_session_factory,
            stream_name=unique_stream_name,
            batch_size=1,
            block_ms=1000,
        )

        await stream_client.ensure_consumer_group(unique_stream_name, "google-worker")

        with (
            patch(
                "stream_consumer_tasks.process_journal_event",
                new_callable=AsyncMock,
            ) as mock_journal,
            patch(
                "stream_consumer_tasks.process_tag_event",
                new_callable=AsyncMock,
            ) as mock_tag,
            patch(
                "stream_consumer_tasks.process_contact_event",
                new_callable=AsyncMock,
            ) as mock_contact,
        ):
            processed = await consumer._process_batch()

        # Event was processed (ACKed) but no handler was called
        assert processed == 1
        mock_journal.assert_not_called()
        mock_tag.assert_not_called()
        mock_contact.assert_not_called()

        # Verify no pending entries (event was ACKed)
        pending = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="google-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending) == 0

    async def test_consumer_start_stop_lifecycle(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
        cleanup_stream: Any,
    ) -> None:
        """Verify the consumer can start and stop cleanly via task cancellation."""
        mock_session_factory = AsyncMock()

        consumer = GoogleWorkerStreamConsumer(
            stream_client=stream_client,
            session_factory=mock_session_factory,
            stream_name=unique_stream_name,
            block_ms=100,  # Short block for fast test
        )

        with (
            patch(
                "stream_consumer_tasks.process_journal_event", new_callable=AsyncMock
            ),
            patch("stream_consumer_tasks.process_tag_event", new_callable=AsyncMock),
        ):
            task = asyncio.create_task(consumer.start())

            # Let it run one iteration
            await asyncio.sleep(0.3)

            # Cancel the task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # If we get here without hanging, the lifecycle works correctly
        assert True

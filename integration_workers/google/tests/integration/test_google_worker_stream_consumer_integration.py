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
    await client.aclose()


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

    @pytest.mark.parametrize(
        "event_type",
        [
            "TagAssigned",
            "TagRemoved",
            "ContactMethodAdded",
            "ContactMethodDeleted",
            "ImportantDateAdded",
            "ImportantDateUpdated",
            "ImportantDateDeleted",
            "ContactAddressAdded",
            "ContactAddressDeleted",
            "ContactNoteAdded",
        ],
    )
    async def test_contact_sub_entity_event_reaches_the_contact_handler(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
        cleanup_stream: Any,
        event_type: str,
    ) -> None:
        """LOCAL-177 regression: these events used to be acked and dropped.

        The route table listed only the four aggregate-level contact events, so
        adding a tag or an email address was read off the stream, acknowledged
        and discarded — the change never reached Google. This is the end-to-end
        guard for that: a real event on a real stream must reach
        ``process_contact_event``.
        """
        mock_session_factory = AsyncMock()
        event_id = f"evt-{uuid.uuid4().hex[:8]}"
        event_data = {"contact_id": 77, "source": "ui"}

        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": event_id,
                "event_type": event_type,
                "aggregate_id": "77",
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

        async def mock_process_contact(
            ctx: Any, event_type: str, event_data: Any
        ) -> dict[str, str]:
            received_calls.append({"event_type": event_type, "event_data": event_data})
            return {"status": "success"}

        with patch(
            "stream_consumer_tasks.process_contact_event",
            side_effect=mock_process_contact,
        ):
            processed = await consumer._process_batch()

        assert processed == 1
        assert len(received_calls) == 1, (
            f"{event_type} was consumed but never dispatched to "
            "process_contact_event - it is missing from the contact route table"
        )
        assert received_calls[0]["event_type"] == event_type
        assert received_calls[0]["event_data"] == event_data

        # Dispatched successfully, so it is acknowledged rather than left pending.
        pending = await redis_client.xpending(unique_stream_name, "google-worker")
        assert pending["pending"] == 0

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

    async def test_failing_handler_retried_via_pending_entries(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
        cleanup_stream: Any,
    ) -> None:
        """A handler that fails leaves the event pending, then a retry acks it.

        First delivery raises (event stays pending, unacked); the pending entry
        is then claimed and re-dispatched, succeeds, and is acknowledged.
        """
        mock_session_factory = AsyncMock()
        event_data = {"journal_id": 7, "title": "Retry Journal"}

        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": f"evt-{uuid.uuid4().hex[:8]}",
                "event_type": "JournalCreated",
                "aggregate_id": "7",
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
        consumer._retry_min_idle_ms = 0  # retry immediately for the test

        await stream_client.ensure_consumer_group(unique_stream_name, "google-worker")

        call_count = 0

        async def flaky_process_journal(
            ctx: Any, event_type: str, event_data: Any
        ) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")
            return {"status": "success"}

        with patch(
            "stream_consumer_tasks.process_journal_event",
            side_effect=flaky_process_journal,
        ):
            # First batch: handler raises, event left pending (unacked).
            await consumer._process_batch()
            pending_after_failure = await stream_client.get_pending_entries(
                stream_name=unique_stream_name,
                group_name="google-worker",
                min_idle_time_ms=0,
                count=10,
            )
            assert len(pending_after_failure) == 1

            # Retry cycle: claim the pending entry, re-dispatch, succeed, ack.
            retried = await consumer._retry_pending()

        assert retried == 1
        assert call_count == 2
        pending_after_retry = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="google-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending_after_retry) == 0

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

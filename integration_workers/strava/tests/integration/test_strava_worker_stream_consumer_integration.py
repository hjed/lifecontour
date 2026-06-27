"""Integration tests for the StravaWorkerStreamConsumer (ITER14-004 Phase 3).

Exercises the declarative route table against **real Redis**: publish a domain
event to a Redis Stream, the consumer reads it, dispatches matched ``strava.``
events to the strava handler, acks unmatched events without dispatch, and retries
a failing handler via pending entries.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import redis.asyncio as redis_async
from core_shared.stream_client import StreamClient

from stream_consumer_tasks import StravaWorkerStreamConsumer

from .conftest import get_workspace_env

os.environ.setdefault(
    "REDIS_URL",
    f"redis://localhost:{get_workspace_env().get('REDIS_TEST_PORT', '6380')}",
)

GROUP_NAME = "strava-worker"


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Any]:
    """Create a real Redis client for testing."""
    client = redis_async.from_url(os.environ["REDIS_URL"])
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def stream_client(redis_client: Any) -> StreamClient:
    """Create a real StreamClient for testing."""
    return StreamClient(redis_client)


@pytest_asyncio.fixture
async def unique_stream_name(redis_client: Any) -> AsyncIterator[str]:
    """Generate a unique stream name and clean it up afterwards."""
    name = f"test:strava-consumer:{uuid.uuid4().hex[:8]}"
    yield name
    await redis_client.delete(name)


async def _publish(redis_client: Any, stream_name: str, event_type: str) -> None:
    """Publish a single domain event onto the stream under test."""
    await redis_client.xadd(
        stream_name,
        {
            "event_id": f"evt-{event_type}",
            "event_type": event_type,
            "aggregate_id": "55",
            "event_data": json.dumps({"object_id": 55}),
            "occurred_at": "2024-06-15T10:30:00+00:00",
        },
    )


async def _pending_count(stream_client: StreamClient, stream_name: str) -> int:
    """Return the number of pending (unacked) entries for the consumer group."""
    entries = await stream_client.get_pending_entries(
        stream_name=stream_name,
        group_name=GROUP_NAME,
        min_idle_time_ms=0,
        count=10,
    )
    return len(entries)


def _consumer(
    stream_client: StreamClient, stream_name: str
) -> StravaWorkerStreamConsumer:
    return StravaWorkerStreamConsumer(
        stream_client=stream_client,
        session_factory=AsyncMock(),
        stream_name=stream_name,
        batch_size=1,
        block_ms=1000,
    )


@pytest.mark.asyncio
class TestStravaWorkerStreamConsumerIntegration:
    """Integration tests using real Redis for the Strava worker consumer."""

    async def test_strava_event_flows_through_stream_and_dispatches(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
    ) -> None:
        """A ``strava.`` event read from real Redis is dispatched and acked."""
        await _publish(redis_client, unique_stream_name, "strava.activity.created")

        consumer = _consumer(stream_client, unique_stream_name)
        consumer._handle_strava_event = AsyncMock()  # type: ignore[method-assign]
        consumer._routes = consumer._build_routes()
        await stream_client.ensure_consumer_group(unique_stream_name, GROUP_NAME)

        processed = await consumer._process_batch()

        assert processed == 1
        consumer._handle_strava_event.assert_awaited_once()
        assert await _pending_count(stream_client, unique_stream_name) == 0

    async def test_unmatched_event_acked_without_dispatch(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
    ) -> None:
        """A non-``strava.`` event is acked and the handler is never invoked."""
        await _publish(redis_client, unique_stream_name, "ContactCreated")

        consumer = _consumer(stream_client, unique_stream_name)
        consumer._handle_strava_event = AsyncMock()  # type: ignore[method-assign]
        await stream_client.ensure_consumer_group(unique_stream_name, GROUP_NAME)

        processed = await consumer._process_batch()

        assert processed == 1
        consumer._handle_strava_event.assert_not_awaited()
        assert await _pending_count(stream_client, unique_stream_name) == 0

    async def test_failing_handler_retried_via_pending_entries(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
    ) -> None:
        """A failing handler leaves the event pending, then a retry acks it."""
        await _publish(redis_client, unique_stream_name, "strava.activity.updated")

        call_count = 0

        async def flaky(_event: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")

        consumer = _consumer(stream_client, unique_stream_name)
        consumer._handle_strava_event = AsyncMock(side_effect=flaky)  # type: ignore[method-assign]
        consumer._routes = consumer._build_routes()
        consumer._retry_min_idle_ms = 0  # retry immediately for the test
        await stream_client.ensure_consumer_group(unique_stream_name, GROUP_NAME)

        await consumer._process_batch()
        assert await _pending_count(stream_client, unique_stream_name) == 1

        retried = await consumer._retry_pending()

        assert retried == 1
        assert call_count == 2
        assert await _pending_count(stream_client, unique_stream_name) == 0

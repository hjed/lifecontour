"""Integration tests for the SnipeItWorkerStreamConsumer route table.

ITER14-004 Phase 3. Exercises the declarative route table against **real
Redis**: publish a domain event to a Redis Stream, the consumer reads it,
dispatches matched events to the right handler, acks unmatched events without
dispatch, and retries a failing handler via pending entries.

Handler methods are patched so the test isolates routing/ack/retry semantics
from the Snipe-IT sync business logic (covered by the DB-backed
``test_stream_consumer_integration.py``).
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

from stream_consumer_tasks import SnipeItWorkerStreamConsumer

from .conftest import get_workspace_env

os.environ.setdefault(
    "REDIS_URL",
    f"redis://localhost:{get_workspace_env().get('REDIS_TEST_PORT', '6380')}",
)


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
    name = f"test:snipeit-consumer:{uuid.uuid4().hex[:8]}"
    yield name
    await redis_client.delete(name)


def _consumer(
    stream_client: StreamClient, stream_name: str
) -> SnipeItWorkerStreamConsumer:
    return SnipeItWorkerStreamConsumer(
        stream_client=stream_client,
        session_factory=AsyncMock(),
        stream_name=stream_name,
        batch_size=1,
        block_ms=1000,
    )


@pytest.mark.asyncio
class TestSnipeItWorkerRouteConsumerIntegration:
    """Integration tests using real Redis for the Snipe-IT worker consumer."""

    async def test_matched_event_flows_through_stream_and_dispatches(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
    ) -> None:
        """A ``GearItemUpdated`` event read from real Redis is dispatched + acked."""
        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": "evt-snipeit-1",
                "event_type": "GearItemUpdated",
                "aggregate_id": "55",
                "event_data": json.dumps({"gear_item_id": 55, "changed_fields": {}}),
                "occurred_at": "2024-06-15T10:30:00+00:00",
            },
        )

        consumer = _consumer(stream_client, unique_stream_name)
        gear = AsyncMock()
        consumer._handle_gear_item_updated = gear  # type: ignore[method-assign]
        consumer._routes = consumer._build_routes()
        await stream_client.ensure_consumer_group(unique_stream_name, "snipeit-worker")

        processed = await consumer._process_batch()

        assert processed == 1
        gear.assert_awaited_once()
        pending = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="snipeit-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending) == 0

    async def test_unmatched_event_acked_without_dispatch(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
    ) -> None:
        """A non-consumed event is acked and no handler is invoked."""
        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": "evt-snipeit-skip",
                "event_type": "ContactCreated",
                "aggregate_id": "99",
                "event_data": json.dumps({"contact_id": 1}),
                "occurred_at": "2024-06-15T10:30:00+00:00",
            },
        )

        consumer = _consumer(stream_client, unique_stream_name)
        gear = AsyncMock()
        journal = AsyncMock()
        webhook = AsyncMock()
        consumer._handle_gear_item_updated = gear  # type: ignore[method-assign]
        consumer._handle_journal_maintenance_event = journal  # type: ignore[method-assign]
        consumer._handle_webhook_received = webhook  # type: ignore[method-assign]
        consumer._routes = consumer._build_routes()
        await stream_client.ensure_consumer_group(unique_stream_name, "snipeit-worker")

        processed = await consumer._process_batch()

        assert processed == 1
        gear.assert_not_awaited()
        journal.assert_not_awaited()
        webhook.assert_not_awaited()
        pending = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="snipeit-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending) == 0

    async def test_failing_handler_retried_via_pending_entries(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
    ) -> None:
        """A failing handler leaves the event pending, then a retry acks it."""
        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": "evt-snipeit-retry",
                "event_type": "GearItemUpdated",
                "aggregate_id": "77",
                "event_data": json.dumps({"gear_item_id": 77, "changed_fields": {}}),
                "occurred_at": "2024-06-15T10:30:00+00:00",
            },
        )

        call_count = 0

        async def flaky(_event: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")

        consumer = _consumer(stream_client, unique_stream_name)
        consumer._handle_gear_item_updated = AsyncMock(side_effect=flaky)  # type: ignore[method-assign]
        consumer._routes = consumer._build_routes()
        consumer._retry_min_idle_ms = 0  # retry immediately for the test
        await stream_client.ensure_consumer_group(unique_stream_name, "snipeit-worker")

        await consumer._process_batch()
        pending_after_failure = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="snipeit-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending_after_failure) == 1

        retried = await consumer._retry_pending()

        assert retried == 1
        assert call_count == 2
        pending_after_retry = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="snipeit-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending_after_retry) == 0

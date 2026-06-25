"""Integration tests for the ImmichWorkerStreamConsumer (ITER14-004 Phase 2).

Exercises the declarative route table against **real Redis**: publish a domain
event to a Redis Stream, the consumer reads it, dispatches matched events to the
contact handler (injecting ``contact_id`` from ``aggregate_id``), acks unmatched
events without dispatch, and retries a failing handler via pending entries.

The worker handler is replaced with a fake ``worker`` module so the test
exercises stream + routing without instantiating ImmichWorkerSettings.
"""

from __future__ import annotations

import json
import os
import sys
import types
import uuid
from collections.abc import AsyncIterator, Generator
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import redis.asyncio as redis_async
from core_shared.stream_client import StreamClient

from stream_consumer_tasks import ImmichWorkerStreamConsumer

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
    name = f"test:immich-consumer:{uuid.uuid4().hex[:8]}"
    yield name
    await redis_client.delete(name)


@pytest.fixture
def fake_process_contact_event() -> Generator[AsyncMock, None, None]:
    """Inject a fake ``worker`` module exposing process_contact_event."""
    _sentinel = object()
    original = sys.modules.get("worker", _sentinel)

    mock = AsyncMock(return_value={"status": "success"})
    fake_worker = types.ModuleType("worker")
    fake_worker.process_contact_event = mock  # type: ignore[attr-defined]
    sys.modules["worker"] = fake_worker
    yield mock
    if original is _sentinel:
        sys.modules.pop("worker", None)
    else:
        sys.modules["worker"] = original  # type: ignore[assignment]


def _consumer(stream_client: StreamClient, stream_name: str, **kwargs: Any) -> Any:
    return ImmichWorkerStreamConsumer(
        stream_client=stream_client,
        session_factory=AsyncMock(),
        stream_name=stream_name,
        batch_size=1,
        block_ms=1000,
        **kwargs,
    )


@pytest.mark.asyncio
class TestImmichWorkerStreamConsumerIntegration:
    """Integration tests using real Redis for the Immich worker consumer."""

    async def test_contact_event_flows_through_stream_and_injects_contact_id(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
        fake_process_contact_event: AsyncMock,
    ) -> None:
        """ContactCreated read from real Redis → handler called with contact_id."""
        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": "evt-immich-1",
                "event_type": "ContactCreated",
                "aggregate_id": "55",
                "event_data": json.dumps({"user_id": 1}),
                "occurred_at": "2024-06-15T10:30:00+00:00",
            },
        )

        consumer = _consumer(stream_client, unique_stream_name)
        await stream_client.ensure_consumer_group(unique_stream_name, "immich-worker")

        processed = await consumer._process_batch()

        assert processed == 1
        fake_process_contact_event.assert_awaited_once_with(
            {"session_factory": consumer._session_factory, "job_id": "evt-immich-1"},
            "ContactCreated",
            {"user_id": 1, "contact_id": 55},
        )
        pending = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="immich-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending) == 0

    async def test_unmatched_event_acked_without_dispatch(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
        fake_process_contact_event: AsyncMock,
    ) -> None:
        """A non-contact event is acked and the handler is never invoked."""
        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": "evt-immich-skip",
                "event_type": "JournalCreated",
                "aggregate_id": "99",
                "event_data": json.dumps({"journal_id": 1}),
                "occurred_at": "2024-06-15T10:30:00+00:00",
            },
        )

        consumer = _consumer(stream_client, unique_stream_name)
        await stream_client.ensure_consumer_group(unique_stream_name, "immich-worker")

        processed = await consumer._process_batch()

        assert processed == 1
        fake_process_contact_event.assert_not_awaited()
        pending = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="immich-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending) == 0

    async def test_failing_handler_retried_via_pending_entries(
        self,
        stream_client: StreamClient,
        redis_client: Any,
        unique_stream_name: str,
        fake_process_contact_event: AsyncMock,
    ) -> None:
        """A failing handler leaves the event pending, then a retry acks it."""
        await redis_client.xadd(
            unique_stream_name,
            {
                "event_id": "evt-immich-retry",
                "event_type": "ContactUpdated",
                "aggregate_id": "77",
                "event_data": json.dumps({"user_id": 1}),
                "occurred_at": "2024-06-15T10:30:00+00:00",
            },
        )

        call_count = 0

        async def flaky(ctx: Any, event_type: str, event_data: Any) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")
            return {"status": "success"}

        fake_process_contact_event.side_effect = flaky

        consumer = _consumer(stream_client, unique_stream_name)
        consumer._retry_min_idle_ms = 0  # retry immediately for the test
        await stream_client.ensure_consumer_group(unique_stream_name, "immich-worker")

        await consumer._process_batch()
        pending_after_failure = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="immich-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending_after_failure) == 1

        retried = await consumer._retry_pending()

        assert retried == 1
        assert call_count == 2
        pending_after_retry = await stream_client.get_pending_entries(
            stream_name=unique_stream_name,
            group_name="immich-worker",
            min_idle_time_ms=0,
            count=10,
        )
        assert len(pending_after_retry) == 0

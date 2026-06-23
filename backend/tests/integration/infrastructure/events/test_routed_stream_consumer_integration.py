"""Integration tests for the declarative routed StreamConsumer against real Redis.

ITER14-004 Phase 1 adds a route table (event-type pattern -> handler) to
``core_shared``'s :class:`StreamConsumer`. These tests exercise the *generic*
routed consumer (no worker needed) end-to-end against a real Redis stream,
confirming the shared infrastructure dispatches matched events, acks unmatched
events immediately, and preserves retry-on-failure via pending entries.

Uses the real-Redis fixtures from this directory's ``conftest.py``
(``stream_client``, ``redis_client``, ``test_stream_name``).
"""

import uuid

import pytest
from core_shared.stream_client import StreamClient, StreamEvent
from core_shared.stream_consumer import EventRoute, StreamConsumer
from redis.asyncio import Redis

GROUP_NAME = "routed-consumer-test"
CONSUMER_NAME = "routed-consumer-1"


def _build_consumer(
    stream_client: StreamClient,
    test_stream_name: str,
    routes: list[EventRoute],
    *,
    retry_min_idle_ms: int = 60000,
) -> StreamConsumer:
    return StreamConsumer(
        stream_client=stream_client,
        stream_name=test_stream_name,
        group_name=GROUP_NAME,
        consumer_name=CONSUMER_NAME,
        routes=routes,
        block_ms=100,
        retry_min_idle_ms=retry_min_idle_ms,
    )


class TestRoutedStreamConsumerIntegration:
    """The generic routed consumer against a real Redis stream."""

    @pytest.mark.asyncio
    async def test_matched_event_dispatched_and_acked(
        self,
        test_stream_name: str,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A matched event is routed to its handler and acknowledged (0 pending)."""
        handled: list[StreamEvent] = []

        async def handle_contact(event: StreamEvent) -> None:
            handled.append(event)

        consumer = _build_consumer(
            stream_client,
            test_stream_name,
            [EventRoute("ContactCreated", handle_contact)],
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42},
            occurred_at="2024-01-01T12:00:00Z",
        )

        processed = await consumer._process_batch()

        assert processed == 1
        assert [e.event_type for e in handled] == ["ContactCreated"]
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_unmatched_event_acked_without_dispatch(
        self,
        test_stream_name: str,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """An event matching no route is acked immediately and never dispatched."""
        handled: list[StreamEvent] = []

        async def handle_contact(event: StreamEvent) -> None:
            handled.append(event)

        consumer = _build_consumer(
            stream_client,
            test_stream_name,
            [EventRoute("ContactCreated", handle_contact)],
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="JournalCreated",
            aggregate_id=7,
            event_data={"journal_id": 7},
            occurred_at="2024-01-01T12:00:00Z",
        )

        processed = await consumer._process_batch()

        assert processed == 1
        assert handled == []
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_failing_handler_retried_via_pending_entries(
        self,
        test_stream_name: str,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A handler that fails first leaves the event pending; a retry succeeds and acks."""
        attempts: list[str] = []

        async def flaky_handler(event: StreamEvent) -> None:
            attempts.append(event.event_id)
            if len(attempts) == 1:
                raise RuntimeError("transient failure")

        # retry_min_idle_ms=0 lets the retry claim the pending entry immediately.
        consumer = _build_consumer(
            stream_client,
            test_stream_name,
            [EventRoute("ContactCreated", flaky_handler)],
            retry_min_idle_ms=0,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="ContactCreated",
            aggregate_id=99,
            event_data={"contact_id": 99},
            occurred_at="2024-01-01T12:00:00Z",
        )

        # First delivery: handler raises, event stays pending (unacked).
        await consumer._process_batch()
        pending_after_failure = await redis_client.xpending(
            test_stream_name, GROUP_NAME
        )
        assert pending_after_failure["pending"] == 1
        assert len(attempts) == 1

        # Retry cycle: pending entry is reclaimed and reprocessed successfully.
        retried = await consumer._retry_pending()

        assert retried == 1
        assert len(attempts) == 2
        pending_after_retry = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_after_retry["pending"] == 0

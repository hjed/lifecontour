"""Driving the history projection by hand, for the end-to-end projection tests.

Every test that asserts "a real write reaches ``field_history``" has to do the
same three things the running application does asynchronously: relay the outbox
to the stream, run one batch of the consumer, and — for the idempotency half —
hand the consumer the same entries a second time as a redelivery would.

They live here rather than in each file because the journal (ITER12-002) and task
(ITER18-003) end-to-end tests drive the identical machinery, and a second copy is
a second place for "how the projection is exercised" to drift from the consumer
it is exercising. They are *not* fixtures: two of the three take the consumer
name as an argument, and a fixture would have to invent one.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)
from app.infrastructure.events.outbox_relay import OutboxRelay

GROUP_NAME = "history-projection"


def patched_projection_engine(async_connection: AsyncConnection) -> Any:
    """Patch the projection consumer's engine to yield the test connection.

    Keeps the consumer's writes on the test ``async_connection`` so they share the
    test savepoint and roll back at teardown.
    """
    mock_engine = MagicMock()

    @asynccontextmanager
    async def mock_begin() -> AsyncIterator[AsyncConnection]:
        yield async_connection

    mock_engine.begin = mock_begin

    return patch(
        "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
        return_value=mock_engine,
    )


async def relay_and_project(
    stream_client: StreamClient,
    stream_name: str,
    async_connection: AsyncConnection,
    consumer_name: str,
) -> None:
    """Relay outbox events to the stream and run the projection consumer once."""
    relay = OutboxRelay(
        stream_client=stream_client, stream_name=stream_name, batch_size=50
    )
    await relay.relay_batch(async_connection)

    consumer = HistoryProjectionConsumer(
        stream_client=stream_client,
        stream_name=stream_name,
        consumer_name=consumer_name,
        block_ms=100,
        # Matched to the relay above, and not left at the production default of
        # ten. One ``_process_batch()`` reads at most this many messages, so a
        # scenario that publishes more loses the tail — silently, as a *missing*
        # history row rather than an error. That is exactly how it was found:
        # driving a merge through the task lifecycle test added two journal
        # events, pushed the run to eleven, and the task's delete marker
        # disappeared with the row count still looking plausible.
        batch_size=50,
    )
    await stream_client.ensure_consumer_group(stream_name, GROUP_NAME)

    with patched_projection_engine(async_connection):
        await consumer._process_batch()


async def replay_stream_through_projection(
    stream_client: StreamClient,
    stream_name: str,
    async_connection: AsyncConnection,
    redis_client: Redis,
) -> None:
    """Re-project every entry already on the stream, as a redelivery would.

    Redis Streams are at-least-once: a consumer restart, or a pending message
    reclaimed by ``XAUTOCLAIM``, hands the projection an event it has already
    processed. Replaying the raw entries through ``_handle_event`` leaves the
    ``event_id`` dedup index as the only thing preventing duplicate rows.
    """
    consumer = HistoryProjectionConsumer(
        stream_client=stream_client,
        stream_name=stream_name,
        consumer_name="test-replay",
        block_ms=100,
    )

    # redis-py types xrange's entries as optionally-None pairs; a stream that has
    # been relayed to always yields real ones, so skip anything else rather than
    # silently replaying a half-empty message.
    entries = await redis_client.xrange(stream_name) or []
    with patched_projection_engine(async_connection):
        for message_id, fields in entries:
            if message_id is None or fields is None:
                continue
            await consumer._handle_event(
                stream_client._parse_message(message_id, dict(fields))
            )

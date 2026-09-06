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

The two steps that are not projection-specific — patching a consumer module's
engine onto the test connection, and relaying the outbox — moved to
``consumer_harness`` when the summary-invalidation consumer needed them too
(ITER18-005 Phase 7). What is left here is the projection's own binding of them.
"""

from typing import Any

from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)
from tests.integration.infrastructure.events.consumer_harness import (
    BATCH_SIZE,
    patched_consumer_engine,
    relay_outbox,
)

GROUP_NAME = "history-projection"
_CONSUMER_MODULE = "app.infrastructure.events.history_projection_consumer"


def patched_projection_engine(async_connection: AsyncConnection) -> Any:
    """Patch the projection consumer's engine to yield the test connection."""
    return patched_consumer_engine(_CONSUMER_MODULE, async_connection)


async def relay_and_project(
    stream_client: StreamClient,
    stream_name: str,
    async_connection: AsyncConnection,
    consumer_name: str,
) -> None:
    """Relay outbox events to the stream and run the projection consumer once."""
    await relay_outbox(stream_client, stream_name, async_connection)

    consumer = HistoryProjectionConsumer(
        stream_client=stream_client,
        stream_name=stream_name,
        consumer_name=consumer_name,
        block_ms=100,
        batch_size=BATCH_SIZE,
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

"""Driving a stream consumer by hand, for the end-to-end consumer tests.

Every test that asserts "a real write reaches the other side of the stream" does
the same two things the running application does asynchronously: relay the
outbox to the stream, then run one batch of the consumer against the test's own
connection so its writes share the test savepoint and roll back at teardown.

Those two steps are here, and the per-consumer harnesses bind them:
``projection_harness`` for ``field_history``, and the summary-invalidation suite
for ``journal_daily_summaries``. Extracted when the second consumer needed them
(ITER18-005 Phase 7) rather than copied, which is the call ITER18-001 Phase 7
made about test helpers and what the duplication gate exists to catch — the two
would otherwise be near-identical functions differing only in a class name.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

from core_shared.stream_client import StreamClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.outbox_relay import OutboxRelay

#: Matched to the relay's batch size below, and deliberately not the production
#: default of ten. One ``_process_batch()`` reads at most this many messages, so
#: a scenario publishing more loses the tail — silently, as a *missing* row
#: rather than an error. That is how it was found: driving a merge through the
#: task lifecycle test added two journal events, pushed the run to eleven, and
#: the task's delete marker disappeared with the row count still looking
#: plausible.
BATCH_SIZE = 50


def patched_consumer_engine(module_name: str, async_connection: AsyncConnection) -> Any:
    """Patch a consumer module's engine to yield the test connection.

    Keeps the consumer's writes on the test ``async_connection`` so they share
    the test savepoint and roll back at teardown, rather than committing through
    an independent connection of their own.

    Args:
        module_name: The consumer module whose ``get_async_database_engine`` to
            patch, e.g. ``app.infrastructure.events.summary_invalidation_consumer``
        async_connection: The test's connection
    """
    mock_engine = MagicMock()

    @asynccontextmanager
    async def mock_begin() -> AsyncIterator[AsyncConnection]:
        yield async_connection

    mock_engine.begin = mock_begin

    return patch(
        f"{module_name}.get_async_database_engine",
        return_value=mock_engine,
    )


async def relay_outbox(
    stream_client: StreamClient,
    stream_name: str,
    async_connection: AsyncConnection,
) -> None:
    """Publish everything the test's writes put in the outbox to the stream."""
    relay = OutboxRelay(
        stream_client=stream_client, stream_name=stream_name, batch_size=BATCH_SIZE
    )
    await relay.relay_batch(async_connection)

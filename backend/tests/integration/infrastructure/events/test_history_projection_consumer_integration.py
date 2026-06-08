"""Integration tests for HistoryProjectionConsumer.

End-to-end flow: Redis stream -> consumer -> HistoryService projection ->
field_history rows. Validates correct row content/grouping, idempotent
redelivery (no duplicate rows), deletion-safe route grouping, and dead-lettering
of malformed events. Mirrors test_search_indexer_consumer_integration.py.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)

GROUP_NAME = "history-projection"
OCCURRED_AT = "2024-03-01T08:00:00+00:00"


def _patched_engine(async_connection: AsyncConnection) -> MagicMock:
    """Build a mock engine whose .begin() yields the test transaction."""
    mock_engine = MagicMock()

    @asynccontextmanager
    async def mock_begin():
        yield async_connection

    mock_engine.begin = mock_begin
    return mock_engine


async def _count_history(
    conn: AsyncConnection, *, entity_type: str, entity_id: int
) -> int:
    result = await conn.execute(
        text(
            "SELECT COUNT(*) FROM field_history "
            "WHERE entity_type = :et AND entity_id = :ei"
        ),
        {"et": entity_type, "ei": entity_id},
    )
    return int(result.scalar_one())


class TestHistoryProjectionConsumerIntegration:
    """Integration tests for HistoryProjectionConsumer with real Redis/Postgres."""

    @pytest.mark.asyncio
    async def test_projects_journal_updated_into_field_history(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A JournalUpdated with two changed fields writes two history rows,
        tagged to the journal, carrying provenance and occurred_at."""
        journal_id = 770001
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="JournalUpdated",
            aggregate_id=journal_id,
            event_data={
                "journal_id": journal_id,
                "changed_fields": {"title": ["Old", "New"], "body": ["a", "b"]},
                "source": "ui",
                "changed_by": "ui",
            },
            occurred_at=OCCURRED_AT,
        )

        consumer = HistoryProjectionConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-history-1",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            count = await consumer._process_batch()

        assert count == 1
        assert (
            await _count_history(
                async_connection, entity_type="journal", entity_id=journal_id
            )
            == 2
        )

        rows = await async_connection.execute(
            text(
                "SELECT field_name, old_value, new_value, source, changed_by, "
                "created_at FROM field_history WHERE entity_id = :ei "
                "ORDER BY field_name"
            ),
            {"ei": journal_id},
        )
        records = rows.fetchall()
        by_field = {r.field_name: r for r in records}
        assert by_field["title"].old_value == "Old"
        assert by_field["title"].new_value == "New"
        assert by_field["body"].old_value == "a"
        assert by_field["title"].source == "ui"
        assert by_field["title"].changed_by == "ui"
        # created_at reflects the event time, not wall-clock at projection.
        assert by_field["title"].created_at.isoformat() == OCCURRED_AT

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_redelivery_writes_no_duplicate_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Re-delivering the same event (same event_id) must not duplicate rows."""
        journal_id = 770002
        event_id = f"evt-{uuid.uuid4().hex[:8]}"
        event_data = {
            "journal_id": journal_id,
            "changed_fields": {"title": ["Old", "New"]},
            "source": "ui",
            "changed_by": "ui",
        }
        # Publish the SAME event twice (two stream messages, identical event_id).
        for _ in range(2):
            await stream_client.publish(
                stream_name=test_stream_name,
                event_id=event_id,
                event_type="JournalUpdated",
                aggregate_id=journal_id,
                event_data=event_data,
                occurred_at=OCCURRED_AT,
            )

        consumer = HistoryProjectionConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-history-2",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            await consumer._process_batch()

        # Idempotent: the duplicate delivery hit ON CONFLICT DO NOTHING.
        assert (
            await _count_history(
                async_connection, entity_type="journal", entity_id=journal_id
            )
            == 1
        )
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_route_deleted_groups_to_journal_without_route_row(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """RouteDeleted history is tagged to the journal, surviving route deletion."""
        journal_id = 770003
        route_id = str(uuid.uuid4())
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="RouteDeleted",
            aggregate_id=1,
            event_data={
                "route_id": route_id,
                "journal_id": journal_id,
                "source": "ui",
                "changed_by": "ui",
            },
            occurred_at=OCCURRED_AT,
        )

        consumer = HistoryProjectionConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-history-3",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            await consumer._process_batch()

        row = await async_connection.execute(
            text(
                "SELECT entity_type, entity_id, field_name FROM field_history "
                "WHERE entity_id = :ei"
            ),
            {"ei": journal_id},
        )
        record = row.fetchone()
        assert record is not None
        assert record.entity_type == "journal"
        assert record.entity_id == journal_id
        assert record.field_name == f"route:{route_id}:__deleted__"

    @pytest.mark.asyncio
    async def test_legacy_route_event_without_journal_id_is_skipped_not_dead_lettered(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A pre-enrichment RouteUpdated (no journal_id), replayed because the
        group reads from id 0, is acked and writes nothing — it must NOT flood
        the DLQ."""
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="RouteUpdated",
            aggregate_id=1,
            event_data={
                "route_id": str(uuid.uuid4()),
                "changed_fields": {"name": ["Old", "New"]},
                "source": "ui",
                "changed_by": "ui",
            },
            occurred_at=OCCURRED_AT,
        )

        consumer = HistoryProjectionConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-history-legacy",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            count = await consumer._process_batch()

        assert count == 1
        # Acknowledged (not left pending for retry / dead-lettering).
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_malformed_event_is_dead_lettered(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """An event that fails projection is retried then persisted to the DLQ."""
        event_id = f"evt-{uuid.uuid4().hex[:8]}"
        # Missing journal_id -> project_event raises KeyError -> handler fails.
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=event_id,
            event_type="JournalUpdated",
            aggregate_id=0,
            event_data={
                "changed_fields": {"title": ["Old", "New"]},
                "source": "ui",
                "changed_by": "ui",
            },
            occurred_at=OCCURRED_AT,
        )

        consumer = HistoryProjectionConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-history-4",
            block_ms=100,
        )
        # Dead-letter on the first retry: claim immediately, one failed delivery.
        consumer._retry_min_idle_ms = 0
        consumer._max_delivery_count = 1
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        engine = _patched_engine(async_connection)
        with (
            patch(
                "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
                return_value=engine,
            ),
            patch(
                "app.infrastructure.events.dead_letter_consumer_mixin.get_async_database_engine",
                return_value=engine,
            ),
        ):
            # First delivery fails and stays pending.
            await consumer._process_batch()
            # Retry sees delivery_count >= max and dead-letters it.
            await consumer._retry_pending()

        dlq = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM dead_letter_events "
                "WHERE event_id = :eid AND consumer_group = :g"
            ),
            {"eid": event_id, "g": GROUP_NAME},
        )
        assert int(dlq.scalar_one()) == 1

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

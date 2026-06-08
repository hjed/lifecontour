"""End-to-end backend integration test for journal history projection.

Exercises the full async chain a real journal mutation travels:

    JournalService.update_journal()
        -> OutboxEventPublisher (outbox_events row, same txn)
        -> OutboxRelay.relay_batch()  (-> pms:domain-events stream)
        -> HistoryProjectionConsumer  (-> field_history rows)

and asserts the change is retrievable, correctly grouped to the journal, with
the right old/new values and provenance. This is the closest backend equivalent
to a user-facing E2E for ITER12-002 Phase 1 (which has no UI surface yet).
"""

from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals import EventDateRange, Journal
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.events.outbox_relay import OutboxRelay

GROUP_NAME = "history-projection"


@pytest.mark.integration
class TestJournalHistoryProjectionE2E:
    @pytest.mark.asyncio
    async def test_journal_update_is_projected_to_retrievable_history(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        journal_service = JournalService(
            journal_repo=SqlJournalRepository(async_connection),
            event_publisher=OutboxEventPublisher(async_connection),
        )

        # 1. Create then update a journal through the real service (UI provenance).
        journal = Journal(
            id=None,
            user_id="user-e2e",
            title="Original title",
            content="c",
            event_date_range=EventDateRange(
                start=datetime(2024, 1, 1), end=datetime(2024, 1, 1)
            ),
        )
        created = await journal_service.create_journal(
            journal, async_connection, changed_by="ui", source=Provenance.UI
        )
        assert created.id is not None
        journal_id = created.id

        created.title = "Updated title"
        await journal_service.update_journal(
            created,
            {"title": ("Original title", "Updated title")},
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )

        # 2. Relay the outbox events to the Redis stream.
        relay = OutboxRelay(
            stream_client=stream_client,
            stream_name=test_stream_name,
            batch_size=50,
        )
        relayed = await relay.relay_batch(async_connection)
        assert relayed >= 2  # JournalCreated + JournalUpdated

        # 3. Consume the stream and project into field_history.
        consumer = HistoryProjectionConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-history-e2e",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield async_connection

        mock_engine.begin = mock_begin

        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=mock_engine,
        ):
            await consumer._process_batch()

        # 4. History is retrievable via the journal aggregation strategy.
        history_repo = SqlFieldHistoryRepository(async_connection)
        entries = await history_repo.get_history_for_aggregate(
            "journal", journal_id, limit=50, offset=0
        )

        by_field = {e.field_name: e for e in entries}
        # The create marker and the title change are both present and grouped.
        assert "__created__" in by_field
        assert "title" in by_field

        title_entry = by_field["title"]
        assert title_entry.entity_type == "journal"
        assert title_entry.entity_id == journal_id
        assert title_entry.old_value == "Original title"
        assert title_entry.new_value == "Updated title"
        assert title_entry.source == Provenance.UI
        assert title_entry.changed_by == "ui"

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

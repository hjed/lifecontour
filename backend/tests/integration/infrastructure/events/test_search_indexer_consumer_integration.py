"""
Integration tests for SearchIndexerConsumer.

Tests the end-to-end flow: Redis stream -> consumer -> SearchIndexer delegation.
Validates that events flow correctly from Redis Streams through the consumer
and that the SearchIndexer is invoked with a properly adapted OutboxEvent.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.search_indexer_consumer import SearchIndexerConsumer
from tests.integration.contact_seeding import seed_contact

GROUP_NAME = "search-indexer"


class TestSearchIndexerConsumerIntegration:
    """Integration tests for SearchIndexerConsumer with real Redis and Postgres."""

    @pytest.mark.asyncio
    async def test_search_indexer_consumer_processes_contact_event(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Verify the consumer reads a ContactCreated event from Redis, adapts it,
        and delegates to SearchIndexer.process_event with the correct OutboxEvent."""
        # 1. Arrange: Insert a real contact into the database so the indexer can find it
        contact_id = 9999
        await seed_contact(
            async_connection,
            contact_id=contact_id,
            first_name="SearchIntegration",
            last_name="TestContact",
        )

        # Publish the event to the stream
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="ContactCreated",
            aggregate_id=contact_id,
            event_data={"contact_id": contact_id},
            occurred_at="2024-01-01T12:00:00Z",
        )

        # 2. Setup the consumer
        consumer = SearchIndexerConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-indexer-1",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        # Mock the engine so the consumer uses our test transaction connection
        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield async_connection

        mock_engine.begin = mock_begin

        # Mock the SearchIndexer to verify delegation without needing MeiliSearch
        mock_indexer = MagicMock()
        mock_indexer.process_event = AsyncMock()

        # 3. Act: Process the batch
        with (
            patch(
                "app.infrastructure.events.search_indexer_consumer.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.search_indexer_consumer.SearchIndexer",
                return_value=mock_indexer,
            ),
        ):
            count = await consumer._process_batch()

        # 4. Assert: Event was processed from the stream
        assert count == 1

        # Verify pending entries are 0 (all acknowledged)
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

        # Verify SearchIndexer was called with the adapted OutboxEvent
        mock_indexer.process_event.assert_called_once()
        call_args = mock_indexer.process_event.call_args[0]
        outbox_event = call_args[0]
        assert outbox_event.event_type == "ContactCreated"
        assert outbox_event.event_data["contact_id"] == contact_id

    @pytest.mark.asyncio
    async def test_consumer_processes_journal_event_and_only_indexes_it(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A journal event is indexed here and invalidates no summary.

        It did both until ITER18-005 Phase 7 moved summary freshness to
        ``SummaryInvalidationConsumer``; this is the same test asserting the
        half that remains, plus the absence of the half that left.
        """
        journal_id = 8888

        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="JournalCreated",
            aggregate_id=journal_id,
            event_data={"journal_id": journal_id},
            occurred_at="2024-01-01T12:00:00Z",
        )

        consumer = SearchIndexerConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-indexer-journal",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield async_connection

        mock_engine.begin = mock_begin

        mock_indexer = MagicMock()
        mock_indexer.process_event = AsyncMock()

        with (
            patch(
                "app.infrastructure.events.search_indexer_consumer.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.search_indexer_consumer.SearchIndexer",
                return_value=mock_indexer,
            ),
        ):
            count = await consumer._process_batch()

        assert count == 1

        # SearchIndexer was called
        mock_indexer.process_event.assert_called_once()

        # And nothing else: the invalidation this handler used to perform is
        # gone from the object, not merely unexercised by this test.
        assert not hasattr(consumer, "_invalidate_daily_summary")

        # Acknowledged
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_consumer_acknowledges_irrelevant_events(
        self,
        test_stream_name: str,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Verify the consumer acknowledges and skips events it shouldn't process."""
        # Publish an irrelevant event (contact sync, not a domain event)
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="contact.created",
            aggregate_id=1,
            event_data={"contact_id": 1},
            occurred_at="2024-01-01T12:00:00Z",
        )

        consumer = SearchIndexerConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-indexer-2",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        # Mock SearchIndexer to verify it's NOT called
        with patch(
            "app.infrastructure.events.search_indexer_consumer.SearchIndexer"
        ) as mock_indexer:
            count = await consumer._process_batch()

        # It processed the batch (read the event)
        assert count == 1
        # But it didn't call the search indexer
        mock_indexer.assert_not_called()

        # And it acknowledged the event
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

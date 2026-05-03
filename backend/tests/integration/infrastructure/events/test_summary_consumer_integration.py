"""
Integration tests for SummaryConsumer.

Tests the end-to-end flow: Redis stream -> consumer -> Summary Generation -> Search Index.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.summary_consumer import SummaryConsumer

GROUP_NAME = "summary-generator"


class TestSummaryConsumerIntegration:
    """Integration tests for SummaryConsumer."""

    @pytest.mark.asyncio
    async def test_summary_consumer_processes_refresh_event(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Verify the consumer processes ContactSummaryRefreshRequested and delegates generation."""
        # 1. Arrange: Insert a real contact
        contact_id = 9998
        await async_connection.execute(
            text(
                """
                INSERT INTO contacts (id, first_name, last_name, created_at, updated_at)
                VALUES (:id, 'Summary', 'Target', NOW(), NOW())
                """
            ),
            {"id": contact_id},
        )

        # Publish the event to the stream
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="ContactSummaryRefreshRequested",
            aggregate_id=contact_id,
            event_data={"contact_id": contact_id},
            occurred_at="2024-01-01T12:00:00Z",
        )

        # 2. Setup the consumer
        consumer = SummaryConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-summary-1",
            block_ms=100,
            container=MagicMock(),
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        # Mock the engine so the consumer uses our test transaction connection
        mock_engine = MagicMock()
        mock_engine.begin = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            # Yield the test connection instead of starting a new transaction
            yield async_connection

        mock_engine.begin.side_effect = mock_begin

        # Mock the actual SummaryGenerator.generate call to avoid real Gemini API calls
        mock_generator = MagicMock()
        mock_result = MagicMock()
        mock_result.status.value = "generated"
        mock_generator.generate = AsyncMock(return_value=mock_result)

        mock_settings = MagicMock()
        mock_settings.gemini_api_key = "fake-key-for-test"
        mock_settings.gemini_summary_model = "fake-model"

        # 3. Act: Process the batch
        with (
            patch(
                "app.infrastructure.events.summary_consumer.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.core.contacts.services.summary_generation_service.SummaryGenerator",
                return_value=mock_generator,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.SearchIndexer"
            ) as mock_indexer_cls,
        ):
            mock_indexer = MagicMock()
            mock_indexer.process_event = AsyncMock()
            mock_indexer_cls.return_value = mock_indexer

            count = await consumer._process_batch()

            # 4. Assert: Event was processed
            assert count == 1

            # Verify pending entries are 0 (acknowledged)
            pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
            assert pending_info["pending"] == 0

            # Verify generate was called with our contact
            mock_generator.generate.assert_called_once_with(contact_id=contact_id)

            # Verify search indexer was called after summary generation
            mock_indexer.process_event.assert_called_once()
            call_args = mock_indexer.process_event.call_args[0]
            assert call_args[0].event_type == "ContactSummaryRefreshRequested"

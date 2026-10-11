"""
Integration tests for InboundEventConsumer.

Tests the end-to-end flow: Redis stream -> consumer -> domain processor delegation.
Validates that events flow correctly from Redis Streams through the consumer
and that the appropriate domain processor is invoked with the adapted OutboxEvent.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.timezone_utils import DEFAULT_TIMEZONE
from app.infrastructure.config import Settings
from app.infrastructure.events.inbound_event_consumer import InboundEventConsumer
from tests.integration.contact_seeding import TEST_USER_ID
from tests.integration.infrastructure.events.user_settings_rows import (
    save_newer_timezone_for_other_user,
    save_timezone,
)


@pytest.fixture
def mock_settings() -> MagicMock:
    """Create mock Settings for the consumer."""
    settings = MagicMock(spec=Settings)
    settings.gemini_api_key = ""
    settings.gemini_model = "gemini-3.5-flash-lite"
    return settings


GROUP_NAME = "inbound-processor"


class TestInboundEventConsumerIntegration:
    """Integration tests for InboundEventConsumer with real Redis and Postgres."""

    @pytest.mark.asyncio
    async def test_consumer_processes_contact_created_event(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
        mock_settings: MagicMock,
    ) -> None:
        """Verify the consumer reads a contact.created event from Redis
        and delegates to OutboxEventProcessor."""
        # 1. Arrange: Publish a contact.created event
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="contact.created",
            aggregate_id=1,
            event_data={
                "integration_source": "google",
                "external_id": "people/c123",
                "contact_data": {"first_name": "Test", "last_name": "Contact"},
                "sync_timestamp": "2024-01-01T10:00:00Z",
                "sync_type": "created",
                "etag": "etag123",
            },
            occurred_at="2024-01-01T12:00:00Z",
        )

        # 2. Setup the consumer
        mock_container = MagicMock()
        consumer = InboundEventConsumer(
            stream_client=stream_client,
            container=mock_container,
            settings=mock_settings,
            stream_name=test_stream_name,
            consumer_name="test-inbound-1",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        # Mock the engine so the consumer uses our test connection. The
        # consumer opens engine.connect() and owns the outermost unit_of_work;
        # async_connection carries EXTERNAL_TRANSACTION_MARKER, so the unit of
        # work uses a SAVEPOINT and the test transaction survives for rollback.
        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_connect():
            yield async_connection

        mock_engine.connect = mock_connect

        # Mock the OutboxEventProcessor to verify delegation
        mock_processor = AsyncMock()
        mock_processor.process_event = AsyncMock(
            return_value={"status": "success", "contact_id": 123}
        )

        # 3. Act: Process the batch
        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.core.integrations.outbox_event_processor.OutboxEventProcessor",
                return_value=mock_processor,
            ),
        ):
            count = await consumer._process_batch()

        # 4. Assert: Event was processed from the stream
        assert count == 1

        # Verify pending entries are 0 (all acknowledged)
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

        # Verify OutboxEventProcessor was called with the adapted OutboxEvent
        mock_processor.process_event.assert_called_once()
        call_args = mock_processor.process_event.call_args[0]
        outbox_event = call_args[0]
        assert outbox_event.event_type == "contact.created"
        assert outbox_event.event_data["integration_source"] == "google"

    @pytest.mark.asyncio
    async def test_consumer_processes_journal_event(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
        mock_settings: MagicMock,
    ) -> None:
        """Verify journal_event.created events delegate to JournalOutboxEventProcessor."""
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="journal_event.created",
            aggregate_id=1,
            event_data={
                "journal_id": 1,
                "user_id": "user123",
                "title": "Test Journal",
            },
            occurred_at="2024-01-01T12:00:00Z",
        )

        mock_container = MagicMock()
        consumer = InboundEventConsumer(
            stream_client=stream_client,
            container=mock_container,
            settings=mock_settings,
            stream_name=test_stream_name,
            consumer_name="test-inbound-journal",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_connect():
            yield async_connection

        mock_engine.connect = mock_connect

        mock_journal_processor = AsyncMock()
        mock_journal_processor.process_event = AsyncMock(
            return_value={"status": "success"}
        )

        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.core.integrations.journal_outbox_event_processor.JournalOutboxEventProcessor",
                return_value=mock_journal_processor,
            ),
        ):
            count = await consumer._process_batch()

        assert count == 1
        mock_journal_processor.process_event.assert_called_once()

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_consumer_acknowledges_irrelevant_events(
        self,
        test_stream_name: str,
        stream_client: StreamClient,
        redis_client: Redis,
        mock_settings: MagicMock,
    ) -> None:
        """Verify the consumer acknowledges and skips events it shouldn't process."""
        # Publish an irrelevant event (domain event, not a sync event)
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="ContactCreated",
            aggregate_id=1,
            event_data={"contact_id": 1},
            occurred_at="2024-01-01T12:00:00Z",
        )

        mock_container = MagicMock()
        consumer = InboundEventConsumer(
            stream_client=stream_client,
            container=mock_container,
            settings=mock_settings,
            stream_name=test_stream_name,
            consumer_name="test-inbound-skip",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        count = await consumer._process_batch()

        # It processed the batch (read the event)
        assert count == 1

        # And it acknowledged the event without processing
        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0


class TestInboundEventConsumerOwnerTimezone:
    """Match detection renders times in the event owner's stored timezone.

    Another user always holds the most recently updated settings row, which is
    what a lookup without a user would have picked.
    """

    async def _assessor_timezone(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> str:
        """Consume a detect_matches event owned by TEST_USER_ID.

        Returns the timezone the title-similarity assessor was built with.
        """
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="journal_review.detect_matches",
            aggregate_id=1,
            event_data={
                "journal_id": 1,
                "user_id": TEST_USER_ID,
                "journal_title": "Morning climb",
                "event_date_range_start": "2024-01-01T10:00:00Z",
                "event_date_range_end": "2024-01-01T11:00:00Z",
                "created_at": "2024-01-01T11:30:00Z",
            },
            occurred_at="2024-01-01T12:00:00Z",
        )

        settings = MagicMock(spec=Settings)
        settings.gemini_api_key = "fake-key-for-test"
        settings.gemini_model = "gemini-3.5-flash-lite"
        consumer = InboundEventConsumer(
            stream_client=stream_client,
            container=MagicMock(),
            settings=settings,
            stream_name=test_stream_name,
            consumer_name="test-inbound-timezone",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_connect():
            yield async_connection

        mock_engine.connect = mock_connect

        mock_processor = AsyncMock()
        mock_processor.process_event = AsyncMock(return_value={"status": "success"})

        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_engine,
            ),
            patch(
                "app.core.integrations.match_detection_event_processor.MatchDetectionEventProcessor",
                return_value=mock_processor,
            ),
            patch(
                "app.core.journal.services.title_similarity_assessor.GeminiTitleSimilarityAssessor"
            ) as assessor_cls,
        ):
            assert await consumer._process_batch() == 1

        mock_processor.process_event.assert_called_once()
        return str(assessor_cls.call_args.kwargs["timezone"])

    @pytest.mark.asyncio
    async def test_detect_matches_uses_event_owner_timezone(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The owner's configured zone is used, not the other user's newer one."""
        await save_timezone(async_connection, TEST_USER_ID, "Australia/Sydney")
        await save_newer_timezone_for_other_user(async_connection)

        zone = await self._assessor_timezone(
            test_stream_name, async_connection, stream_client
        )

        assert zone == "Australia/Sydney"

    @pytest.mark.asyncio
    async def test_detect_matches_owner_without_settings_gets_default_timezone(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """An owner who never configured a zone gets the default, not another user's."""
        await save_newer_timezone_for_other_user(async_connection)

        zone = await self._assessor_timezone(
            test_stream_name, async_connection, stream_client
        )

        assert zone == DEFAULT_TIMEZONE

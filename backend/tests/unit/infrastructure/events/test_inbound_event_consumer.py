"""
Unit tests for InboundEventConsumer.

Tests event routing, filtering, and the _handle_event integration with
OutboxEventProcessor and JournalOutboxEventProcessor for the
inbound-processor consumer group.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient, StreamEvent

from app.infrastructure.config import Settings
from app.infrastructure.events.inbound_event_consumer import InboundEventConsumer


def _make_stream_event(
    event_type: str = "contact.created",
    event_data: dict[str, Any] | None = None,
    aggregate_id: int = 42,
) -> StreamEvent:
    """Create a StreamEvent for testing."""
    return StreamEvent(
        message_id="1234567890-0",
        event_id="evt-test-123",
        event_type=event_type,
        aggregate_id=aggregate_id,
        event_data=event_data or {"contact_id": 42},
        occurred_at="2024-06-15T10:30:00+00:00",
    )


class TestInboundEventConsumerEventMatching:
    """Test event type pattern matching for the inbound event consumer."""

    @pytest.fixture
    def consumer(self) -> InboundEventConsumer:
        """Create an InboundEventConsumer with a mock stream client."""
        mock_client = MagicMock(spec=StreamClient)
        mock_container = MagicMock()
        mock_settings = MagicMock(spec=Settings)
        return InboundEventConsumer(
            stream_client=mock_client,
            container=mock_container,
            settings=mock_settings,
            stream_name="pms:domain-events",
        )

    @pytest.mark.parametrize(
        "event_type",
        [
            "contact.created",
            "contact.updated",
            "contact.deleted",
        ],
    )
    def test_matches_contact_sync_events(
        self, consumer: InboundEventConsumer, event_type: str
    ) -> None:
        """Verify contact sync events are matched (prefix match on 'contact.')."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "journal_event.created",
            "journal_event.updated",
            "journal_event.deleted",
            "journal_event.series_cancelled",
        ],
    )
    def test_matches_journal_event_sync_events(
        self, consumer: InboundEventConsumer, event_type: str
    ) -> None:
        """Verify journal_event sync events are matched (prefix match on 'journal_event.')."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "journal_review.detect_matches",
        ],
    )
    def test_matches_journal_review_events(
        self, consumer: InboundEventConsumer, event_type: str
    ) -> None:
        """Verify journal_review events are matched (prefix match on 'journal_review.')."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            # Domain events — handled by other consumers
            "ContactCreated",
            "ContactUpdated",
            "ContactDeleted",
            "JournalCreated",
            "JournalUpdated",
            "JournalDeleted",
            "TagUpdated",
            "TagDeleted",
            "TagAssigned",
            "TagRemoved",
            "ContactSummaryRefreshRequested",
            # Unknown events
            "SomethingElse",
            "route.created",
        ],
    )
    def test_skips_non_matching_events(
        self, consumer: InboundEventConsumer, event_type: str
    ) -> None:
        """Verify domain events and unknowns are not matched by the inbound consumer."""
        assert consumer._matches_event_type(event_type) is False


class TestInboundEventConsumerHandleEvent:
    """Test the _handle_event implementation.

    Uses shared fixtures from conftest.py for mock_db_engine,
    mock_db_connection, and mock_stream_client.
    """

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        """Create a mock Dishka AsyncContainer."""
        container = MagicMock()

        class MockContext:
            async def __aenter__(self):
                return container

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass  # Mock implementation for context manager

        container.return_value = MockContext()
        container.get = AsyncMock()
        return container

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock Settings."""
        settings = MagicMock(spec=Settings)
        settings.gemini_api_key = "test-key"
        settings.gemini_model = "gemini-2.5-flash"
        return settings

    @pytest.fixture
    def consumer(
        self,
        mock_stream_client: MagicMock,
        mock_container: MagicMock,
        mock_settings: MagicMock,
    ) -> InboundEventConsumer:
        """Create an InboundEventConsumer with mocks."""
        return InboundEventConsumer(
            stream_client=mock_stream_client,
            container=mock_container,
            settings=mock_settings,
            stream_name="pms:domain-events",
        )

    @pytest.mark.asyncio
    async def test_contact_created_routes_to_outbox_event_processor(
        self,
        consumer: InboundEventConsumer,
        mock_db_engine: MagicMock,
    ) -> None:
        """Verify contact.created events route to OutboxEventProcessor.process_event."""
        event = _make_stream_event(
            event_type="contact.created",
            event_data={
                "integration_source": "google",
                "external_id": "people/c123",
                "contact_data": {"first_name": "Test"},
                "sync_timestamp": "2024-01-01T10:00:00Z",
            },
        )

        mock_processor = AsyncMock()
        mock_processor.process_event = AsyncMock(
            return_value={"status": "success", "contact_id": 123}
        )

        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.core.integrations.outbox_event_processor.OutboxEventProcessor",
                return_value=mock_processor,
            ),
        ):
            await consumer._handle_event(event)

        mock_processor.process_event.assert_called_once()
        # Verify the adapted OutboxEvent has the correct event_type
        call_args = mock_processor.process_event.call_args[0]
        assert call_args[0].event_type == "contact.created"
        assert call_args[0].event_id == "evt-test-123"

    @pytest.mark.asyncio
    async def test_contact_updated_routes_to_outbox_event_processor(
        self,
        consumer: InboundEventConsumer,
        mock_db_engine: MagicMock,
    ) -> None:
        """Verify contact.updated events route to OutboxEventProcessor.process_event."""
        event = _make_stream_event(
            event_type="contact.updated",
            event_data={
                "integration_source": "google",
                "external_id": "people/c456",
                "contact_data": {"first_name": "Updated"},
                "sync_timestamp": "2024-01-01T10:00:00Z",
            },
        )

        mock_processor = AsyncMock()
        mock_processor.process_event = AsyncMock(
            return_value={"status": "success", "contact_id": 456}
        )

        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.core.integrations.outbox_event_processor.OutboxEventProcessor",
                return_value=mock_processor,
            ),
        ):
            await consumer._handle_event(event)

        mock_processor.process_event.assert_called_once()
        call_args = mock_processor.process_event.call_args[0]
        assert call_args[0].event_type == "contact.updated"

    @pytest.mark.asyncio
    async def test_journal_event_created_routes_to_journal_outbox_event_processor(
        self,
        consumer: InboundEventConsumer,
        mock_db_engine: MagicMock,
    ) -> None:
        """Verify journal_event.created events route to JournalOutboxEventProcessor."""
        event = _make_stream_event(
            event_type="journal_event.created",
            event_data={
                "journal_id": 1,
                "user_id": "user123",
                "title": "Test Journal",
            },
        )

        mock_journal_processor = AsyncMock()
        mock_journal_processor.process_event = AsyncMock(
            return_value={"status": "success"}
        )

        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.core.integrations.journal_outbox_event_processor.JournalOutboxEventProcessor",
                return_value=mock_journal_processor,
            ),
            patch(
                "app.core.settings.adapters.sql.user_settings_repository.SqlUserSettingsRepository.get_default_timezone",
                new_callable=AsyncMock,
                return_value="UTC",
            ),
        ):
            await consumer._handle_event(event)

        mock_journal_processor.process_event.assert_called_once()
        call_args = mock_journal_processor.process_event.call_args[0]
        assert call_args[0].event_type == "journal_event.created"

    @pytest.mark.asyncio
    async def test_journal_review_detect_matches_routes_to_match_detection_processor(
        self,
        consumer: InboundEventConsumer,
        mock_db_engine: MagicMock,
    ) -> None:
        """Verify journal_review.detect_matches events route to MatchDetectionEventProcessor."""
        event = _make_stream_event(
            event_type="journal_review.detect_matches",
            event_data={
                "journal_id": 1,
                "user_id": "user123",
                "journal_title": "Test Journal",
                "event_date_range_start": "2024-01-01T10:00:00Z",
                "event_date_range_end": "2024-01-01T11:00:00Z",
            },
        )

        mock_match_processor = AsyncMock()
        mock_match_processor.process_event = AsyncMock(
            return_value={"status": "success"}
        )

        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.core.integrations.match_detection_event_processor.MatchDetectionEventProcessor",
                return_value=mock_match_processor,
            ),
            patch(
                "app.core.settings.adapters.sql.user_settings_repository.SqlUserSettingsRepository.get_default_timezone",
                new_callable=AsyncMock,
                return_value="UTC",
            ),
        ):
            await consumer._handle_event(event)

        mock_match_processor.process_event.assert_called_once()
        call_args = mock_match_processor.process_event.call_args[0]
        assert call_args[0].event_type == "journal_review.detect_matches"

    @pytest.mark.asyncio
    async def test_journal_review_skips_match_detection_when_no_gemini_key(
        self,
        consumer: InboundEventConsumer,
        mock_db_engine: MagicMock,
    ) -> None:
        """Verify journal_review events still process without Gemini key (no detector)."""
        # Override settings to have no Gemini key
        consumer._settings.gemini_api_key = ""

        event = _make_stream_event(
            event_type="journal_review.detect_matches",
            event_data={
                "journal_id": 1,
                "user_id": "user123",
                "journal_title": "Test Journal",
            },
        )

        mock_match_processor = AsyncMock()
        mock_match_processor.process_event = AsyncMock(
            return_value={"status": "success"}
        )

        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.core.integrations.match_detection_event_processor.MatchDetectionEventProcessor",
                return_value=mock_match_processor,
            ) as mock_cls,
        ):
            await consumer._handle_event(event)

        # MatchDetectionEventProcessor should be created with match_candidate_detector=None
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs.get("match_candidate_detector") is None

    @pytest.mark.asyncio
    async def test_handle_event_error_propagates(
        self,
        consumer: InboundEventConsumer,
        mock_db_engine: MagicMock,
    ) -> None:
        """Verify errors in processing propagate (event left pending for retry)."""
        event = _make_stream_event(
            event_type="contact.created",
            event_data={
                "integration_source": "google",
                "external_id": "people/c123",
                "contact_data": {"first_name": "Test"},
                "sync_timestamp": "2024-01-01T10:00:00Z",
            },
        )

        mock_processor = AsyncMock()
        mock_processor.process_event = AsyncMock(
            side_effect=Exception("Processing failed")
        )

        with (
            patch(
                "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.core.integrations.outbox_event_processor.OutboxEventProcessor",
                return_value=mock_processor,
            ),
            pytest.raises(Exception, match="Processing failed"),
        ):
            await consumer._handle_event(event)

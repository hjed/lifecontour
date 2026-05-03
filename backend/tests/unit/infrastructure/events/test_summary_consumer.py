"""
Unit tests for SummaryConsumer.

Tests event routing, filtering, and the _handle_event integration with
the summary generation pipeline for the summary-generator consumer group.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient, StreamEvent

from app.infrastructure.events.summary_consumer import SummaryConsumer


def _make_summary_event(contact_id: int = 42) -> StreamEvent:
    """Create a ContactSummaryRefreshRequested StreamEvent."""
    return StreamEvent(
        message_id="1234567890-0",
        event_id="evt-summary-123",
        event_type="ContactSummaryRefreshRequested",
        aggregate_id=contact_id,
        event_data={"contact_id": contact_id},
        occurred_at="2024-06-15T10:30:00+00:00",
    )


@pytest.fixture
def _mock_settings() -> MagicMock:
    """Create mock settings with Gemini config."""
    settings = MagicMock()
    settings.gemini_api_key = "test-key"
    settings.gemini_summary_model = "gemini-test"
    return settings


class TestSummaryConsumerEventMatching:
    """Test event type pattern matching for the summary consumer."""

    @pytest.fixture
    def consumer(self) -> SummaryConsumer:
        """Create a SummaryConsumer with a mock stream client."""
        mock_client = MagicMock(spec=StreamClient)
        return SummaryConsumer(
            stream_client=mock_client,
            stream_name="pms:domain-events",
            container=MagicMock(),
        )

    def test_matches_summary_refresh_event(self, consumer: SummaryConsumer) -> None:
        """Verify ContactSummaryRefreshRequested is matched."""
        assert consumer._matches_event_type("ContactSummaryRefreshRequested") is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "ContactCreated",
            "ContactUpdated",
            "ContactDeleted",
            "JournalCreated",
            "JournalUpdated",
            "JournalDeleted",
            "TagAssigned",
            "TagRemoved",
            "contact.created",
            "journal_event.created",
            "SomethingElse",
        ],
    )
    def test_skips_non_summary_events(
        self, consumer: SummaryConsumer, event_type: str
    ) -> None:
        """Verify non-summary events are not matched."""
        assert consumer._matches_event_type(event_type) is False


class TestSummaryConsumerHandleEvent:
    """Test the _handle_event implementation.

    Uses shared fixtures from conftest.py for mock_db_engine,
    mock_db_connection, mock_stream_client, and mock_search_indexer.
    """

    @pytest.fixture
    def consumer(self, mock_stream_client: MagicMock) -> SummaryConsumer:
        """Create a SummaryConsumer with mocks."""
        return SummaryConsumer(
            stream_client=mock_stream_client,
            stream_name="pms:domain-events",
            container=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_handle_event_generates_summary(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """Verify _handle_event constructs the generation pipeline and calls generate."""
        event = _make_summary_event(contact_id=42)

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value=MagicMock(status=MagicMock(value="generated"))
        )

        with (
            patch(
                "app.infrastructure.events.summary_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.get_settings",
                return_value=_mock_settings,
            ),
            patch(
                "app.core.contacts.services.summary_generation_service.SummaryGenerator",
                return_value=mock_generator,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.SearchIndexer",
                return_value=mock_search_indexer,
            ),
        ):
            await consumer._handle_event(event)

        mock_generator.generate.assert_called_once_with(contact_id=42)

    @pytest.mark.asyncio
    async def test_handle_event_updates_search_index_after_summary(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """Verify SearchIndexer.process_event is called after summary generation."""
        event = _make_summary_event(contact_id=42)

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(
            return_value=MagicMock(status=MagicMock(value="generated"))
        )

        with (
            patch(
                "app.infrastructure.events.summary_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.get_settings",
                return_value=_mock_settings,
            ),
            patch(
                "app.core.contacts.services.summary_generation_service.SummaryGenerator",
                return_value=mock_generator,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.SearchIndexer",
                return_value=mock_search_indexer,
            ),
        ):
            await consumer._handle_event(event)

        # Search indexer should be called to update the contact index
        mock_search_indexer.process_event.assert_called_once()
        call_args = mock_search_indexer.process_event.call_args[0]
        assert call_args[0].event_type == "ContactSummaryRefreshRequested"

    @pytest.mark.asyncio
    async def test_handle_event_skips_when_no_gemini_key(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
    ) -> None:
        """Verify graceful skip when Gemini API key is not configured."""
        event = _make_summary_event(contact_id=42)

        mock_settings = MagicMock()
        mock_settings.gemini_api_key = ""  # Not configured

        with (
            patch(
                "app.infrastructure.events.summary_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.SearchIndexer",
                return_value=mock_search_indexer,
            ),
        ):
            # Should not raise
            await consumer._handle_event(event)

        # Search indexer should still be called to update index (even without summary)
        mock_search_indexer.process_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_skips_invalid_contact_id(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """Verify graceful skip when contact_id is missing from event data."""
        event = StreamEvent(
            message_id="1234567890-0",
            event_id="evt-invalid-1",
            event_type="ContactSummaryRefreshRequested",
            aggregate_id=0,
            event_data={},  # Missing contact_id
            occurred_at="2024-06-15T10:30:00+00:00",
        )

        with (
            patch(
                "app.infrastructure.events.summary_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.get_settings",
                return_value=_mock_settings,
            ),
            patch(
                "app.infrastructure.events.summary_consumer.SearchIndexer",
                return_value=mock_search_indexer,
            ),
        ):
            # Should not raise
            await consumer._handle_event(event)

        # Search indexer should still be called to update index
        mock_search_indexer.process_event.assert_called_once()

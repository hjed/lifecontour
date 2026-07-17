"""
Unit tests for SummaryConsumer.

Tests event routing, filtering, and the _handle_event split between
buffered marking (ContactSummaryRefreshRequested) and generation
(ContactSummaryRefreshDue) for the summary-generator consumer group.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient, StreamEvent

from app.infrastructure.events.summary_consumer import SummaryConsumer


@asynccontextmanager
async def mock_container_context() -> AsyncGenerator[MagicMock]:
    yield MagicMock()


def make_mock_container() -> MagicMock:
    mock = MagicMock()
    mock.return_value = mock_container_context()
    return mock


def _make_requested_event(contact_id: int = 42) -> StreamEvent:
    """Create a ContactSummaryRefreshRequested StreamEvent (buffered intent)."""
    return StreamEvent(
        message_id="1234567890-0",
        event_id="evt-summary-123",
        event_type="ContactSummaryRefreshRequested",
        aggregate_id=contact_id,
        event_data={"contact_id": contact_id},
        occurred_at="2024-06-15T10:30:00+00:00",
    )


def _make_due_event(contact_id: int = 42) -> StreamEvent:
    """Create a ContactSummaryRefreshDue StreamEvent (generate-now command)."""
    return StreamEvent(
        message_id="1234567890-1",
        event_id="evt-summary-due-123",
        event_type="ContactSummaryRefreshDue",
        aggregate_id=contact_id,
        event_data={"contact_id": contact_id},
        occurred_at="2024-06-15T10:35:00+00:00",
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
            container=make_mock_container(),
        )

    def test_matches_summary_refresh_requested(self, consumer: SummaryConsumer) -> None:
        """Verify ContactSummaryRefreshRequested is matched."""
        assert consumer._matches_event_type("ContactSummaryRefreshRequested") is True

    def test_matches_summary_refresh_due(self, consumer: SummaryConsumer) -> None:
        """Verify ContactSummaryRefreshDue is matched."""
        assert consumer._matches_event_type("ContactSummaryRefreshDue") is True

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


class TestSummaryConsumerHandleRequestedEvent:
    """ContactSummaryRefreshRequested must mark the debounce buffer only."""

    @pytest.fixture
    def consumer(self, mock_stream_client: MagicMock) -> SummaryConsumer:
        """Create a SummaryConsumer with mocks."""
        return SummaryConsumer(
            stream_client=mock_stream_client,
            stream_name="pms:domain-events",
            container=make_mock_container(),
        )

    @pytest.mark.asyncio
    async def test_requested_event_marks_refresh(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
    ) -> None:
        """A Requested event records the debounce marker for the contact."""
        event = _make_requested_event(contact_id=42)

        with (
            patch(
                "app.infrastructure.events.summary_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.core.contacts.adapters.sql.contact_summary_repository"
                ".SqlContactSummaryRepository.mark_refresh_requested",
                new_callable=AsyncMock,
            ) as mock_mark,
        ):
            await consumer._handle_event(event)

        mock_mark.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_requested_event_does_not_generate_or_index(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """A Requested event must not call Gemini or the search indexer."""
        event = _make_requested_event(contact_id=42)

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock()

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
            patch(
                "app.core.contacts.adapters.sql.contact_summary_repository"
                ".SqlContactSummaryRepository.mark_refresh_requested",
                new_callable=AsyncMock,
            ),
        ):
            await consumer._handle_event(event)

        mock_generator.generate.assert_not_called()
        mock_search_indexer.process_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_requested_event_with_invalid_contact_id_is_skipped(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
    ) -> None:
        """A Requested event without a valid contact_id is dropped gracefully."""
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
                "app.core.contacts.adapters.sql.contact_summary_repository"
                ".SqlContactSummaryRepository.mark_refresh_requested",
                new_callable=AsyncMock,
            ) as mock_mark,
        ):
            # Should not raise
            await consumer._handle_event(event)

        mock_mark.assert_not_awaited()


class TestSummaryConsumerHandleDueEvent:
    """ContactSummaryRefreshDue drives the actual generation pipeline.

    Uses shared fixtures from conftest.py for mock_db_engine,
    mock_db_connection, mock_stream_client, and mock_search_indexer.
    """

    @pytest.fixture
    def consumer(self, mock_stream_client: MagicMock) -> SummaryConsumer:
        """Create a SummaryConsumer with mocks."""
        return SummaryConsumer(
            stream_client=mock_stream_client,
            stream_name="pms:domain-events",
            container=make_mock_container(),
        )

    @pytest.mark.asyncio
    async def test_due_event_generates_summary(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """Verify _handle_event constructs the generation pipeline and calls generate."""
        event = _make_due_event(contact_id=42)

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
                "app.core.settings.adapters.sql.user_settings_repository.SqlUserSettingsRepository.get_default_timezone",
                new_callable=AsyncMock,
                return_value="UTC",
            ),
            patch(
                "app.infrastructure.events.summary_consumer.SearchIndexer",
                return_value=mock_search_indexer,
            ),
        ):
            await consumer._handle_event(event)

        mock_generator.generate.assert_called_once_with(contact_id=42)

    @pytest.mark.asyncio
    async def test_due_event_updates_search_index_after_summary(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """Verify SearchIndexer.process_event is called after summary generation."""
        event = _make_due_event(contact_id=42)

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
                "app.core.settings.adapters.sql.user_settings_repository.SqlUserSettingsRepository.get_default_timezone",
                new_callable=AsyncMock,
                return_value="UTC",
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
        assert call_args[0].event_type == "ContactSummaryRefreshDue"

    @pytest.mark.asyncio
    async def test_due_event_skips_when_no_gemini_key(
        self,
        consumer: SummaryConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
    ) -> None:
        """Verify graceful skip when Gemini API key is not configured."""
        event = _make_due_event(contact_id=42)

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
    async def test_due_event_skips_invalid_contact_id(
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
            event_type="ContactSummaryRefreshDue",
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

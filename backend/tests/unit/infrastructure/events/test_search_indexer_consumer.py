"""
Unit tests for SearchIndexerConsumer.

Tests event routing, filtering, and the _handle_event integration with
SearchIndexer for the search-indexer consumer group.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient, StreamEvent

from app.infrastructure.events.search_indexer_consumer import SearchIndexerConsumer


class TestSearchIndexerConsumerEventMatching:
    """Test event type pattern matching for the search indexer consumer."""

    @pytest.fixture
    def consumer(self) -> SearchIndexerConsumer:
        """Create a SearchIndexerConsumer with a mock stream client."""
        mock_client = MagicMock(spec=StreamClient)
        return SearchIndexerConsumer(
            stream_client=mock_client,
            stream_name="pms:domain-events",
        )

    @pytest.mark.parametrize(
        "event_type",
        [
            "ContactCreated",
            "ContactUpdated",
            "ContactDeleted",
            "ContactSummaryRefreshRequested",
        ],
    )
    def test_matches_contact_events(
        self, consumer: SearchIndexerConsumer, event_type: str
    ) -> None:
        """Verify contact events are matched for search indexing."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "ContactRelationshipCreated",
            "ContactRelationshipUpdated",
            "ContactRelationshipDeleted",
        ],
    )
    def test_matches_contact_relationship_events(
        self, consumer: SearchIndexerConsumer, event_type: str
    ) -> None:
        """Verify contact relationship events are matched."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "TagAssigned",
            "TagRemoved",
        ],
    )
    def test_matches_contact_tag_events(
        self, consumer: SearchIndexerConsumer, event_type: str
    ) -> None:
        """Verify contact-tag assignment/removal events are matched."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "ImportantDateAdded",
            "ImportantDateDeleted",
        ],
    )
    def test_matches_contact_important_date_events(
        self, consumer: SearchIndexerConsumer, event_type: str
    ) -> None:
        """Verify contact-scoped important date events are matched."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "JournalCreated",
            "JournalUpdated",
            "JournalDeleted",
        ],
    )
    def test_matches_journal_events(
        self, consumer: SearchIndexerConsumer, event_type: str
    ) -> None:
        """Verify journal events are matched for search indexing."""
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            # Integration sync events — processed by inbound consumer (Phase 3)
            "contact.created",
            "contact.updated",
            "contact.deleted",
            "journal_event.created",
            "journal_event.updated",
            "journal_review.detect_matches",
            # ARQ broadcast events — processed by outbound consumer (Phase 3)
            "TagUpdated",
            "TagDeleted",
            # Unknown events
            "SomethingElse",
            "route.created",
        ],
    )
    def test_skips_non_matching_events(
        self, consumer: SearchIndexerConsumer, event_type: str
    ) -> None:
        """Verify non-search events are not matched (acked and skipped by base class)."""
        assert consumer._matches_event_type(event_type) is False


def _make_stream_event(
    event_type: str = "ContactCreated",
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


class TestSearchIndexerConsumerHandleEvent:
    """Test the _handle_event implementation.

    Uses shared fixtures from conftest.py for mock_db_engine,
    mock_db_connection, and mock_search_indexer.
    """

    @pytest.fixture
    def consumer(self, mock_stream_client: MagicMock) -> SearchIndexerConsumer:
        """Create a SearchIndexerConsumer with mocks."""
        return SearchIndexerConsumer(
            stream_client=mock_stream_client,
            stream_name="pms:domain-events",
        )

    @pytest.mark.asyncio
    async def test_handle_event_calls_search_indexer(
        self,
        consumer: SearchIndexerConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
    ) -> None:
        """Verify _handle_event creates a SearchIndexer and calls process_event."""
        event = _make_stream_event()

        with (
            patch(
                "app.infrastructure.events.search_indexer_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.infrastructure.events.search_indexer_consumer.SearchIndexer",
                return_value=mock_search_indexer,
            ),
        ):
            await consumer._handle_event(event)

        mock_search_indexer.process_event.assert_called_once()
        # Verify the adapted OutboxEvent has the correct event_type
        call_args = mock_search_indexer.process_event.call_args[0]
        assert call_args[0].event_type == "ContactCreated"
        assert call_args[0].event_id == "evt-test-123"

    @pytest.mark.asyncio
    async def test_handle_event_invalidates_daily_summary_for_journal_events(
        self,
        consumer: SearchIndexerConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
    ) -> None:
        """Verify daily summary invalidation runs for journal events."""
        event = _make_stream_event(
            event_type="JournalUpdated",
            event_data={"journal_id": 99},
            aggregate_id=99,
        )

        with (
            patch(
                "app.infrastructure.events.search_indexer_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.infrastructure.events.search_indexer_consumer.SearchIndexer",
                return_value=mock_search_indexer,
            ),
            patch.object(
                consumer,
                "_invalidate_daily_summary",
                new_callable=AsyncMock,
            ) as mock_invalidate,
        ):
            await consumer._handle_event(event)

        mock_search_indexer.process_event.assert_called_once()
        mock_invalidate.assert_called_once()
        # Verify the outbox event passed to invalidation has the right type
        invalidate_args = mock_invalidate.call_args[0]
        assert invalidate_args[0].event_type == "JournalUpdated"

    @pytest.mark.asyncio
    async def test_handle_event_does_not_invalidate_for_non_journal_events(
        self,
        consumer: SearchIndexerConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
    ) -> None:
        """Verify daily summary invalidation does NOT run for contact events."""
        event = _make_stream_event(
            event_type="ContactCreated",
            event_data={"contact_id": 42},
        )

        with (
            patch(
                "app.infrastructure.events.search_indexer_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.infrastructure.events.search_indexer_consumer.SearchIndexer",
                return_value=mock_search_indexer,
            ),
            patch.object(
                consumer,
                "_invalidate_daily_summary",
                new_callable=AsyncMock,
            ) as mock_invalidate,
        ):
            await consumer._handle_event(event)

        mock_search_indexer.process_event.assert_called_once()
        mock_invalidate.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event_type",
        ["JournalCreated", "JournalUpdated", "JournalDeleted"],
    )
    async def test_invalidation_triggered_for_all_journal_crud_events(
        self,
        consumer: SearchIndexerConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
        event_type: str,
    ) -> None:
        """Verify all three journal CRUD event types trigger invalidation."""
        event = _make_stream_event(
            event_type=event_type,
            event_data={"journal_id": 1},
            aggregate_id=1,
        )

        with (
            patch(
                "app.infrastructure.events.search_indexer_consumer.get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch(
                "app.infrastructure.events.search_indexer_consumer.SearchIndexer",
                return_value=mock_search_indexer,
            ),
            patch.object(
                consumer,
                "_invalidate_daily_summary",
                new_callable=AsyncMock,
            ) as mock_invalidate,
        ):
            await consumer._handle_event(event)

        mock_invalidate.assert_called_once()

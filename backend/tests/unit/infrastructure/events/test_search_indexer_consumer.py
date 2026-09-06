"""
Unit tests for SearchIndexerConsumer.

Tests event routing, filtering, and the _handle_event integration with
SearchIndexer for the search-indexer consumer group.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient, StreamEvent

from app.infrastructure.events.search_indexer_consumer import SearchIndexerConsumer
from tests.task_event_inventory import task_event_types


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
            "JournalTagAssigned",
            "JournalTagRemoved",
            "JournalTagDeleted",
            "JournalTagMerged",
        ],
    )
    def test_matches_journal_tag_events(
        self, consumer: SearchIndexerConsumer, event_type: str
    ) -> None:
        """Verify journal tag events are matched.

        The journal document carries ``tag_ids``, so a tag change makes it stale
        until the journal is re-indexed. Without this subscription the events are
        published and projected into history but never reach the indexer.
        """
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            # Journal documents index tag ids and never tag names, so a rename
            # leaves every document unchanged and must not be subscribed.
            "JournalTagRenamed",
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


class TestTasksAreNeverIndexed:
    """The specification's *"tasks are not indexed"*, pinned rather than assumed.

    From the home-dashboard specification, §*Tasks and search*: there is no tasks
    index, a global search never returns a task, and the indexer *ignores* task
    events rather than failing on them. It follows from the no-accumulating-
    backlog principle — a searchable task corpus is a backlog by another name.

    True by construction today, and true twice over: nothing subscribes the
    patterns and ``SearchIndexer.process_event`` has no branch for them either.
    That is exactly why it needs a test — the *history* projection subscribes
    every one of these types, so the next person widening a pattern list has
    nothing to stop them widening this one.
    """

    @pytest.fixture
    def consumer(self) -> SearchIndexerConsumer:
        return SearchIndexerConsumer(
            stream_client=MagicMock(spec=StreamClient),
            stream_name="pms:domain-events",
        )

    @pytest.mark.parametrize("event_type", sorted(task_event_types()))
    def test_no_task_event_is_matched_for_indexing(
        self, consumer: SearchIndexerConsumer, event_type: str
    ) -> None:
        """An unmatched event is acknowledged and skipped by the base class, so it
        neither indexes anything nor sits pending until it dead-letters.

        Parametrised over the event classes in the tasks module rather than a
        list written here, so a type added later is covered the day it lands.
        """
        assert consumer._matches_event_type(event_type) is False

    def test_the_inventory_is_not_empty(self) -> None:
        """A guard on the parametrisation above, not on the consumer.

        An inventory that silently returned nothing would turn every case in this
        class into zero cases and the file would still pass.
        """
        assert len(task_event_types()) >= 6


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
    @pytest.mark.parametrize(
        "event_type", ["JournalCreated", "JournalUpdated", "JournalDeleted"]
    )
    async def test_a_journal_event_is_indexed_and_nothing_else(
        self,
        consumer: SearchIndexerConsumer,
        mock_db_engine: MagicMock,
        mock_search_indexer: MagicMock,
        event_type: str,
    ) -> None:
        """Daily summary invalidation is gone from here — ITER18-005 Phase 7.

        It ran in this handler until then, having landed in it by history rather
        than by design, and four tests here asserted it did. They are this one
        now: the consumer indexes and returns, and summary freshness belongs to
        ``SummaryInvalidationConsumer``.

        The move was forced rather than chosen. This consumer's contract is that
        **task events are permanently ignored** (see ``TestTasksAreNeverIndexed``
        below), and Phase 7's whole subject is that a task change makes a summary
        stale — so the two could not live together whatever the tidiness
        argument said.

        Asserted as an **absence on the object**, not as a call that did not
        happen: a patched-out method that no longer exists would let this pass
        while the invalidation quietly ran somewhere else in the handler.
        """
        event = _make_stream_event(
            event_type=event_type, event_data={"journal_id": 99}, aggregate_id=99
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
        ):
            await consumer._handle_event(event)

        mock_search_indexer.process_event.assert_called_once()
        assert not hasattr(consumer, "_invalidate_daily_summary")

    def test_the_module_no_longer_names_an_invalidation_event_set(self) -> None:
        """``_JOURNAL_INVALIDATION_EVENTS`` moved out with the behaviour.

        Iteration 17 recorded a decision against this constant — *"the summary
        assembler references no tags, so tag events stay out of it"* — and that
        reasoning now lives beside the consumer that owns the set. Two sets, one
        of them stale, is how a subscription silently stops matching what it
        describes.
        """
        from app.infrastructure.events import search_indexer_consumer

        assert not hasattr(search_indexer_consumer, "_JOURNAL_INVALIDATION_EVENTS")

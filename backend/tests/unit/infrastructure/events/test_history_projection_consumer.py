"""Unit tests for HistoryProjectionConsumer configuration.

Verifies the consumer subscribes to exactly the journal/route/gear event types
and runs in the dedicated ``history-projection`` consumer group, mirroring the
SearchIndexerConsumer setup.
"""

from unittest.mock import MagicMock

from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)

_EXPECTED_EVENT_TYPES = {
    "JournalCreated",
    "JournalUpdated",
    "JournalDeleted",
    "JournalTypeAdded",
    "JournalTypeRemoved",
    "RouteCreated",
    "RouteUpdated",
    "RouteDeleted",
    "GearItemUpdated",
}


def _consumer() -> HistoryProjectionConsumer:
    return HistoryProjectionConsumer(
        stream_client=MagicMock(),
        stream_name="pms:test-events",
        consumer_name="history-projection-test",
    )


def test_consumer_uses_history_projection_group() -> None:
    consumer = _consumer()
    assert consumer._group_name == "history-projection"


def test_consumer_subscribes_to_journal_event_types() -> None:
    consumer = _consumer()
    assert set(consumer._event_type_patterns) == _EXPECTED_EVENT_TYPES

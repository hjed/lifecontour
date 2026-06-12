"""Unit tests for HistoryProjectionConsumer configuration.

Verifies the consumer subscribes to exactly the journal/route/gear event types
and runs in the dedicated ``history-projection`` consumer group, mirroring the
SearchIndexerConsumer setup.
"""

from unittest.mock import MagicMock

from app.infrastructure.events.history_projection_consumer import (
    _CONTACT_HISTORY_EVENT_TYPES,
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

# Contact event types the projection knows how to map, but which must NOT be in
# the live subscription this phase (ITER12-003 Phase 1 keeps contact projection
# inert so the dual-write stays the sole writer until Phase 2).
_CONTACT_EVENT_TYPES = {
    "ContactCreated",
    "ContactUpdated",
    "ContactDeleted",
    "ContactMethodAdded",
    "ContactMethodDeleted",
    "ContactAddressAdded",
    "ContactAddressDeleted",
    "ContactNoteAdded",
    "ImportantDateAdded",
    "ImportantDateDeleted",
    "TagAssigned",
    "TagRemoved",
    "ContactRelationshipCreated",
    "ContactRelationshipUpdated",
    "ContactRelationshipDeleted",
    "ContactSummaryUpdated",
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


def test_contact_projection_is_inert_in_live_subscription() -> None:
    """Phase 1 invariant: no contact event type is on the live subscription, so the
    consumer never double-writes contact history while the dual-write still runs."""
    consumer = _consumer()
    assert _CONTACT_EVENT_TYPES.isdisjoint(set(consumer._event_type_patterns))


def test_contact_history_event_types_constant_ready_for_phase_2() -> None:
    """The contact event-type list exists (for Phase 2 to switch on) and matches
    the full set of contact events the projection handles."""
    assert set(_CONTACT_HISTORY_EVENT_TYPES) == _CONTACT_EVENT_TYPES

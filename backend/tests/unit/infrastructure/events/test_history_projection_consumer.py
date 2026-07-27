"""Unit tests for HistoryProjectionConsumer configuration.

Verifies the consumer subscribes to the journal/route/gear AND contact event
types and runs in the dedicated ``history-projection`` consumer group, mirroring
the SearchIndexerConsumer setup.

ITER12-003 Phase 2 switched contacts onto the projection: the contact event types
are now part of the live subscription (the synchronous dual-write was removed).
"""

from unittest.mock import MagicMock

from app.core.history.services.history_service import _HANDLERS
from app.infrastructure.events.history_projection_consumer import (
    _CONTACT_HISTORY_EVENT_TYPES,
    _JOURNAL_HISTORY_EVENT_TYPES,
    HistoryProjectionConsumer,
)

_JOURNAL_EVENT_TYPES = {
    "JournalCreated",
    "JournalUpdated",
    "JournalDeleted",
    "JournalTypeAdded",
    "JournalTypeRemoved",
    # Journal tag assignment/removal.
    "JournalTagAssigned",
    "JournalTagRemoved",
    # Journal tag rename, fanned out to every journal carrying the tag.
    "JournalTagRenamed",
    "RouteCreated",
    "RouteUpdated",
    "RouteDeleted",
    "GearItemUpdated",
}

# Contact event types the projection maps — now part of the live subscription.
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


def test_consumer_subscribes_to_journal_and_contact_event_types() -> None:
    consumer = _consumer()
    assert set(consumer._event_type_patterns) == (
        _JOURNAL_EVENT_TYPES | _CONTACT_EVENT_TYPES
    )


def test_contact_projection_is_live() -> None:
    """ITER12-003 Phase 2: every contact event type is now on the live
    subscription, so the projection is the sole writer of contact history."""
    consumer = _consumer()
    assert _CONTACT_EVENT_TYPES.issubset(set(consumer._event_type_patterns))


def test_subscription_has_no_duplicate_event_types() -> None:
    """Journal and contact event-type lists are disjoint, so the merged live
    subscription contains each type exactly once."""
    consumer = _consumer()
    patterns = list(consumer._event_type_patterns)
    assert len(patterns) == len(set(patterns))


def test_event_type_constants_match_handled_sets() -> None:
    """The module constants match the full sets the projection handles."""
    assert set(_JOURNAL_HISTORY_EVENT_TYPES) == _JOURNAL_EVENT_TYPES
    assert set(_CONTACT_HISTORY_EVENT_TYPES) == _CONTACT_EVENT_TYPES


def test_every_subscribed_event_type_has_a_projection_handler() -> None:
    """A subscribed type with no handler would be consumed and silently dropped.

    ``project_event`` returns an empty row list for an unknown event type, so the
    consumer would acknowledge the event and write no history — a missing entry
    with nothing in the logs. Pinning the two sides together turns that into a
    test failure at the moment a new event type is added.
    """
    subscribed = set(_JOURNAL_HISTORY_EVENT_TYPES) | set(_CONTACT_HISTORY_EVENT_TYPES)

    assert subscribed <= set(_HANDLERS)

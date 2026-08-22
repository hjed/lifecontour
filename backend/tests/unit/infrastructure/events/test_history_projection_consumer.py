"""Unit tests for HistoryProjectionConsumer configuration.

Verifies the consumer subscribes to the journal/route/gear, contact AND task
event types and runs in the dedicated ``history-projection`` consumer group,
mirroring the SearchIndexerConsumer setup.

ITER12-003 Phase 2 switched contacts onto the projection: the contact event types
are now part of the live subscription (the synchronous dual-write was removed).
Every type the tasks domain publishes is projected.
"""

from unittest.mock import MagicMock

from app.core.history.services.history_service import _HANDLERS
from app.infrastructure.events.history_projection_consumer import (
    _CONTACT_HISTORY_EVENT_TYPES,
    _JOURNAL_HISTORY_EVENT_TYPES,
    _TASK_HISTORY_EVENT_TYPES,
    HistoryProjectionConsumer,
)
from tests.task_event_inventory import task_event_types

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
    # Journal tag delete, likewise fanned out to every journal that carried it.
    "JournalTagDeleted",
    # Journal tag merge, fanned out to every journal carrying the source.
    "JournalTagMerged",
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

# Task event types the projection maps: the lifecycle set plus the anchor move
# and the intermediate-journal pair. Every type the tasks domain publishes is
# projected, which ``test_every_task_event_type_is_subscribed`` asserts against
# the events module rather than against this list — a list is a thing somebody
# has to remember to extend.
_TASK_EVENT_TYPES = {
    "TaskCreated",
    "TaskUpdated",
    "TaskDueJournalRetargeted",
    "TaskJournalLinked",
    "TaskJournalUnlinked",
    "TaskDeleted",
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


def test_consumer_subscribes_to_journal_contact_and_task_event_types() -> None:
    consumer = _consumer()
    assert set(consumer._event_type_patterns) == (
        _JOURNAL_EVENT_TYPES | _CONTACT_EVENT_TYPES | _TASK_EVENT_TYPES
    )


def test_task_lifecycle_events_are_projected() -> None:
    """ITER18-003 Phase 6: task writes reach the user's history."""
    consumer = _consumer()
    assert _TASK_EVENT_TYPES.issubset(set(consumer._event_type_patterns))


def test_every_task_event_type_is_subscribed() -> None:
    """Nothing the tasks domain publishes goes unread.

    The subscription and the projection's handler table move together, and this is
    the half that fails when a *new* event type arrives, because it reads the
    event classes out of the module rather than the list above.
    """
    consumer = _consumer()

    assert task_event_types() <= set(consumer._event_type_patterns)


def test_contact_projection_is_live() -> None:
    """ITER12-003 Phase 2: every contact event type is now on the live
    subscription, so the projection is the sole writer of contact history."""
    consumer = _consumer()
    assert _CONTACT_EVENT_TYPES.issubset(set(consumer._event_type_patterns))


def test_subscription_has_no_duplicate_event_types() -> None:
    """Journal, contact and task event-type lists are disjoint, so the merged
    live subscription contains each type exactly once."""
    consumer = _consumer()
    patterns = list(consumer._event_type_patterns)
    assert len(patterns) == len(set(patterns))


def test_event_type_constants_match_handled_sets() -> None:
    """The module constants match the full sets the projection handles."""
    assert set(_JOURNAL_HISTORY_EVENT_TYPES) == _JOURNAL_EVENT_TYPES
    assert set(_CONTACT_HISTORY_EVENT_TYPES) == _CONTACT_EVENT_TYPES
    assert set(_TASK_HISTORY_EVENT_TYPES) == _TASK_EVENT_TYPES


def test_every_subscribed_event_type_has_a_projection_handler() -> None:
    """A subscribed type with no handler would be consumed and silently dropped.

    ``project_event`` returns an empty row list for an unknown event type, so the
    consumer would acknowledge the event and write no history — a missing entry
    with nothing in the logs. Pinning the two sides together turns that into a
    test failure at the moment a new event type is added.
    """
    subscribed = (
        set(_JOURNAL_HISTORY_EVENT_TYPES)
        | set(_CONTACT_HISTORY_EVENT_TYPES)
        | set(_TASK_HISTORY_EVENT_TYPES)
    )

    assert subscribed <= set(_HANDLERS)


def test_no_task_handler_exists_without_a_subscription() -> None:
    """The reverse direction: history written and never read.

    A handler added without the matching subscription projects nothing, because
    the consumer never sees the event — the failure is silent in the other
    direction, and only checking both ways catches it: this half catches a
    handler somebody adds for a type the consumer was never told about.
    """
    consumer = _consumer()
    task_handlers = {key for key in _HANDLERS if key.startswith("Task")}

    assert task_handlers <= set(consumer._event_type_patterns)

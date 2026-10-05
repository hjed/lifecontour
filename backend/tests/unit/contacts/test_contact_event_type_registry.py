"""Guard tests for the shared contact event-type registry.

LOCAL-177: outbound Google contact sync silently dropped ten contact events
(``TagAssigned``, ``ContactMethodAdded``, ``ImportantDate*`` and friends) because
the Google worker's route table listed four event types by hand and nothing tied
that list to the events the contacts domain actually publishes. A new event type
was therefore invisible to outbound sync until someone noticed the data was not
reaching Google.

These tests close that loop: every ``event_type`` literal declared in
``app.core.contacts.models.events`` must be classified in the shared registry as
either pushed to integrations or explicitly excluded with a reason. Adding a new
contact event fails these tests until it is classified.

``event_type`` is passed as a literal to ``super().__init__`` rather than being a
class attribute, so the declared set is read from the source with ``ast`` instead
of by instantiating every event (whose constructors all differ).
"""

import ast
from pathlib import Path

import pytest
from core_shared.models.contacts.event_types import (
    CONTACT_EVENTS_NOT_PUSHED,
    CONTACT_PUSH_EVENT_TYPES,
    CONTACT_PUSH_EVENTS_WITHOUT_CONTACT_ID,
)

import app.core.contacts.models.events as contact_events_module

_EVENTS_SOURCE = Path(contact_events_module.__file__)


def _event_data_keys(class_node: ast.ClassDef) -> set[str]:
    """Return the literal string keys of the class's ``event_data`` dict."""
    keys: set[str] = set()
    for node in ast.walk(class_node):
        if not isinstance(node, ast.keyword) or node.arg != "event_data":
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


def _declared_event_types() -> dict[str, set[str]]:
    """Map each declared ``event_type`` literal to its ``event_data`` keys.

    Walks every class in the contacts events module and picks out the
    ``event_type="..."`` keyword passed to ``super().__init__``.
    """
    tree = ast.parse(_EVENTS_SOURCE.read_text(encoding="utf-8"))
    declared: dict[str, set[str]] = {}

    for class_node in ast.walk(tree):
        if not isinstance(class_node, ast.ClassDef):
            continue
        for node in ast.walk(class_node):
            if not isinstance(node, ast.keyword) or node.arg != "event_type":
                continue
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                declared[node.value.value] = _event_data_keys(class_node)

    return declared


@pytest.fixture(scope="module")
def declared_event_types() -> dict[str, set[str]]:
    """The ``event_type`` literals declared by the contacts domain."""
    return _declared_event_types()


class TestRegistryCoversEveryContactEvent:
    """Every declared contact event is classified exactly once."""

    def test_source_parsing_finds_the_known_events(
        self, declared_event_types: dict[str, set[str]]
    ) -> None:
        """The AST walk actually finds events (guards a silently empty parse)."""
        assert "ContactCreated" in declared_event_types
        assert "TagAssigned" in declared_event_types
        assert len(declared_event_types) > 10

    def test_every_declared_event_is_classified(
        self, declared_event_types: dict[str, set[str]]
    ) -> None:
        """A new contact event must be added to one of the registry tuples."""
        excluded = {event_type for event_type, _reason in CONTACT_EVENTS_NOT_PUSHED}
        classified = set(CONTACT_PUSH_EVENT_TYPES) | excluded

        unclassified = set(declared_event_types) - classified
        assert not unclassified, (
            "Contact events are not classified in "
            "core_shared.models.contacts.event_types: "
            f"{sorted(unclassified)}. Add each to CONTACT_PUSH_EVENT_TYPES so "
            "integration workers push it, or to CONTACT_EVENTS_NOT_PUSHED with a "
            "reason."
        )

    def test_registry_declares_no_unknown_events(
        self, declared_event_types: dict[str, set[str]]
    ) -> None:
        """The registry must not name events the domain no longer publishes."""
        excluded = {event_type for event_type, _reason in CONTACT_EVENTS_NOT_PUSHED}
        stale = (set(CONTACT_PUSH_EVENT_TYPES) | excluded) - set(declared_event_types)
        assert not stale, f"Registry names events that no longer exist: {sorted(stale)}"

    def test_pushed_and_excluded_sets_are_disjoint(self) -> None:
        """An event is either pushed or excluded, never both."""
        excluded = {event_type for event_type, _reason in CONTACT_EVENTS_NOT_PUSHED}
        assert not set(CONTACT_PUSH_EVENT_TYPES) & excluded

    def test_every_exclusion_carries_a_reason(self) -> None:
        """Exclusions document why, so the next reader need not guess."""
        for event_type, reason in CONTACT_EVENTS_NOT_PUSHED:
            assert reason.strip(), f"{event_type} is excluded without a reason"


class TestPushedEventsCarryTheHandlerPrecondition:
    """A pushed event must let the worker find the contact to push."""

    def test_pushed_events_carry_contact_id(
        self, declared_event_types: dict[str, set[str]]
    ) -> None:
        """``process_contact_event`` reads ``event_data["contact_id"]``.

        Without it the handler bails out with "Missing contact_id" and the change
        never reaches Google, which is the failure this ticket fixed.
        """
        for event_type in CONTACT_PUSH_EVENT_TYPES:
            if event_type in CONTACT_PUSH_EVENTS_WITHOUT_CONTACT_ID:
                continue
            assert "contact_id" in declared_event_types[event_type], (
                f"{event_type} is pushed to integrations but carries no "
                "'contact_id' in event_data"
            )

    def test_pushed_events_carry_the_owner(
        self, declared_event_types: dict[str, set[str]]
    ) -> None:
        """Workers push a contact change only to its owner's accounts.

        An event that names no owner is skipped, never fanned out to every
        connected account, so a pushed event without ``user_id`` would silently
        stop syncing. No exemptions: ``ContactMerged`` names the survivor's owner.
        """
        ownerless = [
            event_type
            for event_type in CONTACT_PUSH_EVENT_TYPES
            if "user_id" not in declared_event_types[event_type]
        ]
        assert not ownerless, (
            f"Pushed contact events carry no 'user_id' in event_data: {ownerless}"
        )

    def test_contact_id_exemptions_are_pushed_events(self) -> None:
        """The exemption list only covers events that are actually pushed."""
        assert set(CONTACT_PUSH_EVENTS_WITHOUT_CONTACT_ID) <= set(
            CONTACT_PUSH_EVENT_TYPES
        )

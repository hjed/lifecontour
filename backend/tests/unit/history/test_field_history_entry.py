"""Unit tests for the shared FieldHistoryEntry model and its compatibility alias."""

from core_shared.models.history import Provenance

from app.core.contacts.models.repositories import ContactFieldHistoryEntry
from app.core.history.models import FieldHistoryEntry


def test_contact_alias_is_shared_field_history_entry() -> None:
    """ContactFieldHistoryEntry must alias the shared FieldHistoryEntry for compatibility."""
    assert ContactFieldHistoryEntry is FieldHistoryEntry


def test_construction_defaults() -> None:
    """A minimally-constructed entry defaults source to SYSTEM and event_id to None."""
    entry = FieldHistoryEntry(
        entity_type="contact",
        entity_id=1,
        field_name="first_name",
    )

    assert entry.entity_type == "contact"
    assert entry.entity_id == 1
    assert entry.field_name == "first_name"
    assert entry.old_value is None
    assert entry.new_value is None
    assert entry.changed_by is None
    assert entry.source == Provenance.SYSTEM
    assert entry.event_id is None
    assert entry.id is None
    assert entry.created_at is None


def test_construction_with_event_id_and_provenance() -> None:
    """An entry can carry an event_id and explicit provenance (projection use-case)."""
    entry = FieldHistoryEntry(
        entity_type="journal",
        entity_id=42,
        field_name="title",
        old_value="Old",
        new_value="New",
        changed_by="ui",
        source=Provenance.UI,
        event_id="evt-123",
    )

    assert entry.event_id == "evt-123"
    assert entry.source == Provenance.UI
    assert entry.old_value == "Old"
    assert entry.new_value == "New"
    assert entry.changed_by == "ui"

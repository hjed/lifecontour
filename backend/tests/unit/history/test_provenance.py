"""Unit tests for the shared Provenance enum and its compatibility re-export."""

from core_shared.models.contacts.value_objects import Provenance as ContactProvenance
from core_shared.models.history import Provenance


def test_provenance_reexport_is_the_same_enum() -> None:
    """The contacts value-objects path must re-export the shared Provenance enum."""
    assert ContactProvenance is Provenance


def test_provenance_keeps_existing_values() -> None:
    """Existing provenance sources must be preserved (no behaviour change)."""
    assert Provenance.UI.value == "ui"
    assert Provenance.MCP.value == "mcp"
    assert Provenance.GOOGLE_CONTACTS.value == "google_contacts"
    assert Provenance.STRAVA.value == "strava"
    assert Provenance.SUMMARY_REGENERATION.value == "summary_regeneration"
    assert Provenance.SYSTEM.value == "system"
    assert Provenance.IMMICH.value == "immich"


def test_provenance_adds_google_calendar_source() -> None:
    """A journal-relevant Google Calendar source is added for iteration 12."""
    assert Provenance.GOOGLE_CALENDAR.value == "google_calendar"

"""Unit tests for contacts domain events.

ITER12-003 Phase 1 enriches every contact event with ``source`` (Provenance) and
``changed_by`` in ``event_data`` so the history projection consumer can record
provenance. Sub-entity field edits stay on ``ContactUpdated`` with a per-sub-entity
key (``"method_{id}_{field}"``); a new ``ContactSummaryUpdated`` covers summaries so
the projection can reproduce the dual-write rows.
"""

from datetime import datetime

from core_shared.models.history import Provenance

from app.core.contacts.models.events import (
    ContactAddressAdded,
    ContactCreated,
    ContactDeleted,
    ContactMethodAdded,
    ContactNoteAdded,
    ContactRelationshipCreated,
    ContactRelationshipDeleted,
    ContactRelationshipUpdated,
    ContactSummaryUpdated,
    ContactUpdated,
    ImportantDateAdded,
    TagAssigned,
    TagRemoved,
)
from tests.integration.contact_seeding import TEST_USER_ID


class TestContactCreated:
    """Test ContactCreated event."""

    def test_create_event_with_last_name(self):
        """Test creating ContactCreated event with last name."""
        event = ContactCreated(
            user_id=TEST_USER_ID, contact_id=1, first_name="John", last_name="Doe"
        )

        assert event.aggregate_id == 1
        assert event.event_type == "ContactCreated"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["first_name"] == "John"
        assert event.event_data["last_name"] == "Doe"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_created_1_")

    def test_create_event_without_last_name(self):
        """Test creating ContactCreated event without last name."""
        event = ContactCreated(contact_id=2, first_name="Jane", user_id=TEST_USER_ID)

        assert event.aggregate_id == 2
        assert event.event_type == "ContactCreated"
        assert event.event_data["contact_id"] == 2
        assert event.event_data["first_name"] == "Jane"
        assert event.event_data["last_name"] is None
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_created_2_")


class TestContactUpdated:
    """Test ContactUpdated event."""

    def test_create_event(self):
        """Test creating ContactUpdated event."""
        changed_fields = {
            "first_name": ("John", "Jonathan"),
            "email": ("old@example.com", "new@example.com"),
        }

        event = ContactUpdated(
            user_id=TEST_USER_ID, contact_id=1, changed_fields=changed_fields
        )

        assert event.aggregate_id == 1
        assert event.event_type == "ContactUpdated"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["changed_fields"] == changed_fields
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_updated_1_")


class TestContactDeleted:
    """Test ContactDeleted event."""

    def test_create_event(self):
        """Test creating ContactDeleted event."""
        event = ContactDeleted(contact_id=1, user_id=TEST_USER_ID)

        assert event.aggregate_id == 1
        assert event.event_type == "ContactDeleted"
        assert event.event_data["contact_id"] == 1
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_deleted_1_")


class TestTagAssigned:
    """Test TagAssigned event."""

    def test_create_event(self):
        """Test creating TagAssigned event."""
        event = TagAssigned(
            user_id=TEST_USER_ID, contact_id=1, tag_id=2, tag_name="work"
        )

        assert event.aggregate_id == 1
        assert event.event_type == "TagAssigned"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["tag_id"] == 2
        assert event.event_data["tag_name"] == "work"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("tag_assigned_1_2_")


class TestTagRemoved:
    """Test TagRemoved event."""

    def test_create_event(self):
        """Test creating TagRemoved event."""
        event = TagRemoved(
            user_id=TEST_USER_ID, contact_id=1, tag_id=2, tag_name="work"
        )

        assert event.aggregate_id == 1
        assert event.event_type == "TagRemoved"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["tag_id"] == 2
        assert event.event_data["tag_name"] == "work"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("tag_removed_1_2_")


class TestContactMethodAdded:
    """Test ContactMethodAdded event."""

    def test_create_event(self):
        """Test creating ContactMethodAdded event."""
        event = ContactMethodAdded(
            user_id=TEST_USER_ID,
            contact_id=1,
            method_id=2,
            method_type="email",
            value="test@example.com",
        )

        assert event.aggregate_id == 1
        assert event.event_type == "ContactMethodAdded"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["method_id"] == 2
        assert event.event_data["method_type"] == "email"
        assert event.event_data["value"] == "test@example.com"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_method_added_1_2_")


class TestContactAddressAdded:
    """Test ContactAddressAdded event."""

    def test_create_event(self):
        """Test creating ContactAddressAdded event."""
        event = ContactAddressAdded(
            user_id=TEST_USER_ID,
            contact_id=1,
            address_id=2,
            street_line_1="123 Main St",
            country_code="AU",
        )

        assert event.aggregate_id == 1
        assert event.event_type == "ContactAddressAdded"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["address_id"] == 2
        assert event.event_data["street_line_1"] == "123 Main St"
        assert event.event_data["country_code"] == "AU"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_address_added_1_2_")


class TestContactNoteAdded:
    """Test ContactNoteAdded event."""

    def test_create_event_short_content(self):
        """Test creating ContactNoteAdded event with short content."""
        event = ContactNoteAdded(
            user_id=TEST_USER_ID, contact_id=1, note_id=2, content="Short note"
        )

        assert event.aggregate_id == 1
        assert event.event_type == "ContactNoteAdded"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["note_id"] == 2
        assert event.event_data["content"] == "Short note"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_note_added_1_2_")

    def test_create_event_long_content_truncated(self):
        """Test creating ContactNoteAdded event with long content gets truncated."""
        long_content = "x" * 150  # 150 characters
        event = ContactNoteAdded(
            user_id=TEST_USER_ID, contact_id=1, note_id=2, content=long_content
        )

        assert event.aggregate_id == 1
        assert event.event_type == "ContactNoteAdded"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["note_id"] == 2
        # Content should be truncated to 100 chars + "..."
        expected_content = "x" * 100 + "..."
        assert event.event_data["content"] == expected_content
        assert len(event.event_data["content"]) == 103
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("contact_note_added_1_2_")


class TestProvenanceEnrichment:
    """Every contact event carries source + changed_by, defaulting to system."""

    def test_contact_created_defaults_to_system(self) -> None:
        event = ContactCreated(contact_id=1, first_name="John", user_id=TEST_USER_ID)

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_contact_created_explicit_provenance(self) -> None:
        event = ContactCreated(
            user_id=TEST_USER_ID,
            contact_id=1,
            first_name="John",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    def test_contact_updated_carries_provenance(self) -> None:
        event = ContactUpdated(
            user_id=TEST_USER_ID,
            contact_id=1,
            changed_fields={"first_name": ("A", "B")},
            source=Provenance.MCP,
            changed_by="mcp",
        )

        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"

    def test_contact_deleted_carries_provenance(self) -> None:
        event = ContactDeleted(
            user_id=TEST_USER_ID, contact_id=1, source=Provenance.UI, changed_by="ui"
        )

        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    def test_tag_assigned_carries_provenance(self) -> None:
        event = TagAssigned(
            user_id=TEST_USER_ID,
            contact_id=1,
            tag_id=2,
            tag_name="work",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    def test_tag_removed_carries_provenance(self) -> None:
        event = TagRemoved(
            user_id=TEST_USER_ID,
            contact_id=1,
            tag_id=2,
            tag_name="work",
            source=Provenance.MCP,
            changed_by="mcp",
        )

        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"

    def test_method_added_carries_provenance(self) -> None:
        event = ContactMethodAdded(
            user_id=TEST_USER_ID,
            contact_id=1,
            method_id=2,
            method_type="email",
            value="a@b.com",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    def test_address_added_carries_provenance(self) -> None:
        event = ContactAddressAdded(
            user_id=TEST_USER_ID,
            contact_id=1,
            address_id=2,
            street_line_1="1 St",
            country_code="AU",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    def test_note_added_carries_provenance(self) -> None:
        event = ContactNoteAdded(
            user_id=TEST_USER_ID,
            contact_id=1,
            note_id=2,
            content="Hi",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"


class TestAffectsHistoryFlag:
    """ITER12-003 Phase 2: per-item add/assign events default ``affects_history``
    True (create/standalone paths record per-item history), but the bulk re-save
    path passes ``affects_history=False`` so the history projection skips the
    spurious per-item markers while search still consumes the event."""

    def test_method_added_defaults_affects_history_true(self) -> None:
        event = ContactMethodAdded(
            user_id=TEST_USER_ID,
            contact_id=1,
            method_id=2,
            method_type="email",
            value="a@b.com",
        )

        assert event.event_data["affects_history"] is True

    def test_method_added_accepts_affects_history_false(self) -> None:
        event = ContactMethodAdded(
            user_id=TEST_USER_ID,
            contact_id=1,
            method_id=2,
            method_type="email",
            value="a@b.com",
            affects_history=False,
        )

        assert event.event_data["affects_history"] is False

    def test_address_added_carries_affects_history(self) -> None:
        assert (
            ContactAddressAdded(
                user_id=TEST_USER_ID,
                contact_id=1,
                address_id=2,
                street_line_1="1 St",
                country_code="AU",
            ).event_data["affects_history"]
            is True
        )
        assert (
            ContactAddressAdded(
                user_id=TEST_USER_ID,
                contact_id=1,
                address_id=2,
                street_line_1="1 St",
                country_code="AU",
                affects_history=False,
            ).event_data["affects_history"]
            is False
        )

    def test_note_added_carries_affects_history(self) -> None:
        assert (
            ContactNoteAdded(
                user_id=TEST_USER_ID, contact_id=1, note_id=2, content="Hi"
            ).event_data["affects_history"]
            is True
        )
        assert (
            ContactNoteAdded(
                user_id=TEST_USER_ID,
                contact_id=1,
                note_id=2,
                content="Hi",
                affects_history=False,
            ).event_data["affects_history"]
            is False
        )

    def test_important_date_added_carries_affects_history(self) -> None:
        assert (
            ImportantDateAdded(
                user_id=TEST_USER_ID, contact_id=1, date_id=2, date_type="birthday"
            ).event_data["affects_history"]
            is True
        )
        assert (
            ImportantDateAdded(
                user_id=TEST_USER_ID,
                contact_id=1,
                date_id=2,
                date_type="birthday",
                affects_history=False,
            ).event_data["affects_history"]
            is False
        )

    def test_tag_assigned_carries_affects_history(self) -> None:
        assert (
            TagAssigned(
                user_id=TEST_USER_ID, contact_id=1, tag_id=2, tag_name="work"
            ).event_data["affects_history"]
            is True
        )
        assert (
            TagAssigned(
                user_id=TEST_USER_ID,
                contact_id=1,
                tag_id=2,
                tag_name="work",
                affects_history=False,
            ).event_data["affects_history"]
            is False
        )


class TestContactUpdatedSubEntityKeys:
    """Sub-entity field edits publish ContactUpdated with a per-sub-entity key
    (the core contact event downstream relies on, kept rather than a new event)."""

    def test_method_field_edit_uses_mangled_key(self) -> None:
        event = ContactUpdated(
            user_id=TEST_USER_ID,
            contact_id=1,
            changed_fields={"method_2_value": ("a@b.com", "c@d.com")},
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_type == "ContactUpdated"
        assert event.event_data["changed_fields"] == {
            "method_2_value": ("a@b.com", "c@d.com")
        }
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"


class TestContactSummaryUpdated:
    def test_create_event(self) -> None:
        event = ContactSummaryUpdated(
            contact_id=1,
            changed_fields={"summary_text": ("old", "new")},
            source=Provenance.SUMMARY_REGENERATION,
            changed_by="system",
        )

        assert event.aggregate_id == 1
        assert event.event_type == "ContactSummaryUpdated"
        assert event.event_data["contact_id"] == 1
        assert event.event_data["changed_fields"] == {"summary_text": ("old", "new")}
        assert event.event_data["source"] == Provenance.SUMMARY_REGENERATION.value
        assert event.event_data["changed_by"] == "system"
        assert event.event_id.startswith("contact_summary_updated_1_")

    def test_defaults_to_summary_regeneration(self) -> None:
        event = ContactSummaryUpdated(
            contact_id=1, changed_fields={"summary_text": ("a", "b")}
        )

        assert event.event_data["source"] == Provenance.SUMMARY_REGENERATION.value
        assert event.event_data["changed_by"] == "system"


class TestContactRelationshipProvenance:
    def test_created_carries_provenance(self) -> None:
        event = ContactRelationshipCreated(
            relationship_id=9,
            from_contact_id=1,
            to_contact_id=2,
            relationship_type="friend",
            to_user=False,
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    def test_updated_carries_changed_fields_and_provenance(self) -> None:
        event = ContactRelationshipUpdated(
            relationship_id=9,
            from_contact_id=1,
            to_contact_id=2,
            relationship_type="colleague",
            to_user=False,
            changed_fields={"relationship_type": ("friend", "colleague")},
            source=Provenance.MCP,
            changed_by="mcp",
        )

        assert event.event_data["changed_fields"] == {
            "relationship_type": ("friend", "colleague")
        }
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"

    def test_deleted_carries_provenance(self) -> None:
        event = ContactRelationshipDeleted(
            relationship_id=9,
            from_contact_id=1,
            to_contact_id=2,
            relationship_type="friend",
            to_user=False,
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

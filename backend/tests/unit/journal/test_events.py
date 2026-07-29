"""Unit tests for journal domain events.

Covers ITER12-002 Phase 1 event enrichment: every journal/route/gear event must
carry ``source`` (Provenance) and ``changed_by`` in its ``event_data`` so the
history projection consumer can record provenance; route/gear events must also
carry ``journal_id`` so changes can be grouped to their parent journal.
"""

from datetime import datetime
from uuid import uuid4

from core_shared.models.history import Provenance

from app.core.journal.models.events import (
    GearItemUpdated,
    JournalCreated,
    JournalDeleted,
    JournalTagAssigned,
    JournalTagRemoved,
    JournalTagRenamed,
    JournalTypeAdded,
    JournalTypeRemoved,
    JournalUpdated,
    RouteCreated,
    RouteDeleted,
    RouteUpdated,
)


class TestJournalCreated:
    """JournalCreated carries provenance."""

    def test_defaults_to_system_provenance(self) -> None:
        event = JournalCreated(journal_id=1, user_id="user-1", title="Hike")

        assert event.aggregate_id == 1
        assert event.event_type == "JournalCreated"
        assert event.event_data["journal_id"] == 1
        assert event.event_data["user_id"] == "user-1"
        assert event.event_data["title"] == "Hike"
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith("journal_created_1_")

    def test_explicit_provenance_round_trips(self) -> None:
        event = JournalCreated(
            journal_id=2,
            user_id="user-2",
            title="Trip",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"


class TestJournalUpdated:
    """JournalUpdated carries changed_fields and provenance."""

    def test_create_event(self) -> None:
        changed_fields = {
            "title": ("Old", "New"),
            "body": ("a", "b"),
        }
        event = JournalUpdated(
            journal_id=1,
            changed_fields=changed_fields,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        assert event.aggregate_id == 1
        assert event.event_type == "JournalUpdated"
        assert event.event_data["journal_id"] == 1
        assert event.event_data["changed_fields"] == changed_fields
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"
        assert event.event_id.startswith("journal_updated_1_")

    def test_defaults_to_system_provenance(self) -> None:
        event = JournalUpdated(journal_id=1, changed_fields={"title": ("a", "b")})

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"


class TestJournalDeleted:
    """JournalDeleted carries provenance."""

    def test_create_event(self) -> None:
        event = JournalDeleted(
            journal_id=1,
            user_id="user-1",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.aggregate_id == 1
        assert event.event_type == "JournalDeleted"
        assert event.event_data["journal_id"] == 1
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"
        assert event.event_id.startswith("journal_deleted_1_")

    def test_defaults_to_system_provenance(self) -> None:
        event = JournalDeleted(journal_id=1, user_id="user-1")

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"


class TestJournalTypeAdded:
    """JournalTypeAdded carries provenance and encodes the type in its event_id."""

    def test_create_event(self) -> None:
        event = JournalTypeAdded(
            journal_id=1,
            journal_type="EVENT",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.aggregate_id == 1
        assert event.event_type == "JournalTypeAdded"
        assert event.event_data["journal_id"] == 1
        assert event.event_data["journal_type"] == "EVENT"
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"
        # event_id includes the type so add/remove of different types never collide.
        assert event.event_id.startswith("journal_type_added_1_EVENT_")

    def test_defaults_to_system_provenance(self) -> None:
        event = JournalTypeAdded(journal_id=1, journal_type="NOTE")

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"


class TestJournalTypeRemoved:
    """JournalTypeRemoved carries provenance and encodes the type in its event_id."""

    def test_create_event(self) -> None:
        event = JournalTypeRemoved(
            journal_id=1,
            journal_type="EVENT",
            source=Provenance.MCP,
            changed_by="mcp",
        )

        assert event.event_type == "JournalTypeRemoved"
        assert event.event_data["journal_type"] == "EVENT"
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"
        assert event.event_id.startswith("journal_type_removed_1_EVENT_")


class TestJournalTagAssigned:
    """JournalTagAssigned names the tag so history can read without a join."""

    def test_create_event(self) -> None:
        tag_id = uuid4()

        event = JournalTagAssigned(
            journal_id=7,
            tag_id=tag_id,
            tag_name="Hiking",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.aggregate_id == 7
        assert event.event_type == "JournalTagAssigned"
        assert event.event_data["journal_id"] == 7
        # Stringified: the payload round-trips through JSON/Redis to the projection.
        assert event.event_data["tag_id"] == str(tag_id)
        assert event.event_data["tag_name"] == "Hiking"
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith(f"journal_tag_assigned_7_{tag_id}_")

    def test_defaults_to_system_provenance(self) -> None:
        event = JournalTagAssigned(journal_id=1, tag_id=uuid4(), tag_name="Work")

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_event_ids_differ_per_tag(self) -> None:
        """Two tags assigned to one journal must not share an event_id.

        The history dedup index is keyed on ``event_id`` (plus entity and field),
        so a shared id would silently drop the second tag's row.
        """
        first = JournalTagAssigned(journal_id=1, tag_id=uuid4(), tag_name="a")
        second = JournalTagAssigned(journal_id=1, tag_id=uuid4(), tag_name="b")

        assert first.event_id != second.event_id


class TestJournalTagRemoved:
    """JournalTagRemoved mirrors the assignment event."""

    def test_create_event(self) -> None:
        tag_id = uuid4()

        event = JournalTagRemoved(
            journal_id=9,
            tag_id=tag_id,
            tag_name="Hiking",
            source=Provenance.MCP,
            changed_by="mcp",
        )

        assert event.aggregate_id == 9
        assert event.event_type == "JournalTagRemoved"
        assert event.event_data["journal_id"] == 9
        assert event.event_data["tag_id"] == str(tag_id)
        assert event.event_data["tag_name"] == "Hiking"
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"
        assert event.event_id.startswith(f"journal_tag_removed_9_{tag_id}_")

    def test_defaults_to_system_provenance(self) -> None:
        event = JournalTagRemoved(journal_id=1, tag_id=uuid4(), tag_name="Work")

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"


class TestJournalTagRenamed:
    """JournalTagRenamed carries both names so history reads as a field change.

    Renaming a tag is published once per journal carrying it — the journal is the
    aggregate whose feed the entry lands in, and a tag-scoped event would have no
    integer ``aggregate_id`` to use, journal tags being UUID-keyed.
    """

    def test_create_event(self) -> None:
        tag_id = uuid4()

        event = JournalTagRenamed(
            journal_id=11,
            tag_id=tag_id,
            old_name="Hiking",
            new_name="Trekking",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.aggregate_id == 11
        assert event.event_type == "JournalTagRenamed"
        assert event.event_data["journal_id"] == 11
        # Stringified: the payload round-trips through JSON/Redis to the projection.
        assert event.event_data["tag_id"] == str(tag_id)
        assert event.event_data["old_name"] == "Hiking"
        assert event.event_data["new_name"] == "Trekking"
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"
        assert isinstance(event.occurred_at, datetime)
        assert event.event_id.startswith(f"journal_tag_renamed_11_{tag_id}_")

    def test_defaults_to_system_provenance(self) -> None:
        event = JournalTagRenamed(
            journal_id=1, tag_id=uuid4(), old_name="Work", new_name="Career"
        )

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_event_ids_differ_per_journal(self) -> None:
        """One rename fans out to every tagged journal with distinct event_ids.

        The history dedup index is keyed on ``event_id`` (plus entity and field),
        so a shared id would silently drop every journal's row but the first.
        """
        tag_id = uuid4()
        first = JournalTagRenamed(
            journal_id=1, tag_id=tag_id, old_name="a", new_name="b"
        )
        second = JournalTagRenamed(
            journal_id=2, tag_id=tag_id, old_name="a", new_name="b"
        )

        assert first.event_id != second.event_id


class TestRouteCreated:
    """RouteCreated carries journal_id and provenance."""

    def test_create_event(self) -> None:
        route_id = str(uuid4())
        event = RouteCreated(
            route_id=route_id,
            journal_id=42,
            name="Summit Loop",
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_type == "RouteCreated"
        assert event.event_data["route_id"] == route_id
        assert event.event_data["journal_id"] == 42
        assert event.event_data["name"] == "Summit Loop"
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"


class TestRouteUpdated:
    """RouteUpdated carries journal_id (new) and provenance."""

    def test_create_event(self) -> None:
        route_id = str(uuid4())
        changed_fields = {"name": ("Old", "New")}
        event = RouteUpdated(
            route_id=route_id,
            journal_id=42,
            changed_fields=changed_fields,
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_type == "RouteUpdated"
        assert event.event_data["route_id"] == route_id
        assert event.event_data["journal_id"] == 42
        assert event.event_data["changed_fields"] == changed_fields
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    def test_defaults_to_system_provenance(self) -> None:
        event = RouteUpdated(
            route_id=str(uuid4()),
            journal_id=1,
            changed_fields={"name": ("a", "b")},
        )

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"


class TestRouteDeleted:
    """RouteDeleted carries journal_id (new) and provenance."""

    def test_create_event(self) -> None:
        route_id = str(uuid4())
        event = RouteDeleted(
            route_id=route_id,
            journal_id=42,
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_type == "RouteDeleted"
        assert event.event_data["route_id"] == route_id
        assert event.event_data["journal_id"] == 42
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"


class TestGearItemUpdated:
    """GearItemUpdated carries optional journal_id and provenance."""

    def test_create_event_with_journal_id(self) -> None:
        gear_id = str(uuid4())
        changed_fields = {"model": ("Old", "New")}
        event = GearItemUpdated(
            gear_item_id=gear_id,
            changed_fields=changed_fields,
            journal_id=42,
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_type == "GearItemUpdated"
        assert event.event_data["gear_item_id"] == gear_id
        assert event.event_data["journal_id"] == 42
        assert event.event_data["changed_fields"] == changed_fields
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    def test_journal_id_optional_defaults_none(self) -> None:
        event = GearItemUpdated(
            gear_item_id=str(uuid4()),
            changed_fields={"model": ("a", "b")},
        )

        assert event.event_data["journal_id"] is None
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

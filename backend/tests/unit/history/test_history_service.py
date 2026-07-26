"""Unit tests for HistoryService.project_event (ITER12-002 Phase 1).

project_event is a pure mapping from a journal/route/gear domain event (as an
OutboxEvent) to the FieldHistoryEntry rows that should be written. Each row must
carry provenance (source/changed_by), the originating event_id (for idempotency),
and created_at = event.occurred_at (so history reflects when the change happened).

changed_fields values arrive as lists after the JSON round-trip through Redis, so
the mapping indexes [old, new] rather than unpacking a tuple.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.history import Provenance

from app.core.history.services.history_service import HistoryService
from app.infrastructure.events.outbox_repository import OutboxEvent

OCCURRED_AT = datetime(2024, 3, 1, 8, 0, 0, tzinfo=UTC)


def _event(
    event_type: str, event_data: dict[str, Any], *, event_id: str = "evt-1"
) -> OutboxEvent:
    return OutboxEvent(
        id=0,
        event_id=event_id,
        event_type=event_type,
        aggregate_id=event_data.get("journal_id", 0),
        event_data=event_data,
        occurred_at=OCCURRED_AT,
        retry_count=0,
        created_at=OCCURRED_AT,
    )


@pytest.fixture
def service() -> HistoryService:
    return HistoryService()


class TestJournalCreated:
    def test_produces_created_marker(self, service: HistoryService) -> None:
        event = _event(
            "JournalCreated",
            {
                "journal_id": 10,
                "user_id": "u1",
                "title": "Hike",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 1
        row = rows[0]
        assert row.entity_type == "journal"
        assert row.entity_id == 10
        assert row.field_name == "__created__"
        assert row.old_value is None
        assert row.new_value == "Hike"
        assert row.source == Provenance.UI
        assert row.changed_by == "ui"
        assert row.event_id == "evt-1"
        assert row.created_at == OCCURRED_AT


class TestJournalUpdated:
    def test_one_row_per_changed_field(self, service: HistoryService) -> None:
        event = _event(
            "JournalUpdated",
            {
                "journal_id": 10,
                # Lists, mirroring the JSON round-trip through Redis.
                "changed_fields": {"title": ["Old", "New"], "body": ["a", "b"]},
                "source": Provenance.MCP.value,
                "changed_by": "mcp",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 2
        by_field = {r.field_name: r for r in rows}
        assert by_field["title"].old_value == "Old"
        assert by_field["title"].new_value == "New"
        assert by_field["body"].old_value == "a"
        assert by_field["body"].new_value == "b"
        for r in rows:
            assert r.entity_type == "journal"
            assert r.entity_id == 10
            assert r.source == Provenance.MCP
            assert r.changed_by == "mcp"
            assert r.created_at == OCCURRED_AT

    def test_no_changed_fields_produces_no_rows(self, service: HistoryService) -> None:
        event = _event(
            "JournalUpdated",
            {
                "journal_id": 10,
                "changed_fields": {},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        assert service.project_event(event) == []

    def test_non_pair_changed_field_is_skipped(self, service: HistoryService) -> None:
        """Internal sync-trigger signals (non (old,new) pairs) produce no history."""
        event = _event(
            "JournalUpdated",
            {
                "journal_id": 10,
                # {"calendar_info": True} is a calendar-sync trigger, not a change.
                "changed_fields": {"calendar_info": True, "title": ["a", "b"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 1
        assert rows[0].field_name == "title"

    def test_only_sync_signal_produces_no_rows(self, service: HistoryService) -> None:
        event = _event(
            "JournalUpdated",
            {
                "journal_id": 10,
                "changed_fields": {"calendar_info": True},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        assert service.project_event(event) == []

    def test_none_values_are_preserved(self, service: HistoryService) -> None:
        event = _event(
            "JournalUpdated",
            {
                "journal_id": 10,
                "changed_fields": {"body": [None, "set"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert rows[0].old_value is None
        assert rows[0].new_value == "set"


class TestJournalDeleted:
    def test_produces_deleted_marker(self, service: HistoryService) -> None:
        event = _event(
            "JournalDeleted",
            {
                "journal_id": 10,
                "user_id": "u1",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 1
        assert rows[0].field_name == "__deleted__"
        assert rows[0].entity_type == "journal"
        assert rows[0].entity_id == 10


class TestJournalType:
    def test_added_writes_types_field(self, service: HistoryService) -> None:
        event = _event(
            "JournalTypeAdded",
            {
                "journal_id": 10,
                "journal_type": "EVENT",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 1
        assert rows[0].field_name == "types"
        assert rows[0].old_value is None
        assert rows[0].new_value == "EVENT"

    def test_removed_writes_types_field(self, service: HistoryService) -> None:
        event = _event(
            "JournalTypeRemoved",
            {
                "journal_id": 10,
                "journal_type": "EVENT",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 1
        assert rows[0].field_name == "types"
        assert rows[0].old_value == "EVENT"
        assert rows[0].new_value is None


class TestRoute:
    def test_created_marker_grouped_to_journal(self, service: HistoryService) -> None:
        event = _event(
            "RouteCreated",
            {
                "route_id": "r-abc",
                "journal_id": 10,
                "name": "Summit Loop",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 1
        assert rows[0].entity_type == "journal"
        assert rows[0].entity_id == 10
        assert rows[0].field_name == "route:r-abc:__created__"
        assert rows[0].new_value == "Summit Loop"

    def test_updated_one_row_per_field(self, service: HistoryService) -> None:
        event = _event(
            "RouteUpdated",
            {
                "route_id": "r-abc",
                "journal_id": 10,
                "changed_fields": {"name": ["Old", "New"], "distance": ["1", "2"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 2
        fields = {r.field_name for r in rows}
        assert fields == {"route:r-abc:name", "route:r-abc:distance"}
        for r in rows:
            assert r.entity_type == "journal"
            assert r.entity_id == 10

    def test_deleted_marker_grouped_to_journal(self, service: HistoryService) -> None:
        event = _event(
            "RouteDeleted",
            {
                "route_id": "r-abc",
                "journal_id": 10,
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 1
        assert rows[0].entity_type == "journal"
        assert rows[0].entity_id == 10
        assert rows[0].field_name == "route:r-abc:__deleted__"

    @pytest.mark.parametrize(
        "event_type",
        ["RouteCreated", "RouteUpdated", "RouteDeleted"],
    )
    def test_route_event_without_journal_id_is_skipped(
        self, service: HistoryService, event_type: str
    ) -> None:
        """Historical route events emitted before journal_id enrichment must be
        skipped (not raise), since the group replays the stream from id 0."""
        event = _event(
            event_type,
            {
                "route_id": "r-old",
                "name": "Legacy",
                "changed_fields": {"name": ["a", "b"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        assert service.project_event(event) == []


class TestGearItemUpdated:
    def test_grouped_to_journal_when_journal_id_present(
        self, service: HistoryService
    ) -> None:
        event = _event(
            "GearItemUpdated",
            {
                "gear_item_id": "g-1",
                "journal_id": 10,
                "changed_fields": {"model": ["Old", "New"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len(rows) == 1
        assert rows[0].entity_type == "journal"
        assert rows[0].entity_id == 10
        assert rows[0].field_name == "gear:g-1:model"

    def test_skipped_when_no_journal_id(self, service: HistoryService) -> None:
        event = _event(
            "GearItemUpdated",
            {
                "gear_item_id": "g-1",
                "journal_id": None,
                "changed_fields": {"model": ["Old", "New"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        assert service.project_event(event) == []


class TestJournalTags:
    """Journal tag assignment/removal projects onto the journal itself.

    Deliberately the same ``field_name="tags"`` shape as the contact tag rows
    (``TestContactTags``) so the shared ActivityItem renders both identically.
    """

    def test_assigned_writes_tags_field_on_journal(
        self, service: HistoryService
    ) -> None:
        event = _event(
            "JournalTagAssigned",
            {
                "journal_id": 10,
                "tag_id": "3f7c1f0e-0000-4000-8000-000000000001",
                "tag_name": "Hiking",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("journal", 10, "tags", None, "Hiking")
        ]

    def test_removed_writes_tags_field_on_journal(
        self, service: HistoryService
    ) -> None:
        event = _event(
            "JournalTagRemoved",
            {
                "journal_id": 10,
                "tag_id": "3f7c1f0e-0000-4000-8000-000000000001",
                "tag_name": "Hiking",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("journal", 10, "tags", "Hiking", None)
        ]

    def test_missing_tag_name_projects_nothing(self, service: HistoryService) -> None:
        """A payload without ``tag_name`` yields no row, and does not raise.

        Raising would park the whole batch in the dead-letter queue and stall
        history for every event behind it; emitting the row anyway would render as
        "Changed Tags from null to null" in the feed.
        """
        event = _event(
            "JournalTagAssigned",
            {
                "journal_id": 12,
                "tag_id": "3f7c1f0e-0000-4000-8000-000000000003",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        assert service.project_event(event) == []


# --------------------------------------------------------------------------- #
# Contact event projection (ITER12-003 Phase 1).
#
# Each contact handler must reproduce the EXACT rows the synchronous dual-write
# (ContactHistoryService.record_*) writes today, so the projection can replace it
# in Phase 2 without changing the user-visible feed. The contact aggregation
# strategy keys on these (entity_type, entity_id) pairs:
#   contact / contact_id          (base fields, "tags", "status")
#   contact_method / method_id
#   contact_address / address_id
#   contact_note / note_id
#   contact_important_date / date_id
#   contact_relationship / relationship_id
#   contact_summary / contact_id
# --------------------------------------------------------------------------- #


def _row_tuple(row: Any) -> tuple[str, int, str, str | None, str | None]:
    return (
        row.entity_type,
        row.entity_id,
        row.field_name,
        row.old_value,
        row.new_value,
    )


class TestContactCreated:
    def test_projects_only_contact_status_marker(self, service: HistoryService) -> None:
        # ContactCreated carries only the contact-level marker; per-sub-entity
        # "created" markers come from the ContactMethodAdded / *AddressAdded /
        # *NoteAdded / ImportantDateAdded events published alongside, so they are
        # not duplicated by the ContactCreated projection.
        event = _event(
            "ContactCreated",
            {
                "contact_id": 5,
                "first_name": "John",
                "last_name": "Doe",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact", 5, "status", None, "created")
        ]
        assert rows[0].source == Provenance.UI
        assert rows[0].changed_by == "ui"
        assert rows[0].event_id == "evt-1"
        assert rows[0].created_at == OCCURRED_AT


class TestContactUpdated:
    def test_one_row_per_changed_field(self, service: HistoryService) -> None:
        event = _event(
            "ContactUpdated",
            {
                "contact_id": 5,
                "changed_fields": {
                    "first_name": ["John", "Jonathan"],
                    "last_name": ["Doe", "Smith"],
                },
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert {_row_tuple(r) for r in rows} == {
            ("contact", 5, "first_name", "John", "Jonathan"),
            ("contact", 5, "last_name", "Doe", "Smith"),
        }

    def test_empty_changed_fields_produces_no_rows(
        self, service: HistoryService
    ) -> None:
        event = _event(
            "ContactUpdated",
            {"contact_id": 5, "changed_fields": {}, "source": "ui", "changed_by": "ui"},
        )

        assert service.project_event(event) == []

    def test_sub_entity_keys_route_to_sub_entity_rows(
        self, service: HistoryService
    ) -> None:
        """Sub-entity field edits arrive as ContactUpdated with a per-sub-entity
        key; the projection decodes "{prefix}_{id}_{field}" to the right row
        (method/address/note), matching the dual-write's record_*_change."""
        event = _event(
            "ContactUpdated",
            {
                "contact_id": 5,
                "changed_fields": {
                    "first_name": ["John", "Jane"],
                    "method_11_value": ["a@b.com", "c@d.com"],
                    "address_21_street_line_1": ["1 St", "2 Ave"],
                    "note_31_content": ["Hi", "Hello"],
                },
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert {_row_tuple(r) for r in rows} == {
            ("contact", 5, "first_name", "John", "Jane"),
            ("contact_method", 11, "value", "a@b.com", "c@d.com"),
            ("contact_address", 21, "street_line_1", "1 St", "2 Ave"),
            ("contact_note", 31, "content", "Hi", "Hello"),
        }

    def test_field_name_with_underscores_is_preserved(
        self, service: HistoryService
    ) -> None:
        """The decoded field keeps trailing underscores (e.g. is_primary)."""
        event = _event(
            "ContactUpdated",
            {
                "contact_id": 5,
                "changed_fields": {"method_11_is_primary": ["False", "True"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_method", 11, "is_primary", "False", "True")
        ]


class TestContactDeleted:
    def test_status_deleted_marker(self, service: HistoryService) -> None:
        event = _event(
            "ContactDeleted",
            {"contact_id": 5, "source": Provenance.UI.value, "changed_by": "ui"},
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact", 5, "status", "active", "deleted")
        ]


class TestContactMethod:
    def test_added_status_marker(self, service: HistoryService) -> None:
        event = _event(
            "ContactMethodAdded",
            {
                "contact_id": 5,
                "method_id": 11,
                "method_type": "email",
                "value": "a@b.com",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_method", 11, "status", None, "created")
        ]

    def test_deleted_status_marker(self, service: HistoryService) -> None:
        event = _event(
            "ContactMethodDeleted",
            {
                "contact_id": 5,
                "method_id": 11,
                "method_type": "email",
                "value": "a@b.com",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_method", 11, "status", "active", "deleted")
        ]


class TestContactAddress:
    def test_added_status_marker(self, service: HistoryService) -> None:
        event = _event(
            "ContactAddressAdded",
            {
                "contact_id": 5,
                "address_id": 21,
                "street_line_1": "1 St",
                "country_code": "AU",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_address", 21, "status", None, "created")
        ]

    def test_deleted_status_marker(self, service: HistoryService) -> None:
        event = _event(
            "ContactAddressDeleted",
            {
                "contact_id": 5,
                "address_id": 21,
                "street_line_1": "1 St",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_address", 21, "status", "active", "deleted")
        ]


class TestContactNote:
    def test_added_status_marker(self, service: HistoryService) -> None:
        event = _event(
            "ContactNoteAdded",
            {
                "contact_id": 5,
                "note_id": 31,
                "content": "Hi",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_note", 31, "status", None, "created")
        ]


class TestContactImportantDate:
    def test_added_status_marker(self, service: HistoryService) -> None:
        event = _event(
            "ImportantDateAdded",
            {
                "contact_id": 5,
                "date_id": 41,
                "date_type": "birthday",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_important_date", 41, "status", None, "created")
        ]

    def test_deleted_status_marker(self, service: HistoryService) -> None:
        event = _event(
            "ImportantDateDeleted",
            {
                "contact_id": 5,
                "date_id": 41,
                "date_type": "birthday",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_important_date", 41, "status", "active", "deleted")
        ]


class TestContactTags:
    def test_assigned_writes_tags_field_on_contact(
        self, service: HistoryService
    ) -> None:
        event = _event(
            "TagAssigned",
            {
                "contact_id": 5,
                "tag_id": 7,
                "tag_name": "work",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [("contact", 5, "tags", None, "work")]

    def test_removed_writes_tags_field_on_contact(
        self, service: HistoryService
    ) -> None:
        event = _event(
            "TagRemoved",
            {
                "contact_id": 5,
                "tag_id": 7,
                "tag_name": "work",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [("contact", 5, "tags", "work", None)]


class TestContactRelationship:
    def test_created_writes_status_and_relationship_type(
        self, service: HistoryService
    ) -> None:
        event = _event(
            "ContactRelationshipCreated",
            {
                "relationship_id": 9,
                "from_contact_id": 5,
                "to_contact_id": 6,
                "relationship_type": "friend",
                "to_user": False,
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert {_row_tuple(r) for r in rows} == {
            ("contact_relationship", 9, "status", None, "created"),
            ("contact_relationship", 9, "relationship_type", None, "friend"),
        }

    def test_updated_one_row_per_field(self, service: HistoryService) -> None:
        event = _event(
            "ContactRelationshipUpdated",
            {
                "relationship_id": 9,
                "from_contact_id": 5,
                "to_contact_id": 6,
                "relationship_type": "colleague",
                "to_user": False,
                "changed_fields": {"relationship_type": ["friend", "colleague"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_relationship", 9, "relationship_type", "friend", "colleague")
        ]

    def test_deleted_status_marker(self, service: HistoryService) -> None:
        event = _event(
            "ContactRelationshipDeleted",
            {
                "relationship_id": 9,
                "from_contact_id": 5,
                "to_contact_id": 6,
                "relationship_type": "friend",
                "to_user": False,
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_relationship", 9, "status", "active", "deleted")
        ]


class TestContactSummaryUpdated:
    def test_one_row_per_field_on_contact_summary(
        self, service: HistoryService
    ) -> None:
        event = _event(
            "ContactSummaryUpdated",
            {
                "contact_id": 5,
                "changed_fields": {"summary_text": ["old", "new"]},
                "source": Provenance.SUMMARY_REGENERATION.value,
                "changed_by": "system",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("contact_summary", 5, "summary_text", "old", "new")
        ]
        assert rows[0].source == Provenance.SUMMARY_REGENERATION


class TestAffectsHistoryFlag:
    """ITER12-003 Phase 2: per-item add/assign events emitted during a *bulk*
    contact re-save carry ``affects_history=False`` so the projection skips them
    (the aggregate ``ContactUpdated`` rows are the feed). Search still consumes
    the events; only the history projection honours the flag. A missing key is
    treated as ``True`` for backward compatibility with create/standalone paths.
    """

    @pytest.mark.parametrize(
        ("event_type", "data"),
        [
            (
                "ContactMethodAdded",
                {
                    "contact_id": 5,
                    "method_id": 11,
                    "method_type": "email",
                    "value": "a@b.com",
                },
            ),
            (
                "ContactAddressAdded",
                {
                    "contact_id": 5,
                    "address_id": 21,
                    "street_line_1": "1 St",
                    "country_code": "AU",
                },
            ),
            (
                "ContactNoteAdded",
                {"contact_id": 5, "note_id": 31, "content": "Hi"},
            ),
            (
                "ImportantDateAdded",
                {"contact_id": 5, "date_id": 41, "date_type": "birthday"},
            ),
            (
                "TagAssigned",
                {"contact_id": 5, "tag_id": 7, "tag_name": "work"},
            ),
        ],
    )
    def test_affects_history_false_skips_projection(
        self, service: HistoryService, event_type: str, data: dict[str, Any]
    ) -> None:
        event = _event(
            event_type,
            {**data, "affects_history": False, "source": Provenance.UI.value},
        )

        assert service.project_event(event) == []

    @pytest.mark.parametrize(
        ("event_type", "data", "expected"),
        [
            (
                "ContactMethodAdded",
                {
                    "contact_id": 5,
                    "method_id": 11,
                    "method_type": "email",
                    "value": "a@b.com",
                },
                ("contact_method", 11, "status", None, "created"),
            ),
            (
                "TagAssigned",
                {"contact_id": 5, "tag_id": 7, "tag_name": "work"},
                ("contact", 5, "tags", None, "work"),
            ),
        ],
    )
    def test_affects_history_true_or_absent_projects_rows(
        self,
        service: HistoryService,
        event_type: str,
        data: dict[str, Any],
        expected: tuple[str, int, str, str | None, str | None],
    ) -> None:
        # affects_history=True is explicit; the absent-key case below proves
        # backward compatibility (Phase 1 events have no such key).
        explicit = _event(
            event_type, {**data, "affects_history": True, "source": Provenance.UI.value}
        )
        absent = _event(event_type, {**data, "source": Provenance.UI.value})

        assert [_row_tuple(r) for r in service.project_event(explicit)] == [expected]
        assert [_row_tuple(r) for r in service.project_event(absent)] == [expected]


class TestUnknownAndProvenanceDefaults:
    def test_unknown_event_type_returns_empty(self, service: HistoryService) -> None:
        event = _event("SomethingElse", {"journal_id": 10})

        assert service.project_event(event) == []

    def test_missing_provenance_defaults_to_system(
        self, service: HistoryService
    ) -> None:
        event = _event(
            "JournalCreated",
            {"journal_id": 10, "user_id": "u1", "title": "Hike"},
        )

        rows = service.project_event(event)

        assert rows[0].source == Provenance.SYSTEM
        assert rows[0].changed_by == "system"

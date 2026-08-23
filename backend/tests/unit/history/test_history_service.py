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

from app.core.history.services.history_service import _HANDLERS, HistoryService
from app.infrastructure.events.outbox_repository import OutboxEvent
from tests.task_event_inventory import task_event_types, task_event_types_by_class

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


def _merge_payload(*, already_had_target: bool = False) -> dict[str, Any]:
    """A ``JournalTagMerged`` payload as the service publishes it."""
    return {
        "journal_id": 10,
        "source_tag_id": "3f7c1f0e-0000-4000-8000-000000000007",
        "target_tag_id": "3f7c1f0e-0000-4000-8000-000000000008",
        "source_tag_name": "Hiking",
        "target_tag_name": "Bushwalking",
        "already_had_target": already_had_target,
        "source": Provenance.UI.value,
        "changed_by": "ui",
    }


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

    def test_renamed_writes_an_old_to_new_tags_row(
        self, service: HistoryService
    ) -> None:
        """A rename is a field change on the journal, not an add or a remove.

        Both values present is what makes the shared ActivityItem render
        "Changed Tags from ... to ..." rather than "Added"/"Removed".
        """
        event = _event(
            "JournalTagRenamed",
            {
                "journal_id": 10,
                "tag_id": "3f7c1f0e-0000-4000-8000-000000000002",
                "old_name": "Hiking",
                "new_name": "Trekking",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("journal", 10, "tags", "Hiking", "Trekking")
        ]

    @pytest.mark.parametrize("missing", ["old_name", "new_name"])
    def test_rename_missing_a_name_projects_nothing(
        self, service: HistoryService, missing: str
    ) -> None:
        """Half a rename is unrenderable, so it yields no row rather than raising."""
        payload = {
            "journal_id": 12,
            "tag_id": "3f7c1f0e-0000-4000-8000-000000000004",
            "old_name": "Hiking",
            "new_name": "Trekking",
            "source": Provenance.UI.value,
            "changed_by": "ui",
        }
        del payload[missing]

        assert service.project_event(_event("JournalTagRenamed", payload)) == []

    def test_deleted_writes_a_removal_row(self, service: HistoryService) -> None:
        """Deleting a tag reads on each journal as the tag leaving it.

        Deliberately the same row shape as ``JournalTagRemoved``: from the
        journal's point of view the two are the same change, and the feed should
        not ask the user to care which tag-namespace operation caused it.
        """
        event = _event(
            "JournalTagDeleted",
            {
                "journal_id": 10,
                "tag_id": "3f7c1f0e-0000-4000-8000-000000000005",
                "tag_name": "Hiking",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("journal", 10, "tags", "Hiking", None)
        ]

    def test_delete_missing_tag_name_projects_nothing(
        self, service: HistoryService
    ) -> None:
        """A payload naming no tag yields no row, for the same reason as assign."""
        event = _event(
            "JournalTagDeleted",
            {
                "journal_id": 12,
                "tag_id": "3f7c1f0e-0000-4000-8000-000000000006",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        assert service.project_event(event) == []

    def test_merge_writes_a_source_to_target_swap(
        self, service: HistoryService
    ) -> None:
        """A journal that carried only the source swapped one tag for another.

        Both values present is what makes the shared ActivityItem render
        "Changed Tags from ... to ...", which is what actually happened.
        """
        rows = service.project_event(_event("JournalTagMerged", _merge_payload()))

        assert [_row_tuple(r) for r in rows] == [
            ("journal", 10, "tags", "Hiking", "Bushwalking")
        ]

    def test_merge_onto_a_journal_already_carrying_the_target_is_a_removal(
        self, service: HistoryService
    ) -> None:
        """Nothing arrived on this journal — the source simply left it.

        Rendering the swap here would claim the journal gained a tag it already
        had, which the activity-history spec forbids: history must not record a
        change that did not occur.
        """
        rows = service.project_event(
            _event("JournalTagMerged", _merge_payload(already_had_target=True))
        )

        assert [_row_tuple(r) for r in rows] == [
            ("journal", 10, "tags", "Hiking", None)
        ]

    @pytest.mark.parametrize(
        ("already_had_target", "missing"),
        [
            (False, "source_tag_name"),
            (False, "target_tag_name"),
            (True, "source_tag_name"),
        ],
    )
    def test_merge_missing_a_name_it_needs_projects_nothing(
        self, service: HistoryService, already_had_target: bool, missing: str
    ) -> None:
        """Half a merge is unrenderable, so it yields no row rather than raising.

        The swap branch needs both names: without the guard a missing target name
        would fall through the shared helper as ``("Hiking", None)`` and render as
        a removal that never happened.
        """
        payload = _merge_payload(already_had_target=already_had_target)
        del payload[missing]

        assert service.project_event(_event("JournalTagMerged", payload)) == []

    def test_merge_without_the_flag_projects_nothing(
        self, service: HistoryService
    ) -> None:
        """An absent flag must not silently pick a branch.

        Truthiness would default a malformed payload to the swap, claiming the
        journal gained the target when the producer never said so.
        """
        payload = _merge_payload()
        del payload["already_had_target"]

        assert service.project_event(_event("JournalTagMerged", payload)) == []


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


# --------------------------------------------------------------------------- #
# Task event projection — every type the domain publishes.
#
# A task is a top-level aggregate keyed by its own integer id, so its rows go
# under ("task", task_id) and use the *journal* marker convention (__created__ /
# __deleted__) rather than the contact one (field_name="status"). The contact
# shape exists because contact history spreads across a family of sub-entity
# rows; a task has none.
#
# TestEveryTaskEventTypeIsProjected below turns "every published type is
# projected" from a fact into a failing test for the next one to arrive.
# --------------------------------------------------------------------------- #

TASK_ID = 42
TASK_TEXT = "Book the venue"
CONTACT_ID = 7
OTHER_CONTACT_ID = 9
OLD_JOURNAL_ID = 200
NEW_JOURNAL_ID = 300


def _task_event(
    event_type: str, event_data: dict[str, Any], *, event_id: str = "evt-1"
) -> OutboxEvent:
    """A task event as the outbox stores it — aggregate id is the task."""
    return OutboxEvent(
        id=0,
        event_id=event_id,
        event_type=event_type,
        aggregate_id=event_data.get("task_id", 0),
        event_data=event_data,
        occurred_at=OCCURRED_AT,
        retry_count=0,
        created_at=OCCURRED_AT,
    )


def _task_created_payload(**overrides: Any) -> dict[str, Any]:
    """A ``TaskCreated`` payload as ``TaskService.create_task`` publishes it."""
    payload: dict[str, Any] = {
        "task_id": TASK_ID,
        "user_id": "u1",
        "text": TASK_TEXT,
        "status": "not_done",
        "creating_journal_id": 100,
        "due_journal_id": 200,
        "contact_ids": [],
        "source": Provenance.UI.value,
        "changed_by": "ui",
    }
    payload.update(overrides)
    return payload


class TestTaskCreated:
    def test_projects_a_created_marker_carrying_the_text(
        self, service: HistoryService
    ) -> None:
        rows = service.project_event(
            _task_event("TaskCreated", _task_created_payload())
        )

        assert [_row_tuple(r) for r in rows] == [
            ("task", TASK_ID, "__created__", None, TASK_TEXT)
        ]
        assert rows[0].source == Provenance.UI
        assert rows[0].changed_by == "ui"
        assert rows[0].event_id == "evt-1"
        assert rows[0].created_at == OCCURRED_AT

    def test_names_every_contact_the_task_was_created_with(
        self, service: HistoryService
    ) -> None:
        """A create with people has to announce each of them as an addition.

        ``contact_ids`` is a *list*, not an ``(old, new)`` pair, so the generic
        changed-fields helper cannot fan it out — this handler does. Without it a
        task created with Sarah shows nothing, and a later unlink puts a removal
        in the user's history with no matching addition before it: the exact
        asymmetry Phase 5's payload decision exists to prevent.
        """
        rows = service.project_event(
            _task_event(
                "TaskCreated",
                _task_created_payload(contact_ids=[CONTACT_ID, OTHER_CONTACT_ID]),
            )
        )

        assert [_row_tuple(r) for r in rows] == [
            ("task", TASK_ID, "__created__", None, TASK_TEXT),
            ("task", TASK_ID, f"contact:{CONTACT_ID}", None, str(CONTACT_ID)),
            (
                "task",
                TASK_ID,
                f"contact:{OTHER_CONTACT_ID}",
                None,
                str(OTHER_CONTACT_ID),
            ),
        ]

    def test_every_row_of_a_create_shares_the_event_under_a_distinct_field_name(
        self, service: HistoryService
    ) -> None:
        """One event, several rows — and the dedup index is what makes that safe.

        Rows are written ``ON CONFLICT (event_id, entity_type, entity_id,
        field_name) DO NOTHING``. Three rows of one event therefore only all
        survive because their field names differ, which is why contact keys name
        the contact instead of sharing a ``contacts`` field.
        """
        rows = service.project_event(
            _task_event(
                "TaskCreated",
                _task_created_payload(contact_ids=[CONTACT_ID, OTHER_CONTACT_ID]),
            )
        )

        assert {r.event_id for r in rows} == {"evt-1"}
        assert len({r.field_name for r in rows}) == len(rows)

    def test_a_create_with_nobody_projects_only_the_marker(
        self, service: HistoryService
    ) -> None:
        rows = service.project_event(
            _task_event("TaskCreated", _task_created_payload(contact_ids=[]))
        )

        assert [r.field_name for r in rows] == ["__created__"]

    def test_a_payload_without_contact_ids_projects_only_the_marker(
        self, service: HistoryService
    ) -> None:
        """A replay of a task event published before contacts joined the payload.

        The ``history-projection`` group reads the stream from id ``0``, so it can
        be handed a ``TaskCreated`` from before Phase 5 added ``contact_ids``.
        Skipping the key beats raising: a raising handler dead-letters the batch
        and stalls history for every event queued behind it.
        """
        payload = _task_created_payload()
        del payload["contact_ids"]

        rows = service.project_event(_task_event("TaskCreated", payload))

        assert [r.field_name for r in rows] == ["__created__"]

    def test_status_and_the_two_anchors_are_not_projected(
        self, service: HistoryService
    ) -> None:
        """The create marker opens the history; it does not itemise the task.

        A later status move and a later retarget each publish a self-describing
        ``(old, new)`` pair, so neither needs an opening value to read correctly.
        A contact *unlink* does — it publishes ``(id, None)`` — which is why
        contacts are the one part of the payload this handler fans out.
        """
        rows = service.project_event(
            _task_event("TaskCreated", _task_created_payload(contact_ids=[CONTACT_ID]))
        )

        assert "status" not in {r.field_name for r in rows}
        assert not [r for r in rows if "journal" in r.field_name]


class TestTaskUpdated:
    def test_text_and_status_each_land_one_row(self, service: HistoryService) -> None:
        """One ``PATCH`` may do both, which is one event and two rows."""
        event = _task_event(
            "TaskUpdated",
            {
                "task_id": TASK_ID,
                "user_id": "u1",
                # Lists, mirroring the JSON round-trip through Redis.
                "changed_fields": {
                    "text": [TASK_TEXT, "Book the other venue"],
                    "status": ["not_done", "done"],
                },
                "source": Provenance.MCP.value,
                "changed_by": "mcp",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("task", TASK_ID, "text", TASK_TEXT, "Book the other venue"),
            ("task", TASK_ID, "status", "not_done", "done"),
        ]
        for row in rows:
            assert row.source == Provenance.MCP
            assert row.changed_by == "mcp"
            assert row.created_at == OCCURRED_AT

    def test_a_contact_link_lands_one_row_naming_the_contact(
        self, service: HistoryService
    ) -> None:
        """Phase 5 made contact membership a field, so it arrives here.

        The handler needs no branch for it: ``_rows_from_changed_fields`` reads
        ``change[0]`` as the old value and never looks at the key, so a
        ``contact:{id}`` key projects like any other field.
        """
        event = _task_event(
            "TaskUpdated",
            {
                "task_id": TASK_ID,
                "user_id": "u1",
                "changed_fields": {f"contact:{CONTACT_ID}": [None, CONTACT_ID]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        assert [_row_tuple(r) for r in service.project_event(event)] == [
            ("task", TASK_ID, f"contact:{CONTACT_ID}", None, str(CONTACT_ID))
        ]

    def test_a_contact_unlink_lands_the_pair_the_other_way_round(
        self, service: HistoryService
    ) -> None:
        """Direction is positional and nothing else carries it.

        An unlink projected as ``(None, id)`` would read in the feed as the
        person being added, and no other key in the payload would contradict it.
        """
        event = _task_event(
            "TaskUpdated",
            {
                "task_id": TASK_ID,
                "user_id": "u1",
                "changed_fields": {f"contact:{CONTACT_ID}": [CONTACT_ID, None]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        assert [_row_tuple(r) for r in service.project_event(event)] == [
            ("task", TASK_ID, f"contact:{CONTACT_ID}", str(CONTACT_ID), None)
        ]

    def test_two_people_land_under_distinct_field_names(
        self, service: HistoryService
    ) -> None:
        event = _task_event(
            "TaskUpdated",
            {
                "task_id": TASK_ID,
                "user_id": "u1",
                "changed_fields": {
                    f"contact:{CONTACT_ID}": [None, CONTACT_ID],
                    f"contact:{OTHER_CONTACT_ID}": [None, OTHER_CONTACT_ID],
                },
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        rows = service.project_event(event)

        assert len({r.field_name for r in rows}) == 2

    def test_no_changed_fields_produces_no_rows(self, service: HistoryService) -> None:
        event = _task_event(
            "TaskUpdated",
            {
                "task_id": TASK_ID,
                "user_id": "u1",
                "changed_fields": {},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )

        assert service.project_event(event) == []


class TestTaskDeleted:
    def test_projects_a_deleted_marker(self, service: HistoryService) -> None:
        """The event is a marker, so the row is one too.

        ``TaskDeleted`` carries no text and no anchors — ``delete_task`` reads
        nothing before deleting — so there is no value to record either side.
        """
        event = _task_event(
            "TaskDeleted",
            {
                "task_id": TASK_ID,
                "user_id": "u1",
                "source": Provenance.MCP.value,
                "changed_by": "mcp",
            },
        )

        rows = service.project_event(event)

        assert [_row_tuple(r) for r in rows] == [
            ("task", TASK_ID, "__deleted__", None, None)
        ]
        assert rows[0].source == Provenance.MCP
        assert rows[0].created_at == OCCURRED_AT

    def test_the_row_is_keyed_off_the_payload_rather_than_the_task_row(
        self, service: HistoryService
    ) -> None:
        """Tasks are hard-deleted, so the row this projects can never be joined
        back to a ``tasks`` row. Everything the projection needs is in the event."""
        event = _task_event(
            "TaskDeleted",
            {"task_id": 999, "user_id": "u1", "source": Provenance.UI.value},
        )

        assert [r.entity_id for r in service.project_event(event)] == [999]


def _retarget_payload(**overrides: Any) -> dict[str, Any]:
    """A ``TaskDueJournalRetargeted`` payload as the event builds it.

    ``changed_fields`` values arrive as *lists* rather than tuples, because the
    projection reads them back after a JSON round trip through Redis.
    """
    payload: dict[str, Any] = {
        "task_id": TASK_ID,
        "user_id": "u1",
        "changed_fields": {"due_journal_id": [OLD_JOURNAL_ID, NEW_JOURNAL_ID]},
        "source": Provenance.UI.value,
        "changed_by": "ui",
    }
    payload.update(overrides)
    return payload


class TestTaskDueJournalRetargeted:
    """The anchor move, projected by the handler ``TaskUpdated`` already uses.

    The retarget's payload is deliberately ``changed_fields``-shaped, so
    ``_rows_from_changed_fields`` produces the right rows with no handler of its
    own. Its retained intermediate link is not in the payload either — that is a
    ``TaskJournalLinked`` in its own right — so there is nothing left for a
    second handler to do.
    """

    def test_an_ordinary_deferral_projects_the_pair_the_right_way_round(
        self, service: HistoryService
    ) -> None:
        rows = service.project_event(
            _task_event("TaskDueJournalRetargeted", _retarget_payload())
        )

        assert [_row_tuple(r) for r in rows] == [
            (
                "task",
                TASK_ID,
                "due_journal_id",
                str(OLD_JOURNAL_ID),
                str(NEW_JOURNAL_ID),
            )
        ]

    def test_the_row_carries_the_actor_and_the_time_the_move_happened(
        self, service: HistoryService
    ) -> None:
        rows = service.project_event(
            _task_event(
                "TaskDueJournalRetargeted",
                _retarget_payload(source=Provenance.MCP.value, changed_by="mcp"),
            )
        )

        assert rows[0].source == Provenance.MCP
        assert rows[0].changed_by == "mcp"
        assert rows[0].event_id == "evt-1"
        assert rows[0].created_at == OCCURRED_AT

    def test_a_reopening_retarget_projects_the_status_move_as_well(
        self, service: HistoryService
    ) -> None:
        """The event adds the status pair only when the task actually reopened.

        A deferral of a *done* task lands it not done, which is a change the
        specification singles out as rarely what the user meant — so it reaches
        their history as its own line rather than being folded into the move.
        """
        rows = service.project_event(
            _task_event(
                "TaskDueJournalRetargeted",
                _retarget_payload(
                    changed_fields={
                        "due_journal_id": [OLD_JOURNAL_ID, NEW_JOURNAL_ID],
                        "status": ["done", "not_done"],
                    }
                ),
            )
        )

        assert [_row_tuple(r) for r in rows] == [
            (
                "task",
                TASK_ID,
                "due_journal_id",
                str(OLD_JOURNAL_ID),
                str(NEW_JOURNAL_ID),
            ),
            ("task", TASK_ID, "status", "done", "not_done"),
        ]

    def test_an_ordinary_deferral_writes_no_status_line(
        self, service: HistoryService
    ) -> None:
        """The other half of the reopen rule, asserted rather than implied.

        Every retarget lands the task not done, so a handler that read the status
        off the task rather than off ``changed_fields`` would write
        "not done → not done" into the history of every ordinary deferral.
        """
        rows = service.project_event(
            _task_event("TaskDueJournalRetargeted", _retarget_payload())
        )

        assert "status" not in {r.field_name for r in rows}

    def test_a_payload_carrying_no_changed_fields_projects_nothing(
        self, service: HistoryService
    ) -> None:
        """Silence beats raising: a raising handler dead-letters the whole batch
        and stalls history for every event queued behind it."""
        payload = _retarget_payload()
        del payload["changed_fields"]

        assert (
            service.project_event(_task_event("TaskDueJournalRetargeted", payload))
            == []
        )


class TestTaskJournalLinked:
    def test_projects_one_row_naming_the_journal_gained(
        self, service: HistoryService
    ) -> None:
        """``old=None, new=<the thing linked>`` — the ``JournalTagAssigned`` shape
        the event's own docstring names as its model."""
        rows = service.project_event(
            _task_event(
                "TaskJournalLinked",
                {
                    "task_id": TASK_ID,
                    "user_id": "u1",
                    "journal_id": OLD_JOURNAL_ID,
                    "origin": "manual",
                    "source": Provenance.UI.value,
                    "changed_by": "ui",
                },
            )
        )

        assert [_row_tuple(r) for r in rows] == [
            (
                "task",
                TASK_ID,
                f"journal:{OLD_JOURNAL_ID}",
                None,
                str(OLD_JOURNAL_ID),
            )
        ]
        assert rows[0].source == Provenance.UI
        assert rows[0].changed_by == "ui"
        assert rows[0].created_at == OCCURRED_AT

    def test_two_journals_land_under_distinct_field_names(
        self, service: HistoryService
    ) -> None:
        """Why the key names the journal instead of a shared ``journals`` field.

        Rows dedup on ``(event_id, entity_type, entity_id, field_name)``. These
        two arrive on different events today, so they would survive a shared name
        — but the pair a *retarget* publishes does not, and neither would a future
        write linking two journals in one unit of work. The key is what keeps a
        task's second journal out of the same slot as its first.
        """
        rows = [
            service.project_event(
                _task_event(
                    "TaskJournalLinked",
                    {
                        "task_id": TASK_ID,
                        "user_id": "u1",
                        "journal_id": journal_id,
                        "origin": "manual",
                        "source": Provenance.UI.value,
                    },
                    event_id=f"evt-{journal_id}",
                )
            )[0]
            for journal_id in (OLD_JOURNAL_ID, NEW_JOURNAL_ID)
        ]

        assert len({r.field_name for r in rows}) == 2

    def test_origin_stays_out_of_the_field_name(self, service: HistoryService) -> None:
        """A manual link and a retarget-derived one project the *same* key.

        ``origin`` says why the link exists, and ``field_history`` has no column
        for it — so the only place it could go is the field name, and it must not:
        a link and the unlink that later removes it have to share a name to read
        as a pair. ``journal:retarget:{id}`` followed by ``journal:{id}`` would
        show the user a removal with no addition before it, which is the exact
        asymmetry the create marker fans ``contact_ids`` out to prevent.
        """
        field_names = {
            service.project_event(
                _task_event(
                    "TaskJournalLinked",
                    {
                        "task_id": TASK_ID,
                        "user_id": "u1",
                        "journal_id": OLD_JOURNAL_ID,
                        "origin": origin,
                        "source": Provenance.UI.value,
                    },
                )
            )[0].field_name
            for origin in ("manual", "retarget")
        }

        assert field_names == {f"journal:{OLD_JOURNAL_ID}"}

    def test_a_payload_naming_no_journal_projects_nothing(
        self, service: HistoryService
    ) -> None:
        """The row would read as "linked journal None", and raising would stall
        every event queued behind it — the ``_journal_tag_rows`` precedent."""
        assert (
            service.project_event(
                _task_event(
                    "TaskJournalLinked",
                    {"task_id": TASK_ID, "user_id": "u1", "origin": "manual"},
                )
            )
            == []
        )


class TestTaskJournalUnlinked:
    def test_projects_the_pair_the_other_way_round(
        self, service: HistoryService
    ) -> None:
        """Direction is positional and nothing else on the row carries it.

        An unlink projected as ``(None, id)`` would read in the feed as the
        journal being added, and no other value would contradict it.
        """
        rows = service.project_event(
            _task_event(
                "TaskJournalUnlinked",
                {
                    "task_id": TASK_ID,
                    "user_id": "u1",
                    "journal_id": OLD_JOURNAL_ID,
                    "source": Provenance.MCP.value,
                    "changed_by": "mcp",
                },
            )
        )

        assert [_row_tuple(r) for r in rows] == [
            (
                "task",
                TASK_ID,
                f"journal:{OLD_JOURNAL_ID}",
                str(OLD_JOURNAL_ID),
                None,
            )
        ]
        assert rows[0].source == Provenance.MCP
        assert rows[0].created_at == OCCURRED_AT

    def test_it_shares_a_field_name_with_the_link_it_removes(
        self, service: HistoryService
    ) -> None:
        """The pair has to read together, which is only true if the keys match."""
        payload = {"task_id": TASK_ID, "user_id": "u1", "journal_id": OLD_JOURNAL_ID}

        linked = service.project_event(
            _task_event("TaskJournalLinked", {**payload, "origin": "manual"})
        )
        unlinked = service.project_event(_task_event("TaskJournalUnlinked", payload))

        assert linked[0].field_name == unlinked[0].field_name

    def test_a_payload_naming_no_journal_projects_nothing(
        self, service: HistoryService
    ) -> None:
        assert (
            service.project_event(
                _task_event(
                    "TaskJournalUnlinked", {"task_id": TASK_ID, "user_id": "u1"}
                )
            )
            == []
        )


class TestEveryTaskEventTypeIsProjected:
    """Nothing this domain publishes may be written and then never read.

    The set is not closed — a journal merge re-points a task's anchors and will
    publish an event of its own — so the invariant has to be one that *fails*
    when the next type lands, rather than a list somebody remembers to extend.
    """

    def test_every_task_event_class_has_a_handler(self) -> None:
        assert task_event_types() <= set(_HANDLERS)

    def test_every_task_handler_belongs_to_a_real_event_class(self) -> None:
        """The reverse direction: a handler keyed on a type nobody publishes maps
        an event that can never arrive, and reads as coverage that is not there."""
        task_keys = {key for key in _HANDLERS if key.startswith("Task")}

        assert task_keys == task_event_types()

    def test_each_event_type_string_is_its_class_name(self) -> None:
        """What makes the enumeration above legitimate.

        ``event_type`` is a constructor argument rather than a class attribute, so
        the inventory reads class names and this is the test that says it may.
        """
        for name, event_type in task_event_types_by_class().items():
            assert event_type == name


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

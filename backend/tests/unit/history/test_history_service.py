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

"""Unit tests for the shared HistoryConverter (ITER12-002 Phase 2)."""

from datetime import UTC, datetime

import pytest
from core_shared.models.history import Provenance

from app.api.history import HistoryConverter
from app.core.history.models import FieldHistoryEntry


def _entry(**overrides: object) -> FieldHistoryEntry:
    defaults: dict[str, object] = {
        "entity_type": "journal",
        "entity_id": 7,
        "field_name": "title",
        "old_value": "Old",
        "new_value": "New",
        "changed_by": "ui",
        "source": Provenance.UI,
        "id": 99,
        "created_at": datetime(2024, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return FieldHistoryEntry(**defaults)  # type: ignore[arg-type]


class TestHistoryConverter:
    def test_to_resource_defaults_to_journal_history_type(self) -> None:
        resource = HistoryConverter.to_resource(_entry())
        assert resource.type == "journal_history"
        assert resource.id == "99"
        assert resource.attributes.entity_type == "journal"
        assert resource.attributes.field_name == "title"
        assert resource.attributes.old_value == "Old"
        assert resource.attributes.new_value == "New"
        assert resource.attributes.source == "ui"
        assert resource.attributes.changed_by == "ui"

    def test_resource_type_is_parameterisable(self) -> None:
        resource = HistoryConverter.to_resource(
            _entry(), resource_type="contact_history"
        )
        assert resource.type == "contact_history"

    def test_created_at_iso_string_is_parsed(self) -> None:
        resource = HistoryConverter.to_resource(
            _entry(created_at="2024-03-04T05:06:07+00:00")
        )
        assert resource.attributes.created_at == datetime(
            2024, 3, 4, 5, 6, 7, tzinfo=UTC
        )

    def test_invalid_created_at_string_becomes_none(self) -> None:
        resource = HistoryConverter.to_resource(_entry(created_at="not-a-date"))
        assert resource.attributes.created_at is None

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValueError, match="without ID"):
            HistoryConverter.to_resource(_entry(id=None))

    def test_none_values_pass_through(self) -> None:
        resource = HistoryConverter.to_resource(
            _entry(old_value=None, new_value=None, changed_by=None)
        )
        assert resource.attributes.old_value is None
        assert resource.attributes.new_value is None
        assert resource.attributes.changed_by is None

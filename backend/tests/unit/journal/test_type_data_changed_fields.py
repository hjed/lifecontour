"""Unit tests for type-specific data change diffing (ITER12-002 Phase 2).

``JournalWriteService.update_type_data`` snapshots a type-data row before and
after the update and diffs the tracked fields into ``{field: (old, new)}`` pairs,
which are published on a ``JournalUpdated`` event and projected into journal
history. The pure diff/serialisation helpers are unit-tested here against two
type-specific data tables (MoodData, FitnessData), plus value coercion for the
non-scalar EVENT calendar fields.
"""

from datetime import time
from uuid import UUID

from core_shared.models.journals import FitnessData, MoodData

from app.core.journal.services.journal_write_service import (
    diff_tracked_fields,
    to_history_value,
)


class TestToHistoryValue:
    def test_none_passes_through(self) -> None:
        assert to_history_value(None) is None

    def test_scalars_pass_through(self) -> None:
        assert to_history_value("x") == "x"
        assert to_history_value(7) == 7
        assert to_history_value(True) is True

    def test_time_is_isoformatted(self) -> None:
        assert to_history_value(time(9, 30)) == "09:30:00"

    def test_uuid_is_stringified(self) -> None:
        u = UUID("12345678-1234-5678-1234-567812345678")
        assert to_history_value(u) == str(u)

    def test_enum_uses_value(self) -> None:
        from core_shared.models.journals.event_state import EventState

        assert to_history_value(EventState.CONFIRMED) == EventState.CONFIRMED.value


class TestDiffTrackedFieldsMood:
    fields = ("mood_value", "mood_label", "energy_level")

    def test_no_change_returns_empty(self) -> None:
        before = MoodData(journal_id=1, mood_value=5, mood_label="ok", energy_level=3)
        after = MoodData(journal_id=1, mood_value=5, mood_label="ok", energy_level=3)
        assert diff_tracked_fields(before, after, self.fields) == {}

    def test_single_field_change_is_a_pair(self) -> None:
        before = MoodData(journal_id=1, mood_value=5)
        after = MoodData(journal_id=1, mood_value=8)
        changed = diff_tracked_fields(before, after, self.fields)
        assert changed == {"mood_value": (5, 8)}

    def test_multiple_field_changes(self) -> None:
        before = MoodData(journal_id=1, mood_value=5, mood_label="ok")
        after = MoodData(journal_id=1, mood_value=8, mood_label="great")
        changed = diff_tracked_fields(before, after, self.fields)
        assert changed["mood_value"] == (5, 8)
        assert changed["mood_label"] == ("ok", "great")

    def test_setting_from_none(self) -> None:
        before = MoodData(journal_id=1)
        after = MoodData(journal_id=1, energy_level=4)
        assert diff_tracked_fields(before, after, self.fields) == {
            "energy_level": (None, 4)
        }


class TestDiffTrackedFieldsFitness:
    fields = ("distance", "duration", "calories")

    def test_distance_change(self) -> None:
        before = FitnessData(journal_id=1, distance=1000)
        after = FitnessData(journal_id=1, distance=2000)
        assert diff_tracked_fields(before, after, self.fields) == {
            "distance": (1000, 2000)
        }

    def test_no_change_returns_empty(self) -> None:
        before = FitnessData(journal_id=1, distance=1000, calories=50)
        after = FitnessData(journal_id=1, distance=1000, calories=50)
        assert diff_tracked_fields(before, after, self.fields) == {}


class TestDiffTrackedFieldsMissingRow:
    fields = ("mood_value",)

    def test_before_none_treats_all_as_new(self) -> None:
        after = MoodData(journal_id=1, mood_value=3)
        assert diff_tracked_fields(None, after, self.fields) == {
            "mood_value": (None, 3)
        }

    def test_both_none_returns_empty(self) -> None:
        assert diff_tracked_fields(None, None, self.fields) == {}

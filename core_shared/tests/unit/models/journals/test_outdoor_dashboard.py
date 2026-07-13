"""Unit tests for the outdoor dashboard read models.

Pins the effective-journal-type reduction used by the activity-totals widget:
a journal's types are detected purely by subtype-row presence, so
dependency-implied rows (e.g. the bushwalking row on a canyoning journal) must
not count as their own journal type, while genuinely independent subtypes each
count once.
"""

import pytest

from core_shared.models.journals import (
    JournalType,
    OutdoorActivitySubtype,
    effective_outdoor_journal_types,
)


class TestEffectiveOutdoorJournalTypes:
    def test_dependency_rows_reduce_to_composite_type(self) -> None:
        subtypes = [
            OutdoorActivitySubtype.CANYONING,
            OutdoorActivitySubtype.BUSHWALKING,
            OutdoorActivitySubtype.ABSEILING_TRIP,
        ]

        assert effective_outdoor_journal_types(subtypes) == [JournalType.CANYONING]

    @pytest.mark.parametrize(
        ("composite", "implied"),
        [
            (OutdoorActivitySubtype.CLIMBING, OutdoorActivitySubtype.ABSEILING_TRIP),
            (
                OutdoorActivitySubtype.CROSS_COUNTRY_SKIING,
                OutdoorActivitySubtype.BUSHWALKING,
            ),
            (OutdoorActivitySubtype.CAVING, OutdoorActivitySubtype.ABSEILING_TRIP),
        ],
    )
    def test_implied_dependency_never_counts_alongside_composite(
        self, composite: OutdoorActivitySubtype, implied: OutdoorActivitySubtype
    ) -> None:
        result = effective_outdoor_journal_types([implied, composite])

        assert result == [JournalType(composite.value)]

    def test_independent_subtypes_each_count(self) -> None:
        subtypes = [OutdoorActivitySubtype.KAYAKING, OutdoorActivitySubtype.DIVING]

        assert effective_outdoor_journal_types(subtypes) == [
            JournalType.DIVING,
            JournalType.KAYAKING,
        ]

    def test_no_subtypes_falls_back_to_outdoor_activity(self) -> None:
        assert effective_outdoor_journal_types([]) == [JournalType.OUTDOOR_ACTIVITY]

    def test_outdoor_training_is_a_leaf_type(self) -> None:
        subtypes = [OutdoorActivitySubtype.OUTDOOR_TRAINING]

        assert effective_outdoor_journal_types(subtypes) == [
            JournalType.OUTDOOR_TRAINING
        ]

"""Unit tests for the outdoor dashboard read models.

Pins the effective-journal-type reduction used by the activity-totals widget:
a journal's types are detected purely by subtype-row presence, so
dependency-implied rows (e.g. the bushwalking row on a canyoning journal) must
not count as their own journal type, while genuinely independent subtypes each
count once.

Also pins the checked-out-gear determination (resolved checkout ≤ now <
resolved check-in, and not already checked in on the SnipeIT side) and the
templates-done aggregation (per-template done-counts grouped by template
type) used by the gear and templates-done widgets.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core_shared.models.journals import (
    CheckedOutGearItem,
    EventDateRange,
    GearCheckoutFacts,
    JournalType,
    OutdoorActivitySubtype,
    TemplateDone,
    TemplateReferenceFacts,
    checked_out_gear,
    count_unique_templates_in_window,
    effective_outdoor_journal_types,
    is_currently_checked_out,
    templates_done_by_type,
)

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)

# A representative 30-day window for the pure overlap logic. The real service
# anchors a calendar-day window (midnight → end-of-day) in the user's timezone;
# this simplified rolling window is enough to exercise count_unique_templates_in_window.
RECENT_WINDOW = EventDateRange(start=NOW - timedelta(days=30), end=NOW)


def make_checkout_facts(
    *,
    journal_id: int = 1,
    gear_item_id: str = "11111111-1111-1111-1111-111111111111",
    gear_name: str = "Rope",
    checkout_date: datetime | None = None,
    checkin_date: datetime | None = None,
    snipeit_checked_in: bool = False,
) -> GearCheckoutFacts:
    return GearCheckoutFacts(
        journal_id=journal_id,
        gear_item_id=gear_item_id,
        gear_name=gear_name,
        checkout_date=checkout_date or NOW - timedelta(days=1),
        checkin_date=checkin_date or NOW + timedelta(days=1),
        snipeit_checked_in=snipeit_checked_in,
    )


def make_reference(
    *,
    journal_id: int = 1,
    template_id: str = "22222222-2222-2222-2222-222222222222",
    template_name: str = "Empress Falls",
    template_type: str = "canyoning",
    event_date_range: EventDateRange | None = None,
) -> TemplateReferenceFacts:
    return TemplateReferenceFacts(
        journal_id=journal_id,
        template_id=template_id,
        template_name=template_name,
        template_type=template_type,
        event_date_range=event_date_range
        or EventDateRange(start=NOW - timedelta(days=1), end=NOW - timedelta(days=1)),
    )


def on_day(days_ago: float) -> EventDateRange:
    """A point-in-time event range ``days_ago`` before :data:`NOW`."""
    moment = NOW - timedelta(days=days_ago)
    return EventDateRange(start=moment, end=moment)


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


class TestIsCurrentlyCheckedOut:
    def test_inside_window_is_checked_out(self) -> None:
        facts = make_checkout_facts(
            checkout_date=NOW - timedelta(days=2),
            checkin_date=NOW + timedelta(days=2),
        )

        assert is_currently_checked_out(facts, NOW) is True

    def test_checkout_boundary_is_inclusive(self) -> None:
        facts = make_checkout_facts(
            checkout_date=NOW, checkin_date=NOW + timedelta(days=1)
        )

        assert is_currently_checked_out(facts, NOW) is True

    def test_checkin_boundary_is_exclusive(self) -> None:
        facts = make_checkout_facts(
            checkout_date=NOW - timedelta(days=1), checkin_date=NOW
        )

        assert is_currently_checked_out(facts, NOW) is False

    def test_future_checkout_is_not_yet_checked_out(self) -> None:
        facts = make_checkout_facts(
            checkout_date=NOW + timedelta(days=1),
            checkin_date=NOW + timedelta(days=2),
        )

        assert is_currently_checked_out(facts, NOW) is False

    def test_ended_window_is_no_longer_checked_out(self) -> None:
        facts = make_checkout_facts(
            checkout_date=NOW - timedelta(days=2),
            checkin_date=NOW - timedelta(days=1),
        )

        assert is_currently_checked_out(facts, NOW) is False

    def test_snipeit_checkin_overrides_an_open_window(self) -> None:
        facts = make_checkout_facts(snipeit_checked_in=True)

        assert is_currently_checked_out(facts, NOW) is False


class TestCheckedOutGear:
    def test_filters_out_inactive_checkouts(self) -> None:
        active = make_checkout_facts(journal_id=1)
        ended = make_checkout_facts(
            journal_id=2,
            gear_item_id="33333333-3333-3333-3333-333333333333",
            checkout_date=NOW - timedelta(days=3),
            checkin_date=NOW - timedelta(days=2),
        )
        returned = make_checkout_facts(
            journal_id=3,
            gear_item_id="44444444-4444-4444-4444-444444444444",
            snipeit_checked_in=True,
        )

        result = checked_out_gear([active, ended, returned], NOW)

        assert [item.journal_id for item in result] == [1]

    def test_dedupes_gear_item_keeping_earliest_active_checkout(self) -> None:
        earlier = make_checkout_facts(
            journal_id=1, checkout_date=NOW - timedelta(days=5)
        )
        later = make_checkout_facts(journal_id=2, checkout_date=NOW - timedelta(days=1))

        result = checked_out_gear([later, earlier], NOW)

        assert len(result) == 1
        assert result[0].journal_id == 1
        assert result[0].checked_out_since == NOW - timedelta(days=5)

    def test_orders_longest_out_first(self) -> None:
        recent = make_checkout_facts(
            journal_id=1,
            gear_item_id="33333333-3333-3333-3333-333333333333",
            gear_name="Harness",
            checkout_date=NOW - timedelta(days=1),
        )
        oldest = make_checkout_facts(
            journal_id=2, checkout_date=NOW - timedelta(days=9)
        )

        result = checked_out_gear([recent, oldest], NOW)

        assert [item.journal_id for item in result] == [2, 1]

    def test_maps_facts_to_checked_out_items(self) -> None:
        facts = make_checkout_facts(checkout_date=NOW - timedelta(days=1))

        result = checked_out_gear([facts], NOW)

        assert result == [
            CheckedOutGearItem(
                gear_item_id=facts.gear_item_id,
                name="Rope",
                checked_out_since=NOW - timedelta(days=1),
                journal_id=facts.journal_id,
            )
        ]

    def test_empty_facts_yield_empty_list(self) -> None:
        assert checked_out_gear([], NOW) == []


class TestTemplatesDoneByType:
    def test_counts_repeat_references_per_template(self) -> None:
        result = templates_done_by_type(
            [make_reference(journal_id=1), make_reference(journal_id=2)]
        )

        assert result == {
            "canyoning": [
                TemplateDone(
                    template_id="22222222-2222-2222-2222-222222222222",
                    name="Empress Falls",
                    template_type="canyoning",
                    done_count=2,
                )
            ]
        }

    def test_groups_templates_under_their_type(self) -> None:
        canyon = make_reference(journal_id=1)
        climb = make_reference(
            journal_id=2,
            template_id="55555555-5555-5555-5555-555555555555",
            template_name="Sweet Dreams",
            template_type="climbing",
        )

        result = templates_done_by_type([canyon, climb])

        assert set(result) == {"canyoning", "climbing"}
        assert [entry.name for entry in result["canyoning"]] == ["Empress Falls"]
        assert [entry.name for entry in result["climbing"]] == ["Sweet Dreams"]

    def test_orders_templates_by_name_within_a_type(self) -> None:
        zig = make_reference(
            journal_id=1,
            template_id="55555555-5555-5555-5555-555555555555",
            template_name="Zig Zag",
        )
        arethusa = make_reference(
            journal_id=2,
            template_id="66666666-6666-6666-6666-666666666666",
            template_name="Arethusa",
        )

        result = templates_done_by_type([zig, arethusa])

        assert [entry.name for entry in result["canyoning"]] == [
            "Arethusa",
            "Zig Zag",
        ]

    def test_empty_references_yield_empty_mapping(self) -> None:
        assert templates_done_by_type([]) == {}


class TestCountUniqueTemplatesInWindow:
    def test_counts_each_template_once_however_often_it_was_done(self) -> None:
        references = [
            make_reference(journal_id=1, event_date_range=on_day(2)),
            make_reference(journal_id=2, event_date_range=on_day(5)),
        ]

        assert count_unique_templates_in_window(references, RECENT_WINDOW) == 1

    def test_counts_distinct_templates_separately(self) -> None:
        canyon = make_reference(journal_id=1, event_date_range=on_day(2))
        climb = make_reference(
            journal_id=2,
            template_id="55555555-5555-5555-5555-555555555555",
            template_name="Sweet Dreams",
            template_type="climbing",
            event_date_range=on_day(3),
        )

        assert count_unique_templates_in_window([canyon, climb], RECENT_WINDOW) == 2

    def test_excludes_templates_done_outside_the_window(self) -> None:
        recent = make_reference(journal_id=1, event_date_range=on_day(2))
        stale = make_reference(
            journal_id=2,
            template_id="55555555-5555-5555-5555-555555555555",
            template_name="Claustral",
            event_date_range=on_day(90),
        )

        assert count_unique_templates_in_window([recent, stale], RECENT_WINDOW) == 1

    def test_counts_a_trip_straddling_the_window_boundary(self) -> None:
        # A multi-day trip starting before the window but ending inside it
        # overlaps, matching the activity-totals bucketing rule.
        straddling = make_reference(
            journal_id=1,
            event_date_range=EventDateRange(
                start=NOW - timedelta(days=32), end=NOW - timedelta(days=29)
            ),
        )

        assert count_unique_templates_in_window([straddling], RECENT_WINDOW) == 1

    def test_excludes_a_trip_ending_before_the_window_opens(self) -> None:
        before = make_reference(journal_id=1, event_date_range=on_day(31))

        assert count_unique_templates_in_window([before], RECENT_WINDOW) == 0

    def test_empty_references_count_zero(self) -> None:
        assert count_unique_templates_in_window([], RECENT_WINDOW) == 0

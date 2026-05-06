"""Unit tests for logbook calculators."""

import datetime
from unittest import TestCase

from core_shared.models.journals import (
    AbseilPitch,
    EventDateRange,
    LogbookEntryContact,
    LogbookEntryData,
    LogbookSummaryCalculator,
    OutdoorActivityData,
    ParticipantIndexCalculator,
)


class TestLogbookSummaryCalculator(TestCase):
    def test_calculate_empty(self) -> None:
        calculator = LogbookSummaryCalculator()
        result = calculator.calculate([])
        self.assertEqual(result, [])

    def test_calculate_basic(self) -> None:
        calculator = LogbookSummaryCalculator()
        entries = [
            LogbookEntryData(
                id=1,
                title="Trip 1",
                content="",
                event_date_range=EventDateRange(
                    start=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
                    end=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
                ),
                parent_id=None,
                journal_types=["OUTDOOR_ACTIVITY", "BUSHWALKING"],
                outdoor_activity_data=OutdoorActivityData(
                    journal_id=1,
                    in_leadership_role=True,
                ),
            ),
            LogbookEntryData(
                id=2,
                title="Trip 2",
                content="",
                event_date_range=EventDateRange(
                    start=datetime.datetime(2023, 2, 1, tzinfo=datetime.UTC),
                    end=datetime.datetime(2023, 2, 1, tzinfo=datetime.UTC),
                ),
                parent_id=None,
                journal_types=["OUTDOOR_ACTIVITY", "CANYONING", "ABSEILING_TRIP"],
                outdoor_activity_data=OutdoorActivityData(
                    journal_id=2,
                    in_leadership_role=False,
                ),
                abseil_pitches=[
                    AbseilPitch(
                        journal_id=2, pitch_number=1, height=10, did_setup=True
                    ),
                    AbseilPitch(
                        journal_id=2, pitch_number=2, height=20, did_setup=False
                    ),
                ],
            ),
        ]

        result = calculator.calculate(entries)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].year, 2023)

        self.assertEqual(result[0].total_activities_by_type["BUSHWALKING"], 1)
        self.assertEqual(result[0].total_activities_by_type["CANYONING"], 1)

        self.assertEqual(result[0].leadership_activities_by_type["BUSHWALKING"], 1)
        self.assertNotIn("CANYONING", result[0].leadership_activities_by_type)

        self.assertEqual(result[0].total_abseils, 2)
        self.assertEqual(result[0].total_abseiling_metres, 30)
        self.assertEqual(result[0].total_setups, 1)

    def test_calculate_with_children(self) -> None:
        calculator = LogbookSummaryCalculator()
        entries = [
            LogbookEntryData(
                id=1,
                title="Multi-day Trip",
                content="",
                event_date_range=EventDateRange(
                    start=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
                    end=datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC),
                ),
                parent_id=None,
                journal_types=[],
                children=[
                    LogbookEntryData(
                        id=2,
                        title="Day 1",
                        content="",
                        event_date_range=EventDateRange(
                            start=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
                            end=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
                        ),
                        parent_id=1,
                        journal_types=["OUTDOOR_ACTIVITY", "CLIMBING"],
                        outdoor_activity_data=OutdoorActivityData(
                            journal_id=2,
                            in_leadership_role=True,
                        ),
                    )
                ],
            )
        ]

        result = calculator.calculate(entries)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].year, 2024)
        self.assertEqual(result[0].total_activities_by_type["CLIMBING"], 1)
        self.assertEqual(result[0].leadership_activities_by_type["CLIMBING"], 1)


class TestParticipantIndexCalculator(TestCase):
    def test_calculate_basic(self) -> None:
        calculator = ParticipantIndexCalculator()
        entries = [
            LogbookEntryData(
                id=1,
                title="Trip 1",
                content="",
                event_date_range=EventDateRange(
                    start=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
                    end=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
                ),
                parent_id=None,
                contacts=[
                    LogbookEntryContact(
                        contact_id=101, name="Alice", role="PARTICIPANT"
                    ),
                    LogbookEntryContact(contact_id=102, name="Bob", role="PARTICIPANT"),
                ],
            ),
            LogbookEntryData(
                id=2,
                title="Trip 2",
                content="",
                event_date_range=EventDateRange(
                    start=datetime.datetime(2023, 2, 1, tzinfo=datetime.UTC),
                    end=datetime.datetime(2023, 2, 1, tzinfo=datetime.UTC),
                ),
                parent_id=None,
                contacts=[
                    LogbookEntryContact(
                        contact_id=101, name="Alice", role="PARTICIPANT"
                    ),
                ],
            ),
        ]

        # By default, min_appearances is 3. Alice has 2, Bob has 1. Both should be omitted.
        result = calculator.calculate(entries)
        self.assertEqual(len(result), 0)

        # Lower min_appearances to 0
        result_all = calculator.calculate(entries, min_appearances=0)
        self.assertEqual(len(result_all), 2)

        alice = next(r for r in result_all if r.name == "Alice")
        bob = next(r for r in result_all if r.name == "Bob")

        self.assertEqual(alice.appearances, 2)
        self.assertEqual(bob.appearances, 1)

    def test_calculate_with_children_counts_once_per_root(self) -> None:
        calculator = ParticipantIndexCalculator()
        entries = [
            LogbookEntryData(
                id=1,
                title="Trip 1",
                content="",
                event_date_range=EventDateRange(
                    start=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
                    end=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
                ),
                parent_id=None,
                contacts=[
                    LogbookEntryContact(
                        contact_id=101, name="Alice", role="PARTICIPANT"
                    ),
                ],
                children=[
                    LogbookEntryData(
                        id=2,
                        title="Trip 1 - Day 1",
                        content="",
                        event_date_range=EventDateRange(
                            start=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
                            end=datetime.datetime(2023, 1, 1, tzinfo=datetime.UTC),
                        ),
                        parent_id=1,
                        contacts=[
                            LogbookEntryContact(
                                contact_id=101, name="Alice", role="PARTICIPANT"
                            ),
                        ],
                    )
                ],
            )
        ]

        result = calculator.calculate(entries, min_appearances=0)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0].appearances, 1
        )  # Only 1 appearance despite being in parent and child

"""Unit tests for important-date occurrence resolution.

Pins the rule that turns a stored contact important date into the occurrence
falling inside a window of days: which precisions produce an occurrence at all,
which date types participate, where the window's two inclusive ends lie, how
29 February is observed in a year that does not have one, and when the derived
count of years is a real answer rather than an absent one.

Every case supplies both ends of the window explicitly. The rule takes dates
rather than instants and never reads a clock, so none of these tests depends on
the day it is run.
"""

from __future__ import annotations

import datetime

import pytest

from core_shared.models.contacts.entities import ImportantDate
from core_shared.models.contacts.important_date_occurrence import (
    ImportantDateOccurrence,
    resolve_occurrence,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)

#: Every built-in type, plus custom — the five that open decision 4 was about.
ALL_DATE_TYPES = [
    ImportantDateType.BIRTHDAY,
    ImportantDateType.MARRIAGE_ANNIVERSARY,
    ImportantDateType.WORK_ANNIVERSARY,
    ImportantDateType.FIRST_MET,
    ImportantDateType.CUSTOM,
]


def important_date(
    *,
    date_type: ImportantDateType = ImportantDateType.BIRTHDAY,
    precision: DatePrecision = DatePrecision.DAY_MONTH,
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
) -> ImportantDate:
    """Build a stored important date, supplying whatever the type requires."""
    return ImportantDate(
        contact_id=1,
        date_type=date_type,
        precision=precision,
        year=year,
        month=month,
        day=day,
        custom_date_type_id=7 if date_type is ImportantDateType.CUSTOM else None,
    )


def on(year: int, month: int, day: int) -> datetime.date:
    """A calendar date, spelled out so a window reads as three numbers."""
    return datetime.date(year, month, day)


@pytest.mark.unit
class TestPrecision:
    """Which precisions produce an occurrence, and what each derives."""

    def test_a_full_date_occurs_and_counts_its_years(self) -> None:
        """Full precision places the occurrence and knows how long ago it was."""
        occurrence = resolve_occurrence(
            important_date(precision=DatePrecision.FULL, year=1990, month=3, day=3),
            first_day=on(2026, 3, 1),
            last_day=on(2026, 3, 8),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 3, 3)
        assert occurrence.years == 36

    def test_a_day_month_date_occurs_but_counts_nothing(self) -> None:
        """Day-and-month precision still recurs; it has no year to count from."""
        occurrence = resolve_occurrence(
            important_date(precision=DatePrecision.DAY_MONTH, month=3, day=3),
            first_day=on(2026, 3, 1),
            last_day=on(2026, 3, 8),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 3, 3)
        assert occurrence.years is None

    def test_a_year_only_date_never_occurs(self) -> None:
        """Year precision has no month or day, so there is nowhere to place it."""
        assert (
            resolve_occurrence(
                important_date(precision=DatePrecision.YEAR, year=2015),
                first_day=on(2026, 1, 1),
                last_day=on(2026, 12, 31),
            )
            is None
        )

    def test_precision_outranks_leftover_components(self) -> None:
        """The precision decides, not whatever month and day a row is carrying.

        ``ImportantDate`` clears the month and day of a year-only row when it is
        constructed, but it is a mutable dataclass, so a row reassigned
        afterwards keeps them. Answering from those leftovers would resurrect a
        date the user said they only knew the year of.
        """
        stored = important_date(precision=DatePrecision.DAY_MONTH, month=3, day=3)
        stored.precision = DatePrecision.YEAR
        stored.year = 2015

        assert (
            resolve_occurrence(
                stored, first_day=on(2026, 3, 1), last_day=on(2026, 3, 8)
            )
            is None
        )

    def test_the_occurrence_carries_the_date_it_resolved(self) -> None:
        """The answer carries its question, so a caller need not pair them up."""
        stored = important_date(precision=DatePrecision.FULL, year=1990, month=3, day=3)

        occurrence = resolve_occurrence(
            stored, first_day=on(2026, 3, 1), last_day=on(2026, 3, 8)
        )

        assert occurrence is not None
        assert occurrence.important_date is stored

    def test_an_occurrence_is_frozen(self) -> None:
        """The result is a computed value, not something a caller edits."""
        occurrence = resolve_occurrence(
            important_date(month=3, day=3),
            first_day=on(2026, 3, 1),
            last_day=on(2026, 3, 8),
        )

        assert isinstance(occurrence, ImportantDateOccurrence)
        with pytest.raises(AttributeError):
            occurrence.days_away = 99  # type: ignore[misc]


@pytest.mark.unit
class TestEveryDateTypeParticipates:
    """Open decision 4: precision decides participation, never the type."""

    @pytest.mark.parametrize("date_type", ALL_DATE_TYPES)
    def test_every_type_resolves_from_a_day_month_date(
        self, date_type: ImportantDateType
    ) -> None:
        """No type is filtered out of the window."""
        occurrence = resolve_occurrence(
            important_date(
                date_type=date_type,
                precision=DatePrecision.DAY_MONTH,
                month=3,
                day=3,
            ),
            first_day=on(2026, 3, 1),
            last_day=on(2026, 3, 8),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 3, 3)

    @pytest.mark.parametrize("date_type", ALL_DATE_TYPES)
    def test_every_type_resolves_identically_from_a_full_date(
        self, date_type: ImportantDateType
    ) -> None:
        """The years derivation is the precision's, not the type's."""
        occurrence = resolve_occurrence(
            important_date(
                date_type=date_type,
                precision=DatePrecision.FULL,
                year=2000,
                month=3,
                day=3,
            ),
            first_day=on(2026, 3, 1),
            last_day=on(2026, 3, 8),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 3, 3)
        assert occurrence.years == 26

    @pytest.mark.parametrize("date_type", ALL_DATE_TYPES)
    def test_no_type_rescues_a_year_only_date(
        self, date_type: ImportantDateType
    ) -> None:
        """A year-only date produces nothing whatever type it carries."""
        assert (
            resolve_occurrence(
                important_date(
                    date_type=date_type,
                    precision=DatePrecision.YEAR,
                    year=2015,
                ),
                first_day=on(2026, 1, 1),
                last_day=on(2026, 12, 31),
            )
            is None
        )


@pytest.mark.unit
class TestTheWindowBoundary:
    """Both ends are inclusive, and the window may span more than one year."""

    def test_an_occurrence_on_the_first_day_is_in_the_window(self) -> None:
        """Today counts: a date occurring today is exactly what a dashboard shows."""
        occurrence = resolve_occurrence(
            important_date(month=3, day=3),
            first_day=on(2026, 3, 3),
            last_day=on(2026, 3, 10),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 3, 3)
        assert occurrence.days_away == 0

    def test_an_occurrence_on_the_last_day_is_in_the_window(self) -> None:
        """The far end is included too, and days_away counts to it."""
        occurrence = resolve_occurrence(
            important_date(month=3, day=3),
            first_day=on(2026, 2, 24),
            last_day=on(2026, 3, 3),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 3, 3)
        assert occurrence.days_away == 7

    def test_the_day_before_the_window_is_out(self) -> None:
        """A date that has just passed does not resolve backwards into view."""
        assert (
            resolve_occurrence(
                important_date(month=3, day=3),
                first_day=on(2026, 3, 4),
                last_day=on(2026, 3, 11),
            )
            is None
        )

    def test_the_day_after_the_window_is_out(self) -> None:
        """A date one day beyond the far end is not yet coming up."""
        assert (
            resolve_occurrence(
                important_date(month=3, day=3),
                first_day=on(2026, 2, 24),
                last_day=on(2026, 3, 2),
            )
            is None
        )

    def test_a_window_crossing_the_year_boundary_finds_january(self) -> None:
        """A January date resolves in a window that began the previous December."""
        occurrence = resolve_occurrence(
            important_date(month=1, day=2),
            first_day=on(2026, 12, 28),
            last_day=on(2027, 1, 4),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2027, 1, 2)
        assert occurrence.days_away == 5

    def test_a_window_crossing_the_year_boundary_still_finds_december(self) -> None:
        """The year the window opened in is a candidate as much as the one it closes in."""
        occurrence = resolve_occurrence(
            important_date(month=12, day=30),
            first_day=on(2026, 12, 28),
            last_day=on(2027, 1, 4),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 12, 30)
        assert occurrence.days_away == 2

    def test_a_full_date_across_the_year_boundary_counts_from_its_occurrence(
        self,
    ) -> None:
        """The years count follows the occurrence's year, not the window's start."""
        occurrence = resolve_occurrence(
            important_date(precision=DatePrecision.FULL, year=1990, month=1, day=2),
            first_day=on(2026, 12, 28),
            last_day=on(2027, 1, 4),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2027, 1, 2)
        assert occurrence.years == 37

    def test_a_multi_year_window_returns_the_earliest_occurrence(self) -> None:
        """A window holding two occurrences resolves to the first of them."""
        occurrence = resolve_occurrence(
            important_date(month=3, day=3),
            first_day=on(2026, 1, 1),
            last_day=on(2028, 12, 31),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 3, 3)

    def test_a_single_day_window_is_legitimate(self) -> None:
        """First and last day may be the same day — that window is today alone."""
        occurrence = resolve_occurrence(
            important_date(month=3, day=3),
            first_day=on(2026, 3, 3),
            last_day=on(2026, 3, 3),
        )

        assert occurrence is not None
        assert occurrence.days_away == 0

    def test_a_reversed_window_is_a_caller_error(self) -> None:
        """A window whose end precedes its start is a bug, not an empty answer.

        The date is built outside the block on purpose: ``__post_init__`` raises
        ``ValueError`` too, so constructing it in there would leave two sources
        of the exception the test claims to be about.
        """
        stored = important_date(month=3, day=3)

        with pytest.raises(ValueError, match="last_day"):
            resolve_occurrence(
                stored, first_day=on(2026, 3, 10), last_day=on(2026, 3, 3)
            )


@pytest.mark.unit
class TestTheLeapDay:
    """29 February recurs every year, including the three that do not have one."""

    def test_a_leap_year_places_it_on_the_twenty_ninth(self) -> None:
        """Where the day exists, it is used, and nothing is observed."""
        occurrence = resolve_occurrence(
            important_date(month=2, day=29),
            first_day=on(2028, 2, 25),
            last_day=on(2028, 3, 5),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2028, 2, 29)
        assert occurrence.observed_for_leap_day is False

    def test_a_non_leap_year_observes_it_on_the_twenty_eighth(self) -> None:
        """The date stays in February rather than moving into March or vanishing."""
        occurrence = resolve_occurrence(
            important_date(month=2, day=29),
            first_day=on(2027, 2, 25),
            last_day=on(2027, 3, 5),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2027, 2, 28)
        assert occurrence.observed_for_leap_day is True

    def test_the_observed_day_is_not_used_when_the_real_one_exists(self) -> None:
        """A leap-year window ending on the 28th does not catch the 29th early."""
        assert (
            resolve_occurrence(
                important_date(month=2, day=29),
                first_day=on(2028, 2, 20),
                last_day=on(2028, 2, 28),
            )
            is None
        )

    def test_an_observed_leap_day_still_counts_its_years(self) -> None:
        """Observing the day changes where it lands, not how long ago it was."""
        occurrence = resolve_occurrence(
            important_date(precision=DatePrecision.FULL, year=2000, month=2, day=29),
            first_day=on(2027, 2, 25),
            last_day=on(2027, 3, 5),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2027, 2, 28)
        assert occurrence.observed_for_leap_day is True
        assert occurrence.years == 27

    def test_an_ordinary_date_is_never_marked_observed(self) -> None:
        """The flag means one thing, so it must be false everywhere else."""
        occurrence = resolve_occurrence(
            important_date(month=2, day=28),
            first_day=on(2027, 2, 25),
            last_day=on(2027, 3, 5),
        )

        assert occurrence is not None
        assert occurrence.observed_for_leap_day is False


@pytest.mark.unit
class TestTheDerivedYears:
    """When the count of years is a real answer, and when there is none."""

    def test_a_same_day_occurrence_counts_the_full_years(self) -> None:
        """A birthday today is the age reached today, zero days away."""
        occurrence = resolve_occurrence(
            important_date(precision=DatePrecision.FULL, year=1990, month=9, day=5),
            first_day=on(2026, 9, 5),
            last_day=on(2026, 9, 12),
        )

        assert occurrence is not None
        assert occurrence.days_away == 0
        assert occurrence.years == 36

    def test_a_date_recorded_this_year_counts_zero(self) -> None:
        """Zero is a real count — the year the date itself happened."""
        occurrence = resolve_occurrence(
            important_date(precision=DatePrecision.FULL, year=2026, month=11, day=20),
            first_day=on(2026, 11, 18),
            last_day=on(2026, 11, 25),
        )

        assert occurrence is not None
        assert occurrence.years == 0

    def test_a_date_stored_in_the_future_keeps_its_occurrence(self) -> None:
        """The recurrence is real even when the stored year is ahead of it."""
        occurrence = resolve_occurrence(
            important_date(precision=DatePrecision.FULL, year=2027, month=3, day=10),
            first_day=on(2026, 3, 8),
            last_day=on(2026, 3, 15),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 3, 10)

    def test_a_date_stored_in_the_future_counts_nothing(self) -> None:
        """A negative age is not an age, so there is no count rather than a wrong one."""
        occurrence = resolve_occurrence(
            important_date(precision=DatePrecision.FULL, year=2027, month=3, day=10),
            first_day=on(2026, 3, 8),
            last_day=on(2026, 3, 15),
        )

        assert occurrence is not None
        assert occurrence.years is None


@pytest.mark.unit
class TestAnImpossibleCalendarYear:
    """The year is range-checked nowhere, so a stored one may not be a year.

    ``__post_init__``, the API schema and the column constraints all range-check
    the month and the day and none of them checks the year, so ``year=0`` is as
    storable as ``year=1990``. Subtracting it would report a birthday as "turns
    2026", which is worse than saying nothing.
    """

    @pytest.mark.parametrize("stored_year", [0, -1, -500, 10_000, 99_999])
    def test_a_year_outside_the_calendar_counts_nothing(self, stored_year: int) -> None:
        """No count at all, rather than a nonsensical one."""
        occurrence = resolve_occurrence(
            important_date(
                precision=DatePrecision.FULL, year=stored_year, month=3, day=3
            ),
            first_day=on(2026, 3, 1),
            last_day=on(2026, 3, 8),
        )

        assert occurrence is not None
        assert occurrence.years is None

    @pytest.mark.parametrize("stored_year", [0, -500, 99_999])
    def test_a_year_outside_the_calendar_keeps_its_occurrence(
        self, stored_year: int
    ) -> None:
        """The month and day are still real, so the date still comes round."""
        occurrence = resolve_occurrence(
            important_date(
                precision=DatePrecision.FULL, year=stored_year, month=3, day=3
            ),
            first_day=on(2026, 3, 1),
            last_day=on(2026, 3, 8),
        )

        assert occurrence is not None
        assert occurrence.occurs_on == on(2026, 3, 3)

    def test_the_first_calendar_year_is_a_real_year(self) -> None:
        """Year 1 is the boundary and is inside it, so it still counts."""
        occurrence = resolve_occurrence(
            important_date(
                precision=DatePrecision.FULL,
                year=datetime.MINYEAR,
                month=3,
                day=3,
            ),
            first_day=on(2026, 3, 1),
            last_day=on(2026, 3, 8),
        )

        assert occurrence is not None
        assert occurrence.years == 2025

    def test_the_last_calendar_year_is_a_real_year_but_lies_ahead(self) -> None:
        """Year 9999 is inside the calendar, and falls under the future rule."""
        occurrence = resolve_occurrence(
            important_date(
                precision=DatePrecision.FULL,
                year=datetime.MAXYEAR,
                month=3,
                day=3,
            ),
            first_day=on(2026, 3, 1),
            last_day=on(2026, 3, 8),
        )

        assert occurrence is not None
        assert occurrence.years is None


@pytest.mark.unit
class TestAnImpossibleCalendarDay:
    """Day is range-checked 1–31 with no month cross-check, so these rows exist."""

    @pytest.mark.parametrize(
        ("month", "day"),
        [(2, 30), (2, 31), (4, 31), (6, 31), (9, 31), (11, 31)],
    )
    def test_a_day_that_no_year_has_never_occurs(self, month: int, day: int) -> None:
        """A stored date that is not a date resolves to nothing, and does not raise."""
        assert (
            resolve_occurrence(
                important_date(month=month, day=day),
                first_day=on(2026, 1, 1),
                last_day=on(2028, 12, 31),
            )
            is None
        )

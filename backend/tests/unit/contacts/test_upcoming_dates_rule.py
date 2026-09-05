"""Unit tests for the upcoming-dates rule: which rows to ask for, and in what order.

The dashboard's upcoming-dates section shows "important contact dates falling in
the next seven days ... ordered by date ascending then by contact importance
descending". Two pure claims live in that sentence and both are asserted here
rather than through a service or a query:

- **which stored rows could possibly land in the window**, which is what the
  query is allowed to filter on; and
- **what order the survivors come back in**, including how a same-day tie is
  broken.

**The leap day is why the candidate rule is not just "the days in the window".**
A row stored as 29 February is *observed* on 28 February in a year that has no
29th (ITER18-004 Phase 9), so its occurrence date and its stored month/day are
not the same pair. A query filtering on the literal pairs the window spells
would drop every leap-day birthday in three years out of four — silently, and
for the three quarters of users whose section would simply be missing a row.

**Precision, impossible data and the derived years are not re-tested here.**
``resolve_occurrence`` owns them and has 56 tests of its own; duplicating them
at this layer would buy nothing and cost twice on every future change.
"""

from __future__ import annotations

import datetime

import pytest
from core_shared.models.contacts.entities import ImportantDate
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.date_window import DEFAULT_UPCOMING_DAYS_AHEAD, upcoming_window

from app.core.contacts.models.importance import ContactImportance
from app.core.contacts.models.upcoming_dates import (
    ContactImportantDate,
    UpcomingDateContact,
    select_upcoming_dates,
    upcoming_dates_window,
    window_month_days,
)

pytestmark = pytest.mark.unit

TODAY = datetime.date(2026, 8, 11)


def contact(contact_id: int, name: str = "Ada Lovelace") -> UpcomingDateContact:
    """A contact as a dashboard row shows one."""
    return UpcomingDateContact(id=contact_id, display_name=name, photo_url=None)


def candidate(
    date_id: int,
    *,
    contact_id: int,
    month: int,
    day: int,
    year: int | None = None,
    precision: DatePrecision = DatePrecision.DAY_MONTH,
    date_type: ImportantDateType = ImportantDateType.BIRTHDAY,
    name: str = "Ada Lovelace",
) -> ContactImportantDate:
    """A row as the candidate query returns one: a stored date and its contact."""
    return ContactImportantDate(
        important_date=ImportantDate(
            id=date_id,
            contact_id=contact_id,
            date_type=date_type,
            precision=precision,
            year=year,
            month=month,
            day=day,
        ),
        contact=contact(contact_id, name),
    )


def importance(
    contact_id: int,
    *,
    favourite: bool = False,
    journals: int = 0,
    activity: int = 0,
) -> ContactImportance:
    """One contact's signals, as Phase 10's shared read returns them."""
    return ContactImportance(
        contact_id=contact_id,
        is_favourite=favourite,
        journal_count_30d=journals,
        activity_count_30d=activity,
        last_activity_at=None,
    )


class TestTheCandidatePairs:
    """Which stored ``(month, day)`` pairs could land in the window."""

    def test_a_week_yields_its_eight_days(self) -> None:
        pairs = window_month_days(upcoming_window(TODAY, 7))

        assert pairs == (
            (8, 11),
            (8, 12),
            (8, 13),
            (8, 14),
            (8, 15),
            (8, 16),
            (8, 17),
            (8, 18),
        )

    def test_a_window_of_zero_days_yields_one_pair(self) -> None:
        assert window_month_days(upcoming_window(TODAY, 0)) == ((8, 11),)

    def test_it_crosses_a_month_boundary(self) -> None:
        pairs = window_month_days(upcoming_window(datetime.date(2026, 8, 30), 3))

        assert pairs == ((8, 30), (8, 31), (9, 1), (9, 2))

    def test_it_crosses_a_year_boundary(self) -> None:
        """The stored pairs carry no year, so December and January sit side by side."""
        pairs = window_month_days(upcoming_window(datetime.date(2026, 12, 30), 3))

        assert pairs == ((12, 30), (12, 31), (1, 1), (1, 2))

    def test_a_window_covering_28_february_in_a_common_year_asks_for_the_29th(
        self,
    ) -> None:
        """2027 has no 29 February, so a leap-day row is observed on the 28th.

        Without this the row is never fetched, and a leap-day birthday is
        missing from the section in three years out of four.
        """
        pairs = window_month_days(upcoming_window(datetime.date(2027, 2, 26), 3))

        assert pairs == ((2, 26), (2, 27), (2, 28), (2, 29), (3, 1))

    def test_a_window_covering_a_real_29_february_asks_for_it_once(self) -> None:
        """2028 is a leap year: the 29th is already one of the window's own days."""
        pairs = window_month_days(upcoming_window(datetime.date(2028, 2, 27), 3))

        assert pairs == ((2, 27), (2, 28), (2, 29), (3, 1))
        assert pairs.count((2, 29)) == 1

    def test_a_window_stopping_before_28_february_does_not_ask_for_the_29th(
        self,
    ) -> None:
        pairs = window_month_days(upcoming_window(datetime.date(2027, 2, 24), 3))

        assert (2, 29) not in pairs

    def test_a_window_longer_than_a_month_repeats_no_pair(self) -> None:
        pairs = window_month_days(upcoming_window(TODAY, 90))

        assert len(pairs) == len(set(pairs))


class TestWhatTheRuleSelects:
    """The window is filtered a second time here, deliberately."""

    def test_an_in_window_date_comes_back_with_its_occurrence_resolved(self) -> None:
        window = upcoming_window(TODAY, 7)

        selected = select_upcoming_dates(
            [candidate(1, contact_id=10, month=8, day=14)],
            window,
            {10: importance(10)},
        )

        assert len(selected.dates) == 1
        occurrence = selected.dates[0].occurrence
        assert occurrence.occurs_on == datetime.date(2026, 8, 14)
        assert occurrence.days_away == 3

    def test_a_date_outside_the_window_is_dropped(self) -> None:
        """The query filters this already; asserting it here makes the boundary
        provable without a database, and a query that over-fetches still fails
        its own tests rather than being papered over."""
        selected = select_upcoming_dates(
            [candidate(1, contact_id=10, month=9, day=14)],
            upcoming_window(TODAY, 7),
            {10: importance(10)},
        )

        assert selected.dates == ()

    def test_a_year_precision_row_produces_nothing(self) -> None:
        """No month or day to place it on — the rule ``resolve_occurrence`` owns."""
        selected = select_upcoming_dates(
            [
                ContactImportantDate(
                    important_date=ImportantDate(
                        id=1,
                        contact_id=10,
                        date_type=ImportantDateType.FIRST_MET,
                        precision=DatePrecision.YEAR,
                        year=2019,
                    ),
                    contact=contact(10),
                )
            ],
            upcoming_window(TODAY, 7),
            {10: importance(10)},
        )

        assert selected.dates == ()

    def test_a_leap_day_row_survives_into_a_common_year(self) -> None:
        """The candidate pairs ask for it; the rule must not then drop it."""
        selected = select_upcoming_dates(
            [candidate(1, contact_id=10, month=2, day=29)],
            upcoming_window(datetime.date(2027, 2, 26), 3),
            {10: importance(10)},
        )

        assert len(selected.dates) == 1
        assert selected.dates[0].occurrence.occurs_on == datetime.date(2027, 2, 28)
        assert selected.dates[0].occurrence.observed_for_leap_day

    def test_the_contact_travels_with_the_date(self) -> None:
        selected = select_upcoming_dates(
            [candidate(1, contact_id=10, month=8, day=14, name="Grace Hopper")],
            upcoming_window(TODAY, 7),
            {10: importance(10)},
        )

        assert selected.dates[0].contact.display_name == "Grace Hopper"


class TestTheOrder:
    """Date ascending, then contact importance descending, in one pass."""

    def test_the_soonest_date_comes_first(self) -> None:
        selected = select_upcoming_dates(
            [
                candidate(1, contact_id=10, month=8, day=16),
                candidate(2, contact_id=11, month=8, day=12),
                candidate(3, contact_id=12, month=8, day=14),
            ],
            upcoming_window(TODAY, 7),
            {cid: importance(cid) for cid in (10, 11, 12)},
        )

        assert [date.occurrence.occurs_on.day for date in selected.dates] == [
            12,
            14,
            16,
        ]

    def test_a_more_important_contact_never_outranks_a_sooner_date(self) -> None:
        """Importance breaks ties within a day; it does not reorder the days."""
        selected = select_upcoming_dates(
            [
                candidate(1, contact_id=10, month=8, day=16),
                candidate(2, contact_id=11, month=8, day=12),
            ],
            upcoming_window(TODAY, 7),
            {10: importance(10, favourite=True, journals=99), 11: importance(11)},
        )

        assert [date.contact.id for date in selected.dates] == [11, 10]

    def test_a_same_day_tie_puts_the_favourite_first(self) -> None:
        selected = select_upcoming_dates(
            [
                candidate(1, contact_id=10, month=8, day=14),
                candidate(2, contact_id=11, month=8, day=14),
            ],
            upcoming_window(TODAY, 7),
            {
                10: importance(10, journals=50, activity=50),
                11: importance(11, favourite=True),
            },
        )

        assert [date.contact.id for date in selected.dates] == [11, 10]

    def test_a_same_day_tie_between_equals_falls_to_the_journal_count(self) -> None:
        selected = select_upcoming_dates(
            [
                candidate(1, contact_id=10, month=8, day=14),
                candidate(2, contact_id=11, month=8, day=14),
            ],
            upcoming_window(TODAY, 7),
            {
                10: importance(10, favourite=True, journals=1, activity=99),
                11: importance(11, favourite=True, journals=4),
            },
        )

        assert [date.contact.id for date in selected.dates] == [11, 10]

    def test_a_same_day_tie_between_equals_falls_last_to_the_activity_count(
        self,
    ) -> None:
        selected = select_upcoming_dates(
            [
                candidate(1, contact_id=10, month=8, day=14),
                candidate(2, contact_id=11, month=8, day=14),
            ],
            upcoming_window(TODAY, 7),
            {
                10: importance(10, favourite=True, journals=4, activity=2),
                11: importance(11, favourite=True, journals=4, activity=7),
            },
        )

        assert [date.contact.id for date in selected.dates] == [11, 10]

    def test_two_contacts_with_nothing_to_separate_them_still_have_one_order(
        self,
    ) -> None:
        """Without a final tie-break the same request could answer twice in two
        orders, which is a bug a user sees as the list shuffling itself."""
        candidates = [
            candidate(2, contact_id=11, month=8, day=14),
            candidate(1, contact_id=10, month=8, day=14),
        ]
        signals = {10: importance(10), 11: importance(11)}
        window = upcoming_window(TODAY, 7)

        first = select_upcoming_dates(candidates, window, signals)
        second = select_upcoming_dates(list(reversed(candidates)), window, signals)

        assert [date.contact.id for date in first.dates] == [10, 11]
        assert first.dates == second.dates

    def test_one_contact_with_two_dates_on_a_day_is_ordered_by_the_date_row(
        self,
    ) -> None:
        """The contact tie-break cannot separate these, so the row id must."""
        selected = select_upcoming_dates(
            [
                candidate(
                    7,
                    contact_id=10,
                    month=8,
                    day=14,
                    date_type=ImportantDateType.WORK_ANNIVERSARY,
                ),
                candidate(3, contact_id=10, month=8, day=14),
            ],
            upcoming_window(TODAY, 7),
            {10: importance(10)},
        )

        assert [date.occurrence.important_date.id for date in selected.dates] == [3, 7]

    def test_a_contact_with_no_signals_ranks_last_but_still_appears(self) -> None:
        """A contact deleted between the two reads must not blank the section.

        Contact 10 is absent from the signals entirely, and would sort *first*
        on the id tie-break if it were treated as equal — so 11 is given a real
        signal, which is what makes the assertion about the missing entry.
        """
        selected = select_upcoming_dates(
            [
                candidate(1, contact_id=10, month=8, day=14),
                candidate(2, contact_id=11, month=8, day=14),
            ],
            upcoming_window(TODAY, 7),
            {11: importance(11, journals=3)},
        )

        assert [date.contact.id for date in selected.dates] == [11, 10]
        assert selected.dates[1].importance.contact_id == 10
        assert not selected.dates[1].importance.is_favourite


class TestTheAnswerCarriesItsWindow:
    """An empty answer has no rows to derive the window from, so it carries one."""

    def test_an_empty_window_still_reports_the_window_it_asked_about(self) -> None:
        window = upcoming_window(TODAY, 7)

        selected = select_upcoming_dates([], window, {})

        assert selected.dates == ()
        assert selected.window == window
        assert selected.total == 0

    def test_the_whole_window_travels_and_nothing_is_capped(self) -> None:
        """The card caps at three (ITER18-004 open decision 3) from this payload,
        so a show-more costs no second request. Capping here would make one."""
        selected = select_upcoming_dates(
            [
                candidate(index, contact_id=index, month=8, day=11 + index % 8)
                for index in range(12)
            ],
            upcoming_window(TODAY, 7),
            {index: importance(index) for index in range(12)},
        )

        assert selected.total == 12
        assert len(selected.dates) == selected.total


class TestTheWindowBound:
    """The contacts domain's translation of the shared bound."""

    def test_it_defaults_to_the_shared_seven_days(self) -> None:
        assert upcoming_dates_window(TODAY) == upcoming_window(
            TODAY, DEFAULT_UPCOMING_DAYS_AHEAD
        )

    def test_it_builds_the_same_window_the_tasks_section_uses(self) -> None:
        assert upcoming_dates_window(TODAY, 7) == upcoming_window(TODAY, 7)

    def test_a_negative_window_is_a_contacts_validation_error(self) -> None:
        """Not a ``DateWindowError``: this reaches a contacts surface as a 422."""
        with pytest.raises(ContactValidationError) as excinfo:
            upcoming_dates_window(TODAY, -1)

        assert excinfo.value.field == "days_ahead"

    def test_a_window_past_the_maximum_is_a_contacts_validation_error(self) -> None:
        with pytest.raises(ContactValidationError) as excinfo:
            upcoming_dates_window(TODAY, 91)

        assert "90" in str(excinfo.value)

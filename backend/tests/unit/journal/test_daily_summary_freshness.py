"""Unit tests for the daily summary freshness rule.

Today's summary must reflect today: a row generated yesterday evening is stale
by the morning and must not be served (Home Dashboard specification,
*Extending the Daily Summary → Freshness*). Any other day is never stale — a
past day's summary describes that day however long ago it was written.

"Today" and "generated today" are both read in the user's timezone, so the
boundary tests lean on the same fixed instant the eligibility tests use: 14:30
UTC on 3 September, which is already 00:30 on the 4th in Sydney and still
07:30 on the 3rd in Los Angeles.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary

from app.core.journal.services.daily_summary_freshness import (
    DailySummaryFreshnessChecker,
    was_generated_on,
)

_NOW = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
_SEVEN_AM_UTC = datetime(2026, 9, 3, 7, 0, tzinfo=UTC)
_UTC_TODAY = date(2026, 9, 3)
_UTC_YESTERDAY = date(2026, 9, 2)
_UTC_TOMORROW = date(2026, 9, 4)


def summary(summary_date: date, generated_at: datetime | None) -> JournalDailySummary:
    return JournalDailySummary(
        user_id="user123",
        summary_date=summary_date,
        summary_text="Whatever was written.",
        status=SummaryStatus.GENERATED,
        generated_at=generated_at,
    )


@pytest.fixture
def checker() -> DailySummaryFreshnessChecker:
    return DailySummaryFreshnessChecker(clock=lambda: _NOW)


class TestTodaysSummaryMustBeGeneratedToday:
    """The specification's own two examples, at 07:00 the next morning."""

    def test_generated_at_22_00_yesterday_is_stale_at_07_00_today(self) -> None:
        checker = DailySummaryFreshnessChecker(clock=lambda: _SEVEN_AM_UTC)
        row = summary(_UTC_TODAY, datetime(2026, 9, 2, 22, 0, tzinfo=UTC))

        assert checker.is_stale(row, timezone="UTC") is True

    def test_generated_at_00_30_today_is_not_stale_at_07_00_today(self) -> None:
        checker = DailySummaryFreshnessChecker(clock=lambda: _SEVEN_AM_UTC)
        row = summary(_UTC_TODAY, datetime(2026, 9, 3, 0, 30, tzinfo=UTC))

        assert checker.is_stale(row, timezone="UTC") is False

    def test_generated_moments_ago_is_not_stale(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        row = summary(_UTC_TODAY, datetime(2026, 9, 3, 14, 29, tzinfo=UTC))

        assert checker.is_stale(row, timezone="UTC") is False

    def test_a_today_row_that_never_recorded_when_is_stale(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        """No ``generated_at`` cannot prove it was generated today."""
        assert checker.is_stale(summary(_UTC_TODAY, None), timezone="UTC") is True


class TestOtherDaysAreNeverStale:
    """The rule singles out today; a past or future day keeps its summary."""

    def test_a_past_day_generated_that_evening_is_not_stale(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        row = summary(_UTC_YESTERDAY, datetime(2026, 9, 2, 22, 0, tzinfo=UTC))

        assert checker.is_stale(row, timezone="UTC") is False

    def test_a_past_day_generated_weeks_later_is_not_stale(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        row = summary(date(2026, 8, 1), datetime(2026, 8, 30, 9, 0, tzinfo=UTC))

        assert checker.is_stale(row, timezone="UTC") is False

    def test_a_past_day_with_no_generated_at_is_not_stale(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        assert checker.is_stale(summary(_UTC_YESTERDAY, None), timezone="UTC") is False

    def test_a_future_day_is_not_stale(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        row = summary(_UTC_TOMORROW, datetime(2026, 9, 3, 10, 0, tzinfo=UTC))

        assert checker.is_stale(row, timezone="UTC") is False


class TestBothDaysAreReadInTheUsersTimezone:
    """The same instant is a different day in different zones."""

    # 23:00 on 3 September in Sydney (+10), 13:00 UTC the same day.
    _SYDNEY_LATE_EVENING = datetime(2026, 9, 3, 13, 0, tzinfo=UTC)
    # 00:10 on 4 September in Sydney, 14:10 UTC on the 3rd.
    _SYDNEY_JUST_PAST_MIDNIGHT = datetime(2026, 9, 3, 14, 10, tzinfo=UTC)
    # 22:00 on 2 September in Los Angeles (-7), 05:00 UTC on the 3rd.
    _LA_YESTERDAY_EVENING = datetime(2026, 9, 3, 5, 0, tzinfo=UTC)

    def test_sydney_at_00_30_finds_a_summary_from_23_00_stale(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        """Ninety minutes old, but written yesterday where the user lives."""
        row = summary(_UTC_TOMORROW, self._SYDNEY_LATE_EVENING)

        assert checker.is_stale(row, timezone="Australia/Sydney") is True

    def test_sydney_at_00_30_finds_a_summary_from_00_10_fresh(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        row = summary(_UTC_TOMORROW, self._SYDNEY_JUST_PAST_MIDNIGHT)

        assert checker.is_stale(row, timezone="Australia/Sydney") is False

    def test_sydney_does_not_judge_utcs_today_which_is_its_yesterday(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        """UTC's 3 September is a past day in Sydney, so no rule applies."""
        row = summary(_UTC_TODAY, self._SYDNEY_LATE_EVENING)

        assert checker.is_stale(row, timezone="Australia/Sydney") is False

    def test_los_angeles_finds_a_utc_today_instant_stale_when_it_was_its_yesterday(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        """05:00 UTC on the 3rd is still the evening of the 2nd in Los Angeles."""
        row = summary(_UTC_TODAY, self._LA_YESTERDAY_EVENING)

        assert checker.is_stale(row, timezone="America/Los_Angeles") is True

    def test_the_same_instant_is_fresh_for_a_utc_user(
        self, checker: DailySummaryFreshnessChecker
    ) -> None:
        row = summary(_UTC_TODAY, self._LA_YESTERDAY_EVENING)

        assert checker.is_stale(row, timezone="UTC") is False

    @pytest.mark.parametrize("timezone", [None, "", "Not/AZone"])
    def test_a_missing_or_unknown_timezone_falls_back_to_utc(
        self, checker: DailySummaryFreshnessChecker, timezone: str | None
    ) -> None:
        stale = summary(_UTC_TODAY, datetime(2026, 9, 2, 23, 59, tzinfo=UTC))
        fresh = summary(_UTC_TODAY, datetime(2026, 9, 3, 0, 1, tzinfo=UTC))

        assert checker.is_stale(stale, timezone=timezone) is True
        assert checker.is_stale(fresh, timezone=timezone) is False


class TestWasGeneratedOn:
    """The pure predicate the dashboard reuses, given the day it already holds."""

    def test_true_when_generated_at_falls_on_the_day_in_the_zone(self) -> None:
        row = summary(_UTC_TOMORROW, datetime(2026, 9, 3, 14, 10, tzinfo=UTC))

        assert was_generated_on(row, _UTC_TOMORROW, ZoneInfo("Australia/Sydney"))

    def test_false_when_it_falls_on_the_day_before_in_the_zone(self) -> None:
        row = summary(_UTC_TOMORROW, datetime(2026, 9, 3, 13, 0, tzinfo=UTC))

        assert not was_generated_on(row, _UTC_TOMORROW, ZoneInfo("Australia/Sydney"))

    def test_false_without_a_generated_at(self) -> None:
        assert not was_generated_on(
            summary(_UTC_TODAY, None), _UTC_TODAY, ZoneInfo("UTC")
        )

    def test_a_naive_generated_at_is_read_as_utc(self) -> None:
        """The storage convention ``to_user_tz`` documents: naive means UTC."""
        row = summary(_UTC_TOMORROW, datetime(2026, 9, 3, 14, 10))

        assert was_generated_on(row, _UTC_TOMORROW, ZoneInfo("Australia/Sydney"))
        assert not was_generated_on(row, _UTC_TODAY, ZoneInfo("Australia/Sydney"))

    def test_the_status_is_not_its_business(self) -> None:
        """Whether a row may be *served* is the caller's rule; this is only when."""
        row = summary(_UTC_TODAY, datetime(2026, 9, 3, 1, 0, tzinfo=UTC))
        row.status = SummaryStatus.PENDING

        assert was_generated_on(row, _UTC_TODAY, ZoneInfo("UTC"))

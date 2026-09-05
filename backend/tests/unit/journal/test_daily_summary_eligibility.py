"""Unit tests for DailySummaryEligibilityChecker.

The checker judges a day against a clock so the boundary between "today" and
"a past day" can be pinned either side of the user's local midnight rather than
UTC's. ``_NOW`` is 14:30 UTC, which is already tomorrow in Sydney and still the
morning in Los Angeles — the two zones every boundary test below leans on.
"""

from datetime import UTC, date, datetime

import pytest

from app.core.journal.services.daily_summary_eligibility import (
    DailySummaryEligibilityChecker,
)

_NOW = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
_UTC_TODAY = date(2026, 9, 3)
_UTC_YESTERDAY = date(2026, 9, 2)
_UTC_TOMORROW = date(2026, 9, 4)


@pytest.fixture
def checker() -> DailySummaryEligibilityChecker:
    return DailySummaryEligibilityChecker(clock=lambda: _NOW)


class TestTodayIsAlwaysEligible:
    """The current day qualifies regardless of how many journals it has."""

    def test_today_with_zero_journals_is_eligible(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert checker.is_eligible(0, summary_date=_UTC_TODAY, timezone="UTC") is True

    def test_today_with_one_journal_is_eligible(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert checker.is_eligible(1, summary_date=_UTC_TODAY, timezone="UTC") is True

    def test_today_ignores_a_custom_threshold(self) -> None:
        """A raised threshold governs other days, never today."""
        checker = DailySummaryEligibilityChecker(min_journals=5, clock=lambda: _NOW)
        assert checker.is_eligible(0, summary_date=_UTC_TODAY, timezone="UTC") is True


class TestPastDaysKeepTheThreshold:
    """A past day still needs two or more journals."""

    def test_past_day_with_one_journal_is_not_eligible(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert (
            checker.is_eligible(1, summary_date=_UTC_YESTERDAY, timezone="UTC") is False
        )

    def test_past_day_with_zero_journals_is_not_eligible(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert (
            checker.is_eligible(0, summary_date=_UTC_YESTERDAY, timezone="UTC") is False
        )

    def test_past_day_with_two_journals_is_eligible(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert (
            checker.is_eligible(2, summary_date=_UTC_YESTERDAY, timezone="UTC") is True
        )

    def test_past_day_with_many_journals_is_eligible(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert (
            checker.is_eligible(10, summary_date=_UTC_YESTERDAY, timezone="UTC") is True
        )

    def test_custom_threshold_governs_past_days(self) -> None:
        checker = DailySummaryEligibilityChecker(min_journals=3, clock=lambda: _NOW)
        assert (
            checker.is_eligible(2, summary_date=_UTC_YESTERDAY, timezone="UTC") is False
        )
        assert (
            checker.is_eligible(3, summary_date=_UTC_YESTERDAY, timezone="UTC") is True
        )

    def test_threshold_of_one_still_excludes_an_empty_past_day(self) -> None:
        checker = DailySummaryEligibilityChecker(min_journals=1, clock=lambda: _NOW)
        assert (
            checker.is_eligible(0, summary_date=_UTC_YESTERDAY, timezone="UTC") is False
        )
        assert (
            checker.is_eligible(1, summary_date=_UTC_YESTERDAY, timezone="UTC") is True
        )


class TestFutureDaysAreUnchanged:
    """A future date keeps the threshold; this rule only singles out today."""

    def test_future_day_with_one_journal_is_not_eligible(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert (
            checker.is_eligible(1, summary_date=_UTC_TOMORROW, timezone="UTC") is False
        )

    def test_future_day_with_two_journals_is_eligible(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert (
            checker.is_eligible(2, summary_date=_UTC_TOMORROW, timezone="UTC") is True
        )


class TestTodayIsResolvedInTheUsersTimezone:
    """ "Today" is the user's local date, never UTC's."""

    def test_sydney_after_local_midnight_treats_utc_tomorrow_as_today(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        """14:30 UTC is 00:30 the next day in Sydney (UTC+10)."""
        assert (
            checker.is_eligible(
                0, summary_date=_UTC_TOMORROW, timezone="Australia/Sydney"
            )
            is True
        )

    def test_sydney_after_local_midnight_treats_utc_today_as_past(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        """UTC's today is already yesterday in Sydney, so the threshold applies."""
        assert (
            checker.is_eligible(1, summary_date=_UTC_TODAY, timezone="Australia/Sydney")
            is False
        )

    def test_sydney_before_local_midnight_still_treats_utc_today_as_today(
        self,
    ) -> None:
        """One hour earlier, 13:30 UTC is 23:30 in Sydney: still 3 September.

        Paired with the two Sydney cases above, this straddles one zone's
        midnight rather than only comparing zones at one instant.
        """
        checker = DailySummaryEligibilityChecker(
            clock=lambda: datetime(2026, 9, 3, 13, 30, tzinfo=UTC)
        )
        assert (
            checker.is_eligible(0, summary_date=_UTC_TODAY, timezone="Australia/Sydney")
            is True
        )
        assert (
            checker.is_eligible(
                1, summary_date=_UTC_TOMORROW, timezone="Australia/Sydney"
            )
            is False
        )

    def test_los_angeles_before_local_midnight_treats_utc_today_as_today(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        """14:30 UTC is 07:30 the same day in Los Angeles (UTC-7)."""
        assert (
            checker.is_eligible(
                0, summary_date=_UTC_TODAY, timezone="America/Los_Angeles"
            )
            is True
        )

    def test_los_angeles_before_local_midnight_treats_utc_tomorrow_as_future(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert (
            checker.is_eligible(
                1, summary_date=_UTC_TOMORROW, timezone="America/Los_Angeles"
            )
            is False
        )

    def test_missing_timezone_falls_back_to_utc(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert checker.is_eligible(0, summary_date=_UTC_TODAY, timezone=None) is True
        assert (
            checker.is_eligible(0, summary_date=_UTC_TOMORROW, timezone=None) is False
        )

    def test_unknown_timezone_falls_back_to_utc(
        self, checker: DailySummaryEligibilityChecker
    ) -> None:
        assert (
            checker.is_eligible(0, summary_date=_UTC_TODAY, timezone="Not/AZone")
            is True
        )
        assert (
            checker.is_eligible(0, summary_date=_UTC_TOMORROW, timezone="Not/AZone")
            is False
        )


class TestDefaultClock:
    """Without an injected clock the checker reads the real time.

    Asserted against a day decades past rather than against a second reading
    of the real clock, which could straddle midnight and flip the answer.
    """

    def test_default_clock_treats_a_long_past_day_as_past(self) -> None:
        checker = DailySummaryEligibilityChecker()
        assert (
            checker.is_eligible(1, summary_date=date(2000, 1, 1), timezone="UTC")
            is False
        )


class TestAnImposedInstant:
    """A caller that has already read the clock can impose its reading.

    The checker keeps its own ``clock`` for callers that have none, but a
    request that resolved "now" earlier must be able to hand it over: judging
    eligibility against a second, later reading is how a day that was today
    when its journals were counted becomes a ``DISABLED`` past day.
    """

    def test_the_supplied_instant_wins_over_the_checkers_own_clock(self) -> None:
        checker = DailySummaryEligibilityChecker(
            clock=lambda: datetime(2026, 4, 28, 0, 0, 1, tzinfo=UTC)
        )

        # Its own clock says the 28th, so the 27th would be a past day with one
        # journal — ineligible. The imposed instant says the 27th is today.
        assert checker.is_eligible(
            1,
            summary_date=date(2026, 4, 27),
            timezone="UTC",
            now=datetime(2026, 4, 27, 23, 59, 59, tzinfo=UTC),
        )

    def test_without_one_it_still_reads_its_own_clock(self) -> None:
        checker = DailySummaryEligibilityChecker(
            clock=lambda: datetime(2026, 4, 28, 0, 0, 1, tzinfo=UTC)
        )

        assert not checker.is_eligible(
            1, summary_date=date(2026, 4, 27), timezone="UTC"
        )

    def test_the_imposed_instant_is_read_in_the_users_zone(self) -> None:
        """23:00 UTC on the 27th is already the 28th in Sydney."""
        checker = DailySummaryEligibilityChecker()
        moment = datetime(2026, 4, 27, 23, 0, tzinfo=UTC)

        assert checker.is_eligible(
            0,
            summary_date=date(2026, 4, 28),
            timezone="Australia/Sydney",
            now=moment,
        )
        assert not checker.is_eligible(
            0, summary_date=date(2026, 4, 28), timezone="UTC", now=moment
        )

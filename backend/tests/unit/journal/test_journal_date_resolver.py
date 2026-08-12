"""Unit tests for journal date resolution and the future-dated rule.

A journal's *date* is the local date of its ``event_date_range.start`` in the
acting user's *configured* timezone, and it is the date the tasks model's
future-dated invariant is judged against. (It is meant to be the date the
journal list groups it under too, but that list groups in the *browser's*
timezone — see the module under test for the recorded divergence.) Every case
here is a case where a UTC reading would give a different answer, because a rule
that only holds at midday is not a rule.

The instants are fixed rather than relative to ``now`` so the day boundaries and
the two Sydney daylight-saving transitions of 2026 are exercised deterministically:

- **2026-10-04** — clocks go forward (AEST +10 → AEDT +11), a 23-hour local day.
- **2026-04-05** — clocks go back (AEDT +11 → AEST +10), a 25-hour local day.
"""

import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.journals import EventDateRange, Journal

from app.core.journal.services.journal_date_resolver import (
    JournalDateResolver,
    is_future_dated,
    journal_date,
    local_date,
    local_day_window,
    local_window,
    today_in,
)

USER_ID = "test-user-123"

SYDNEY = ZoneInfo("Australia/Sydney")
NEW_YORK = ZoneInfo("America/New_York")
UTC_ZONE = ZoneInfo("UTC")
# Two zones whose clocks change **at midnight**, which is the case Sydney's
# 02:00/03:00 transitions cannot exercise: the last hour of the day repeats, so
# a window built from the local wall time ``23:59:59.999999`` closes an hour
# early and drops real journals.
SANTIAGO = ZoneInfo("America/Santiago")
BEIRUT = ZoneInfo("Asia/Beirut")


def utc(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
) -> datetime.datetime:
    """A UTC instant, the way the database hands journal timestamps back."""
    return datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.UTC)


def make_journal(
    start: datetime.datetime, end: datetime.datetime | None = None
) -> Journal:
    """A journal spanning ``start`` to ``end`` (default: an instantaneous range)."""
    return Journal(
        user_id=USER_ID,
        title="A journal",
        content="content",
        event_date_range=EventDateRange(start=start, end=end or start),
    )


@pytest.mark.unit
class TestJournalDate:
    """A journal's date is its start, read in the user's timezone."""

    def test_journal_date_is_the_local_date_of_the_start(self) -> None:
        """``journal_date`` is ``local_date`` applied to the range's start."""
        start = utc(2026, 7, 30, 14, 30)
        assert journal_date(make_journal(start), SYDNEY) == local_date(start, SYDNEY)

    def test_uses_the_start_of_the_range_not_the_end(self) -> None:
        """A four-day journal is dated by its first day, not its last."""
        journal = make_journal(utc(2026, 8, 1, 2), utc(2026, 8, 4, 2))

        assert journal_date(journal, UTC_ZONE) == datetime.date(2026, 8, 1)

    def test_resolves_either_side_of_the_users_local_midnight(self) -> None:
        """23:00 and 00:30 Sydney fall on different dates, both inside 30 July UTC."""
        before_midnight = make_journal(utc(2026, 7, 30, 13, 0))  # 23:00 AEST 30 Jul
        after_midnight = make_journal(utc(2026, 7, 30, 14, 30))  # 00:30 AEST 31 Jul

        assert journal_date(before_midnight, SYDNEY) == datetime.date(2026, 7, 30)
        assert journal_date(after_midnight, SYDNEY) == datetime.date(2026, 7, 31)

    def test_west_of_utc_resolves_to_the_previous_utc_date(self) -> None:
        """01:00 UTC is still the previous evening in New York."""
        journal = make_journal(utc(2026, 7, 30, 1, 0))  # 21:00 EDT 29 Jul

        assert journal_date(journal, NEW_YORK) == datetime.date(2026, 7, 29)

    def test_a_naive_start_is_treated_as_utc(self) -> None:
        """Naive timestamps are UTC, matching ``to_user_tz``'s documented convention."""
        naive = datetime.datetime(2026, 7, 30, 14, 30)  # noqa: DTZ001 — deliberate

        assert local_date(naive, SYDNEY) == datetime.date(2026, 7, 31)

    def test_resolves_across_a_spring_forward_transition(self) -> None:
        """After the 4 Oct jump to +11, 13:30 UTC is already the 5th in Sydney."""
        journal = make_journal(utc(2026, 10, 4, 13, 30))  # 00:30 AEDT 5 Oct

        assert journal_date(journal, SYDNEY) == datetime.date(2026, 10, 5)

    def test_resolves_across_a_fall_back_transition(self) -> None:
        """After the 5 Apr return to +10, 13:30 UTC is still the 5th in Sydney."""
        journal = make_journal(utc(2026, 4, 5, 13, 30))  # 23:30 AEST 5 Apr

        assert journal_date(journal, SYDNEY) == datetime.date(2026, 4, 5)


@pytest.mark.unit
class TestTodayIn:
    """ "Today" is the user's local date, never UTC's."""

    def test_today_is_the_local_date_not_the_utc_date(self) -> None:
        """00:30 Sydney on the 31st, while UTC is still on the 30th."""
        assert today_in(SYDNEY, now=utc(2026, 7, 30, 14, 30)) == datetime.date(
            2026, 7, 31
        )

    def test_today_west_of_utc_lags_the_utc_date(self) -> None:
        """21:00 New York on the 29th, while UTC has already reached the 30th."""
        assert today_in(NEW_YORK, now=utc(2026, 7, 30, 1, 0)) == datetime.date(
            2026, 7, 29
        )

    def test_defaults_to_the_current_instant(self) -> None:
        """Omitting ``now`` anchors on the real clock, in the given timezone.

        Sandwiched between two readings of the clock rather than compared to a
        second one: a bare equality would fail whenever the two readings landed
        either side of Sydney's midnight.
        """
        before = datetime.datetime.now(datetime.UTC)
        resolved = today_in(SYDNEY)
        after = datetime.datetime.now(datetime.UTC)

        assert local_date(before, SYDNEY) <= resolved <= local_date(after, SYDNEY)


@pytest.mark.unit
class TestIsFutureDated:
    """Strictly after today, judged on the user's local calendar."""

    NOW = utc(2026, 7, 30, 3, 0)  # 03:00 UTC on 30 July — today is the 30th in UTC

    def test_a_journal_starting_tomorrow_is_future_dated(self) -> None:
        journal = make_journal(utc(2026, 7, 31, 2))

        assert is_future_dated(journal, UTC_ZONE, now=self.NOW) is True

    def test_a_journal_starting_today_is_not_future_dated(self) -> None:
        """Today is not the future.

        Specification invariant 4 requires the due journal's date to be *in the
        future relative to today*, so a journal later the same day — even one
        starting at 23:00 — cannot hold a task.
        """
        journal = make_journal(utc(2026, 7, 30, 23))

        assert is_future_dated(journal, UTC_ZONE, now=self.NOW) is False

    def test_a_journal_starting_yesterday_is_not_future_dated(self) -> None:
        journal = make_journal(utc(2026, 7, 29, 2))

        assert is_future_dated(journal, UTC_ZONE, now=self.NOW) is False

    def test_a_multi_day_journal_that_started_yesterday_and_ends_tomorrow_is_past(
        self,
    ) -> None:
        """Open decision 2: a journal's date is its **start** date.

        A trip that began yesterday and runs until tomorrow is therefore past,
        and cannot be a due journal, however much of it is still ahead.
        """
        journal = make_journal(utc(2026, 7, 29, 2), utc(2026, 7, 31, 2))

        assert is_future_dated(journal, UTC_ZONE, now=self.NOW) is False

    def test_a_multi_day_journal_starting_tomorrow_is_future_dated(self) -> None:
        """The mirror of the straddling case — the end date never decides it."""
        journal = make_journal(utc(2026, 7, 31, 2), utc(2026, 8, 2, 2))

        assert is_future_dated(journal, UTC_ZONE, now=self.NOW) is True

    def test_the_boundary_is_the_users_midnight_not_utcs(self) -> None:
        """A Sydney user just past midnight: their "today" is already the 31st.

        A UTC reading would call the first journal future-dated, because 30 July
        18:00 UTC is still "today" there. It is not: in Sydney both instants fall
        on the 31st.
        """
        now = utc(2026, 7, 30, 14, 30)  # 00:30 AEST 31 Jul
        same_local_day = make_journal(utc(2026, 7, 30, 20))  # 06:00 AEST 31 Jul
        next_local_day = make_journal(utc(2026, 7, 31, 20))  # 06:00 AEST 1 Aug

        assert is_future_dated(same_local_day, SYDNEY, now=now) is False
        assert is_future_dated(next_local_day, SYDNEY, now=now) is True

    def test_a_dst_transition_day_is_compared_by_local_date(self) -> None:
        """On the 23-hour day the comparison still runs on local dates."""
        now = utc(2026, 10, 3, 20)  # 07:00 AEDT 4 Oct — today is the 4th
        late_on_the_same_day = make_journal(utc(2026, 10, 4, 12))  # 23:00 AEDT 4 Oct
        just_after_midnight = make_journal(utc(2026, 10, 4, 13, 30))  # 00:30 5 Oct

        assert is_future_dated(late_on_the_same_day, SYDNEY, now=now) is False
        assert is_future_dated(just_after_midnight, SYDNEY, now=now) is True


@pytest.mark.unit
class TestLocalDayWindow:
    """The user's local day as an instant range, for windowed journal queries."""

    def test_spans_midnight_to_the_final_microsecond_in_the_users_timezone(
        self,
    ) -> None:
        window = local_day_window(datetime.date(2026, 7, 30), SYDNEY)

        assert window.start.astimezone(datetime.UTC) == utc(2026, 7, 29, 14, 0)
        assert window.end.astimezone(datetime.UTC) == datetime.datetime(
            2026, 7, 30, 13, 59, 59, 999999, tzinfo=datetime.UTC
        )

    def test_a_spring_forward_day_is_twenty_three_hours_long(self) -> None:
        """The 4 Oct window opens at +10 and closes at +11, so it is an hour short.

        The endpoints are compared **after** conversion to UTC: subtracting two
        aware datetimes that share a ``tzinfo`` is naive arithmetic in Python and
        would report a full 24 hours regardless.
        """
        window = local_day_window(datetime.date(2026, 10, 4), SYDNEY)
        start_utc = window.start.astimezone(datetime.UTC)
        end_utc = window.end.astimezone(datetime.UTC)

        assert start_utc == utc(2026, 10, 3, 14, 0)
        assert end_utc == datetime.datetime(
            2026, 10, 4, 12, 59, 59, 999999, tzinfo=datetime.UTC
        )
        assert end_utc - start_utc == datetime.timedelta(hours=23) - datetime.timedelta(
            microseconds=1
        )


@pytest.mark.unit
class TestLocalWindow:
    """A span of local days as an instant range — the multi-day generalisation.

    ``local_day_window`` is now its single-day case, so the cases above still
    cover that. What is only reachable here is a span that *contains* a clock
    change, which is the shape the tasks upcoming window has: seven days is long
    enough to straddle a transition twice a year, and both ends then carry
    different offsets.
    """

    def test_it_spans_the_first_midnight_to_the_last_microsecond(self) -> None:
        """Both ends inclusive, which is what the upcoming window promises."""
        window = local_window(
            datetime.date(2026, 7, 30), datetime.date(2026, 8, 2), SYDNEY
        )

        assert window.start.astimezone(datetime.UTC) == utc(2026, 7, 29, 14, 0)
        assert window.end.astimezone(datetime.UTC) == datetime.datetime(
            2026, 8, 2, 13, 59, 59, 999999, tzinfo=datetime.UTC
        )

    def test_a_span_containing_a_clock_change_is_an_hour_short(self) -> None:
        """The two ends carry different offsets, and the span is what it really is.

        4 October 2026 is Sydney's spring forward, so a window opening on the 1st
        at +10 closes on the 7th at +11. Building both ends from *dates* is what
        makes this right: zeroing the components of some instant inside the span
        would carry that instant's offset to both ends and lose the hour.
        """
        window = local_window(
            datetime.date(2026, 10, 1), datetime.date(2026, 10, 7), SYDNEY
        )
        start_utc = window.start.astimezone(datetime.UTC)
        end_utc = window.end.astimezone(datetime.UTC)

        assert window.start.utcoffset() == datetime.timedelta(hours=10)
        assert window.end.utcoffset() == datetime.timedelta(hours=11)
        assert end_utc - start_utc == datetime.timedelta(days=7) - datetime.timedelta(
            hours=1, microseconds=1
        )

    @pytest.mark.parametrize(
        ("zone", "first", "last"),
        [
            # Sydney's spring forward, at 02:00 — the ordinary shape.
            (SYDNEY, datetime.date(2026, 10, 1), datetime.date(2026, 10, 7)),
            # Sydney's fall back, at 03:00.
            (SYDNEY, datetime.date(2026, 4, 1), datetime.date(2026, 4, 7)),
            # **Santiago's fall back happens at midnight**, so 23:00–23:59 on
            # 4 April occurs twice. That is the case a window built from
            # ``time.max`` gets wrong: ``fold=0`` picks the earlier pass and the
            # window closes an hour before the day does.
            (SANTIAGO, datetime.date(2026, 3, 29), datetime.date(2026, 4, 4)),
            # Beirut's, in the other hemisphere and the other half of the year.
            (BEIRUT, datetime.date(2026, 10, 18), datetime.date(2026, 10, 24)),
        ],
    )
    def test_every_local_day_in_the_span_falls_inside_the_instants(
        self, zone: ZoneInfo, first: datetime.date, last: datetime.date
    ) -> None:
        """The property that actually matters, over the zones that break it.

        The window exists to be compared against ``event_date_range_start`` in
        **SQL**, where the comparison is between *instants*. So what has to hold
        is that a journal whose ``journal_date`` is in the span has its instant
        in the range, at any hour of any day in it.

        Both sides are converted to UTC before comparing, and that is not
        incidental: Python compares two aware datetimes sharing one ``tzinfo``
        by their *naive* values, so a version of this test that compared them
        as-is would assert wall-clock containment — passing happily against a
        window whose instants were an hour short. Found by review, having been
        written the wrong way first.

        The failure this pins is a task vanishing from a dashboard for one day a
        year in Santiago, with nothing to tell the user it was ever there.

        Each hour is probed in **both folds**. ``combine`` always produces
        ``fold=0``, so a repeated hour would otherwise only ever be sampled on
        its first pass — and the second pass is precisely the instant the broken
        window excluded.
        """
        window = local_window(first, last, zone)
        start_utc = window.start.astimezone(datetime.UTC)
        end_utc = window.end.astimezone(datetime.UTC)

        outside = [
            (day, hour, fold)
            for offset in range((last - first).days + 1)
            for day in [first + datetime.timedelta(days=offset)]
            for hour in (0, 12, 23)
            for fold in (0, 1)
            for moment in [
                datetime.datetime.combine(day, datetime.time(hour), zone).replace(
                    fold=fold
                )
            ]
            if journal_date(make_journal(moment), zone) == day
            and not (start_utc <= moment.astimezone(datetime.UTC) <= end_utc)
        ]

        assert outside == []

    def test_the_window_ends_where_the_next_day_begins(self) -> None:
        """One microsecond before the following midnight, in an ambiguous zone.

        Santiago's clocks go back **at midnight** on 5 April 2026, so 4 April
        has two 23:00 hours and its final microsecond is the later one. Asserted
        as an absolute instant, because the local wall time ``23:59:59.999999``
        names both of them and is exactly the ambiguity that made this wrong.
        """
        day = datetime.date(2026, 4, 4)
        window = local_window(day, day, SANTIAGO)
        next_midnight = datetime.datetime.combine(
            day + datetime.timedelta(days=1), datetime.time.min, SANTIAGO
        )

        assert window.end.astimezone(datetime.UTC) == next_midnight.astimezone(
            datetime.UTC
        ) - datetime.timedelta(microseconds=1)

    def test_a_day_whose_clocks_go_back_at_midnight_is_twenty_five_hours_long(
        self,
    ) -> None:
        """The regression case, stated as the thing a user would notice.

        A window an hour short here is not an approximation: it is a journal at
        23:30 local, on a date the window says it covers, that no query returns.
        """
        window = local_day_window(datetime.date(2026, 4, 4), SANTIAGO)
        span = window.end.astimezone(datetime.UTC) - window.start.astimezone(
            datetime.UTC
        )

        assert span == datetime.timedelta(hours=25) - datetime.timedelta(microseconds=1)

    def test_a_single_day_span_matches_the_day_window(self) -> None:
        """``local_day_window`` is defined as this, so the two cannot drift."""
        day = datetime.date(2026, 10, 4)

        assert local_window(day, day, SYDNEY) == local_day_window(day, SYDNEY)


@pytest.mark.unit
class TestJournalDateResolver:
    """The async wrapper: it supplies the timezone and nothing else."""

    @pytest.fixture
    def mock_user_settings_repo(self) -> AsyncMock:
        repo = AsyncMock()
        repo.get_timezone.return_value = "Australia/Sydney"
        return repo

    @pytest.fixture
    def resolver(self, mock_user_settings_repo: AsyncMock) -> JournalDateResolver:
        return JournalDateResolver(user_settings_repo=mock_user_settings_repo)

    async def test_timezone_for_reads_the_users_setting(
        self, resolver: JournalDateResolver, mock_user_settings_repo: AsyncMock
    ) -> None:
        assert (await resolver.timezone_for(USER_ID)).key == "Australia/Sydney"
        mock_user_settings_repo.get_timezone.assert_awaited_once_with(USER_ID)

    async def test_an_unknown_timezone_name_falls_back_to_utc(
        self, resolver: JournalDateResolver, mock_user_settings_repo: AsyncMock
    ) -> None:
        """A stored value the tz database does not know must not break a read."""
        mock_user_settings_repo.get_timezone.return_value = "Not/A_Zone"

        assert (await resolver.timezone_for(USER_ID)).key == "UTC"

    async def test_today_uses_the_users_timezone(
        self, resolver: JournalDateResolver
    ) -> None:
        today = await resolver.today(USER_ID, now=utc(2026, 7, 30, 14, 30))

        assert today == datetime.date(2026, 7, 31)

    async def test_is_future_dated_uses_the_users_timezone(
        self, resolver: JournalDateResolver
    ) -> None:
        now = utc(2026, 7, 30, 14, 30)  # 00:30 AEST 31 Jul
        same_local_day = make_journal(utc(2026, 7, 30, 20))
        next_local_day = make_journal(utc(2026, 7, 31, 20))

        assert await resolver.is_future_dated(USER_ID, same_local_day, now=now) is False
        assert await resolver.is_future_dated(USER_ID, next_local_day, now=now) is True

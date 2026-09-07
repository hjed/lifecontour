"""Unit tests for which days a change makes a daily summary stale.

The rule this module pins is the whole of ITER18-005 Phase 7's mapping, and it
is a *span* rule rather than a date one. ``SqlJournalRepository.get_all``
selects a day's journals by **overlap** —
``event_date_range_end >= :start AND event_date_range_start <= :end`` — so a
journal running Friday to Sunday is part of three days' summaries, and a change
to it makes three stale. The handler this phase replaces mapped every journal to
a single date, which is the first of the four defects ITER18-004 Phase 4f
recorded against it.

Every span here is built from instants rather than dates, because the local span
is where a UTC reading gives a different answer, and a rule that only holds at
midday is not a rule.
"""

import datetime
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.date_window import upcoming_window
from core_shared.models.journals import EventDateRange

from app.core.journal.services.daily_summary_invalidation_targets import (
    DaySpan,
    InvalidationTarget,
    day_span_of,
    targets_for_journal,
    targets_for_task_due_span,
)

USER_ID = "test-user-123"

SYDNEY = ZoneInfo("Australia/Sydney")
LOS_ANGELES = ZoneInfo("America/Los_Angeles")
UTC_ZONE = ZoneInfo("UTC")

TODAY = datetime.date(2026, 4, 27)


def _day(day: int) -> datetime.date:
    """A date in April 2026, so the cases read as offsets from ``TODAY``."""
    return datetime.date(2026, 4, day)


def _range(start: datetime.datetime, end: datetime.datetime) -> EventDateRange:
    return EventDateRange(start=start, end=end)


class TestDaySpanRejectsWhatIsNotASpan:
    """A reversed span is a caller's bug, not a question with an empty answer."""

    def test_a_last_day_before_the_first_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must not precede"):
            DaySpan(first_day=_day(27), last_day=_day(26))

    def test_a_single_day_is_a_span(self) -> None:
        span = DaySpan(first_day=_day(27), last_day=_day(27))

        assert span.contains(_day(27))
        assert not span.contains(_day(28))


class TestClippingASpanToThePast:
    """A task's past-day half is the part of its span already behind the user."""

    def test_a_span_wholly_before_today_is_kept_whole(self) -> None:
        span = DaySpan(first_day=_day(20), last_day=_day(22))

        assert span.clipped_before(TODAY) == span

    def test_a_span_crossing_today_keeps_only_the_days_before_it(self) -> None:
        span = DaySpan(first_day=_day(25), last_day=_day(29))

        assert span.clipped_before(TODAY) == DaySpan(
            first_day=_day(25), last_day=_day(26)
        )

    def test_a_span_starting_today_clips_to_nothing(self) -> None:
        span = DaySpan(first_day=TODAY, last_day=_day(30))

        assert span.clipped_before(TODAY) is None

    def test_a_span_wholly_ahead_clips_to_nothing(self) -> None:
        span = DaySpan(first_day=_day(30), last_day=_day(30))

        assert span.clipped_before(TODAY) is None


class TestTheLocalSpanOfAnEventDateRange:
    """The span is local days, and the zone is the acting user's.

    Each case is one where reading the instants in UTC answers differently.
    """

    def test_a_single_day_event_spans_one_day(self) -> None:
        span = day_span_of(
            _range(
                datetime.datetime(2026, 4, 27, 9, 0, tzinfo=datetime.UTC),
                datetime.datetime(2026, 4, 27, 10, 0, tzinfo=datetime.UTC),
            ),
            UTC_ZONE,
        )

        assert span == DaySpan(first_day=_day(27), last_day=_day(27))

    def test_a_multi_day_event_spans_every_day_it_touches(self) -> None:
        span = day_span_of(
            _range(
                datetime.datetime(2026, 4, 24, 18, 0, tzinfo=datetime.UTC),
                datetime.datetime(2026, 4, 26, 8, 0, tzinfo=datetime.UTC),
            ),
            UTC_ZONE,
        )

        assert span == DaySpan(first_day=_day(24), last_day=_day(26))

    def test_the_span_is_read_in_the_users_zone_not_utc_far_east(self) -> None:
        """22:00 UTC on the 26th is already the 27th in Sydney."""
        span = day_span_of(
            _range(
                datetime.datetime(2026, 4, 26, 22, 0, tzinfo=datetime.UTC),
                datetime.datetime(2026, 4, 26, 23, 0, tzinfo=datetime.UTC),
            ),
            SYDNEY,
        )

        assert span == DaySpan(first_day=_day(27), last_day=_day(27))

    def test_the_span_is_read_in_the_users_zone_not_utc_far_west(self) -> None:
        """02:00 UTC on the 27th is still the 26th in Los Angeles."""
        span = day_span_of(
            _range(
                datetime.datetime(2026, 4, 27, 2, 0, tzinfo=datetime.UTC),
                datetime.datetime(2026, 4, 27, 3, 0, tzinfo=datetime.UTC),
            ),
            LOS_ANGELES,
        )

        assert span == DaySpan(first_day=_day(26), last_day=_day(26))

    def test_an_event_ending_at_local_midnight_reaches_the_following_day(self) -> None:
        """Deliberate, and the same answer the day query gives.

        ``get_all`` selects on ``event_date_range_end >= :start``, and the
        following day's window starts at that very instant, so the journal is in
        that day's summary. The span has to agree or the day would never be
        invalidated.
        """
        span = day_span_of(
            _range(
                datetime.datetime(2026, 4, 27, 20, 0, tzinfo=datetime.UTC),
                datetime.datetime(2026, 4, 28, 0, 0, tzinfo=datetime.UTC),
            ),
            UTC_ZONE,
        )

        assert span == DaySpan(first_day=_day(27), last_day=_day(28))


class TestTargetsForAJournalChange:
    """A journal change makes every day of its span stale — old span included."""

    def test_one_span_is_one_target(self) -> None:
        span = DaySpan(first_day=_day(24), last_day=_day(26))

        assert targets_for_journal(USER_ID, span) == frozenset(
            {InvalidationTarget(user_id=USER_ID, span=span)}
        )

    def test_a_move_carries_the_day_the_journal_left(self) -> None:
        """The first of the four defects ITER18-004 Phase 4f recorded."""
        was = DaySpan(first_day=_day(20), last_day=_day(20))
        now = DaySpan(first_day=_day(27), last_day=_day(27))

        assert targets_for_journal(USER_ID, was, now) == frozenset(
            {
                InvalidationTarget(user_id=USER_ID, span=was),
                InvalidationTarget(user_id=USER_ID, span=now),
            }
        )

    def test_a_move_within_one_day_collapses_to_a_single_target(self) -> None:
        """An edit that moved the clock but not the day costs one statement."""
        span = DaySpan(first_day=_day(27), last_day=_day(27))

        assert targets_for_journal(USER_ID, span, span) == frozenset(
            {InvalidationTarget(user_id=USER_ID, span=span)}
        )

    def test_no_spans_is_nothing_to_invalidate(self) -> None:
        assert targets_for_journal(USER_ID) == frozenset()


class TestTargetsForATaskChange:
    """A task's days follow its **due** journal, and the two halves differ.

    Today's summary lists not-done tasks whose due journal *starts* inside the
    week ahead; a past day's summary lists what was due in that day's journals,
    which is the overlap set again. So a past span invalidates the days it
    covers, and a future one invalidates today — never both, because a span
    starting before today cannot start inside a window that begins at today.
    """

    window = upcoming_window(TODAY)

    def _targets(self, span: DaySpan) -> frozenset[InvalidationTarget]:
        return targets_for_task_due_span(USER_ID, span, today=TODAY, window=self.window)

    def test_a_task_due_on_a_past_day_invalidates_that_day(self) -> None:
        span = DaySpan(first_day=_day(20), last_day=_day(20))

        assert self._targets(span) == frozenset(
            {InvalidationTarget(user_id=USER_ID, span=span)}
        )

    def test_a_task_due_in_a_past_multi_day_journal_invalidates_every_day(self) -> None:
        span = DaySpan(first_day=_day(20), last_day=_day(22))

        assert self._targets(span) == frozenset(
            {InvalidationTarget(user_id=USER_ID, span=span)}
        )

    def test_a_task_due_today_invalidates_today(self) -> None:
        span = DaySpan(first_day=TODAY, last_day=TODAY)

        assert self._targets(span) == frozenset(
            {InvalidationTarget.for_day(USER_ID, TODAY)}
        )

    def test_a_task_due_inside_the_week_invalidates_today_and_not_its_own_day(
        self,
    ) -> None:
        """The forward-looking half is rendered on **today's** prompt, nowhere else."""
        span = DaySpan(first_day=_day(30), last_day=_day(30))

        assert self._targets(span) == frozenset(
            {InvalidationTarget.for_day(USER_ID, TODAY)}
        )

    def test_the_last_day_of_the_window_is_inside_it(self) -> None:
        span = DaySpan(
            first_day=_day(27) + datetime.timedelta(days=7),
            last_day=_day(27) + datetime.timedelta(days=7),
        )

        assert self._targets(span) == frozenset(
            {InvalidationTarget.for_day(USER_ID, TODAY)}
        )

    def test_a_day_past_the_window_invalidates_nothing(self) -> None:
        span = DaySpan(
            first_day=_day(27) + datetime.timedelta(days=8),
            last_day=_day(27) + datetime.timedelta(days=8),
        )

        assert self._targets(span) == frozenset()

    def test_a_span_crossing_today_invalidates_only_the_days_behind_it(self) -> None:
        """It started before the window opens, so it is in no upcoming listing.

        The days it covered before today still describe it, which is why the
        past half is not empty.
        """
        span = DaySpan(first_day=_day(25), last_day=_day(29))

        assert self._targets(span) == frozenset(
            {
                InvalidationTarget(
                    user_id=USER_ID,
                    span=DaySpan(first_day=_day(25), last_day=_day(26)),
                )
            }
        )

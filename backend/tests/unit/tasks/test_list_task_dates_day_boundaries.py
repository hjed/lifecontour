"""The list-task date rules across the user's day boundaries.

The rules in ``core_shared.models.tasks.list_dates`` take dates already resolved
in the user's timezone. These tests drive the whole composition from UTC
instants — the way the database hands journals back and the clock hands ``now``
— through ``today_in``, ``journal_date`` and ``journal_last_day``, so that a task
turns overdue at the user's **local** midnight and not at UTC's.

Each boundary is tested from both sides, and at least one side of each is a case
where a UTC reading gives the other answer. Instants are fixed
so the boundaries and Sydney's 2026 spring-forward (4 October, AEST +10 → AEDT
+11) are exercised the same way on every run.
"""

import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import (
    DueJournalDays,
    Task,
    TaskDateState,
    derive_task_date_state,
    is_due_date_allowed,
    list_task_due,
)

from app.core.journal.services.journal_date_resolver import (
    journal_date,
    journal_last_day,
    today_in,
)

pytestmark = pytest.mark.unit

SYDNEY = ZoneInfo("Australia/Sydney")
NEW_YORK = ZoneInfo("America/New_York")

USER_ID = "user-1"
DUE_JOURNAL_ID = 22

NINTH_OF_AUGUST = datetime.date(2026, 8, 9)
OVERDUE = TaskDateState(lapse_reason=None, overdue=True)
NOT_OVERDUE = TaskDateState(lapse_reason=None, overdue=False)


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0
) -> datetime.datetime:
    """A UTC instant, the way the database hands timestamps back."""
    return datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.UTC)


def make_journal(start: datetime.datetime, end: datetime.datetime) -> Journal:
    """A journal spanning ``start`` to ``end``, both stored in UTC."""
    return Journal(
        user_id=USER_ID,
        title="A trip",
        content="content",
        event_date_range=EventDateRange(start=start, end=end),
    )


def list_task(**overrides: Any) -> Task:
    """A not-done, undated task on a list."""
    fields: dict[str, Any] = {
        "user_id": USER_ID,
        "text": "Pack the tent",
        "task_list_id": 5,
        "position": 0,
    }
    fields.update(overrides)
    return Task(**fields)


def due_journal_days(journal: Journal, tz: ZoneInfo) -> DueJournalDays:
    """Resolve a due journal's days in ``tz``, as a reader will."""
    return DueJournalDays(
        first_day=journal_date(journal, tz),
        last_day=journal_last_day(journal, tz),
        cancelled=False,
    )


def state_at(
    task: Task,
    tz: ZoneInfo,
    now: datetime.datetime,
    journal: Journal | None = None,
) -> TaskDateState:
    """The task's date state at ``now``, everything resolved in ``tz``."""
    return derive_task_date_state(
        task=task,
        due_journal=due_journal_days(journal, tz) if journal else None,
        today=today_in(tz, now),
    )


class TestADueDateTurnsOverdueAtLocalMidnight:
    """A task due 9 August is overdue from the user's midnight into the 10th."""

    @pytest.mark.parametrize(
        ("tz", "now", "expected"),
        [
            # 23:59 AEST on the 9th: the day is not over.
            pytest.param(
                SYDNEY, utc(2026, 8, 9, 13, 59), NOT_OVERDUE, id="sydney-23:59"
            ),
            # 00:00 AEST on the 10th — still the 9th in UTC, already overdue.
            pytest.param(SYDNEY, utc(2026, 8, 9, 14, 0), OVERDUE, id="sydney-00:00"),
            # 23:30 EDT on the 9th — already the 10th in UTC, not yet overdue.
            pytest.param(
                NEW_YORK, utc(2026, 8, 10, 3, 30), NOT_OVERDUE, id="new-york-23:30"
            ),
            # 00:00 EDT on the 10th: overdue.
            pytest.param(
                NEW_YORK, utc(2026, 8, 10, 4, 0), OVERDUE, id="new-york-00:00"
            ),
        ],
    )
    def test_overdue_follows_the_users_calendar_not_utcs(
        self, tz: ZoneInfo, now: datetime.datetime, expected: TaskDateState
    ) -> None:
        """The flip happens at local midnight, either side of UTC."""
        task = list_task(due_date=NINTH_OF_AUGUST)

        assert state_at(task, tz, now) == expected


class TestAMultiDayJournalIsOverdueOnlyOnceItIsOver:
    """A 14–16 August trip, stored as Sydney local midnights.

    Its start, 00:00 AEST on the 14th, is 14:00 UTC on the 13th; its end,
    00:00 AEST on the 16th — the start of its last day — is 14:00 UTC on the 15th.
    """

    TRIP = make_journal(utc(2026, 8, 13, 14), utc(2026, 8, 15, 14))

    @pytest.mark.parametrize(
        ("now", "expected"),
        [
            # Midday on day two, 15 Aug.
            pytest.param(utc(2026, 8, 15, 2), NOT_OVERDUE, id="day-two"),
            # 23:59 on the last day, 16 Aug.
            pytest.param(utc(2026, 8, 16, 13, 59), NOT_OVERDUE, id="last-day-23:59"),
            # Local midnight after the last day.
            pytest.param(utc(2026, 8, 16, 14, 0), OVERDUE, id="day-after-00:00"),
        ],
    )
    def test_the_packing_list_waits_for_the_trip_to_end(
        self, now: datetime.datetime, expected: TaskDateState
    ) -> None:
        """Not overdue during the trip; overdue from the midnight it ends."""
        task = list_task(due_journal_id=DUE_JOURNAL_ID)

        assert state_at(task, SYDNEY, now, self.TRIP) == expected

    def test_the_task_is_still_dated_by_the_trips_first_day(self) -> None:
        """Its date — the week it belongs in — is the day the trip starts."""
        due = list_task_due(
            due_date=None, due_journal=due_journal_days(self.TRIP, SYDNEY)
        )

        assert due is not None
        assert due.day == datetime.date(2026, 8, 14)
        assert due.overdue_after == datetime.date(2026, 8, 16)


class TestAClockChangeInsideTheJournal:
    """A 3–5 October trip, across Sydney's 4 October spring-forward.

    It starts at 00:00 AEST (+10) on the 3rd, 14:00 UTC on the 2nd, and its end,
    00:00 AEDT (+11) on the 5th, is 13:00 UTC on the 4th.
    """

    TRIP = make_journal(utc(2026, 10, 2, 14), utc(2026, 10, 4, 13))

    def test_the_last_day_survives_the_offset_change(self) -> None:
        """The last day is still the 5th, with an hour fewer behind it."""
        assert journal_last_day(self.TRIP, SYDNEY) == datetime.date(2026, 10, 5)

    @pytest.mark.parametrize(
        ("now", "expected"),
        [
            # 23:59 AEDT on the 5th.
            pytest.param(utc(2026, 10, 5, 12, 59), NOT_OVERDUE, id="last-day-23:59"),
            # 00:00 AEDT on the 6th — an hour earlier in UTC than in August.
            pytest.param(utc(2026, 10, 5, 13, 0), OVERDUE, id="day-after-00:00"),
        ],
    )
    def test_overdue_starts_at_the_new_offsets_midnight(
        self, now: datetime.datetime, expected: TaskDateState
    ) -> None:
        """Midnight after the trip is judged at +11, not the +10 it began in."""
        task = list_task(due_journal_id=DUE_JOURNAL_ID)

        assert state_at(task, SYDNEY, now, self.TRIP) == expected


class TestADueDateIsAllowedUntilItsDayEnds:
    """ "Today or later" is the user's today: a due date stays settable until
    their midnight, whatever UTC's date says."""

    @pytest.mark.parametrize(
        ("now", "allowed"),
        [
            # 23:59 AEST on the 9th: the 9th is today.
            pytest.param(utc(2026, 8, 9, 13, 59), True, id="23:59-today"),
            # 00:00 AEST on the 10th — still the 9th in UTC: now yesterday.
            pytest.param(utc(2026, 8, 9, 14, 0), False, id="00:00-yesterday"),
        ],
    )
    def test_the_same_date_is_refused_one_minute_later(
        self, now: datetime.datetime, allowed: bool
    ) -> None:
        """The boundary is Sydney's midnight."""
        assert is_due_date_allowed(NINTH_OF_AUGUST, today_in(SYDNEY, now)) is allowed

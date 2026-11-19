"""Unit tests for the date rules a task on a list follows.

A task on a list has a due date, a due journal, or no date at all, and it
**never lapses**: past its date it reads as *overdue* and stays open on its list.
A due journal's date is the day it starts, but a list task due in it is only
overdue once the journal's **last** day has ended, so a trip's packing list is
not overdue on day two. While the due journal is cancelled the task is undated.
And a due date, when set, must be today or later.

Every rule is pure and takes dates already resolved in the user's timezone, as
the lapse rule does. Dates are fixed rather than relative to ``now`` so each
boundary is exercised the same way on every run; the timezone composition is
proven in ``test_list_task_dates_day_boundaries.py``.
"""

import datetime
from typing import Any

import pytest
from core_shared.models.tasks import (
    DueJournalDays,
    LapseReason,
    ListTaskDue,
    Task,
    TaskDateState,
    TaskDomainError,
    TaskDueDateInPastError,
    TaskStatus,
    derive_task_date_state,
    ensure_due_date_allowed,
    is_due_date_allowed,
    is_list_task_overdue,
    list_task_due,
)

pytestmark = pytest.mark.unit

TODAY = datetime.date(2026, 8, 9)
YESTERDAY = datetime.date(2026, 8, 8)
TOMORROW = datetime.date(2026, 8, 10)

LIST_ID = 5
CREATING_JOURNAL_ID = 11
DUE_JOURNAL_ID = 22


def journal_days(
    first_day: datetime.date,
    last_day: datetime.date | None = None,
    *,
    cancelled: bool = False,
) -> DueJournalDays:
    """A due journal's resolved days; single-day unless a last day is given."""
    return DueJournalDays(
        first_day=first_day, last_day=last_day or first_day, cancelled=cancelled
    )


def overdue(due: ListTaskDue | None, status: TaskStatus = TaskStatus.NOT_DONE) -> bool:
    """The overdue rule, with today pinned so each call reads as its own case."""
    return is_list_task_overdue(status=status, due=due, today=TODAY)


def due_on(day: datetime.date) -> ListTaskDue:
    """A list task's due-by-date, as ``list_task_due`` would build it."""
    due = list_task_due(due_date=day, due_journal=None)
    assert due is not None
    return due


def make_task(**overrides: Any) -> Task:
    """A not-done list task with no date, overridable per case."""
    fields: dict[str, Any] = {
        "user_id": "user-1",
        "text": "Pack the tent",
        "task_list_id": LIST_ID,
        "position": 0,
    }
    fields.update(overrides)
    return Task(**fields)


def journal_only_task(status: TaskStatus = TaskStatus.NOT_DONE) -> Task:
    """A task with both anchors and no list."""
    return make_task(
        task_list_id=None,
        position=None,
        creating_journal_id=CREATING_JOURNAL_ID,
        due_journal_id=DUE_JOURNAL_ID,
        status=status,
    )


class TestDueJournalDays:
    """A due journal's days arrive resolved, and must make sense as a span."""

    def test_a_last_day_before_the_first_is_refused(self) -> None:
        """A journal cannot end before it starts."""
        with pytest.raises(ValueError, match="last_day"):
            DueJournalDays(first_day=TODAY, last_day=YESTERDAY, cancelled=False)

    def test_a_datetime_is_refused_as_a_first_day(self) -> None:
        """An instant would mean a caller skipped the timezone conversion."""
        with pytest.raises(TypeError, match="first_day"):
            DueJournalDays(
                first_day=datetime.datetime(2026, 8, 9, 14, tzinfo=datetime.UTC),
                last_day=TODAY,
                cancelled=False,
            )

    def test_a_datetime_is_refused_as_a_last_day(self) -> None:
        """The last day is a calendar date too."""
        with pytest.raises(TypeError, match="last_day"):
            DueJournalDays(
                first_day=TODAY,
                last_day=datetime.datetime(2026, 8, 10, 14, tzinfo=datetime.UTC),
                cancelled=False,
            )

    def test_a_single_day_journal_starts_and_ends_on_its_day(self) -> None:
        """The same day twice is a valid span."""
        days = DueJournalDays(first_day=TODAY, last_day=TODAY, cancelled=False)

        assert days.first_day == days.last_day == TODAY


class TestListTaskDue:
    """Where a list task's date comes from, and when that day is over."""

    def test_an_undated_task_has_no_due(self) -> None:
        """No due date and no due journal: the task simply lives on its list."""
        assert list_task_due(due_date=None, due_journal=None) is None

    def test_a_due_date_is_both_the_day_and_the_day_it_is_over(self) -> None:
        """A due date names one day, and the task is overdue once it ends."""
        assert list_task_due(due_date=TOMORROW, due_journal=None) == ListTaskDue(
            day=TOMORROW, overdue_after=TOMORROW
        )

    def test_a_single_day_journal_dates_the_task_by_its_day(self) -> None:
        """A one-day journal's date is both ends of the task's due."""
        assert list_task_due(
            due_date=None, due_journal=journal_days(TOMORROW)
        ) == ListTaskDue(day=TOMORROW, overdue_after=TOMORROW)

    def test_a_multi_day_journal_is_dated_by_its_start_and_over_after_its_end(
        self,
    ) -> None:
        """The journal's date is its first day, but it is over after its last.

        Its first day is the date for every task purpose (when it is due, the
        week it lands in); only overdue waits for the journal to be over.
        """
        last_day = datetime.date(2026, 8, 12)

        assert list_task_due(
            due_date=None, due_journal=journal_days(TOMORROW, last_day)
        ) == ListTaskDue(day=TOMORROW, overdue_after=last_day)

    def test_a_cancelled_due_journal_leaves_the_task_undated(self) -> None:
        """While the journal is cancelled the task is treated as undated."""
        assert (
            list_task_due(
                due_date=None, due_journal=journal_days(YESTERDAY, cancelled=True)
            )
            is None
        )

    def test_un_cancelling_the_journal_restores_the_date(self) -> None:
        """Nothing is stored, so the same journal uncancelled dates the task."""
        assert list_task_due(
            due_date=None, due_journal=journal_days(YESTERDAY, cancelled=False)
        ) == ListTaskDue(day=YESTERDAY, overdue_after=YESTERDAY)

    def test_a_due_date_beside_a_due_journal_is_refused(self) -> None:
        """Invariant 4: a due date or a due journal, never both."""
        due_journal = journal_days(TOMORROW)

        with pytest.raises(ValueError, match="both"):
            list_task_due(due_date=TOMORROW, due_journal=due_journal)


class TestListTaskOverdue:
    """A list task is overdue strictly after the day it is over."""

    def test_a_task_due_yesterday_is_overdue(self) -> None:
        """Its day has ended."""
        assert overdue(due_on(YESTERDAY)) is True

    def test_a_task_due_today_is_not_overdue(self) -> None:
        """Today has not ended — the same boundary as the lapse rule."""
        assert overdue(due_on(TODAY)) is False

    def test_a_task_due_tomorrow_is_not_overdue(self) -> None:
        """Its day has not come."""
        assert overdue(due_on(TOMORROW)) is False

    @pytest.mark.parametrize(
        ("first_day", "last_day"),
        [
            pytest.param(TODAY, datetime.date(2026, 8, 11), id="first-day"),
            pytest.param(YESTERDAY, TOMORROW, id="middle-day"),
            pytest.param(datetime.date(2026, 8, 7), TODAY, id="last-day"),
        ],
    )
    def test_a_task_due_in_a_journal_still_under_way_is_not_overdue(
        self, first_day: datetime.date, last_day: datetime.date
    ) -> None:
        """A trip's packing list is not overdue on day two, or on its last day."""
        due = list_task_due(
            due_date=None, due_journal=journal_days(first_day, last_day)
        )

        assert overdue(due) is False

    def test_a_task_due_in_a_journal_is_overdue_the_day_after_it_ends(self) -> None:
        """Once the last day has ended, the task is overdue."""
        due = list_task_due(
            due_date=None,
            due_journal=journal_days(datetime.date(2026, 8, 6), YESTERDAY),
        )

        assert overdue(due) is True

    def test_an_undated_task_is_never_overdue(self) -> None:
        """With no date there is nothing to be late for."""
        assert overdue(None) is False

    def test_a_task_due_in_a_cancelled_past_journal_is_not_overdue(self) -> None:
        """A cancelled due journal leaves the task undated, so not overdue."""
        due = list_task_due(
            due_date=None, due_journal=journal_days(YESTERDAY, cancelled=True)
        )

        assert overdue(due) is False

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    def test_a_closed_task_past_its_date_is_not_overdue(
        self, status: TaskStatus
    ) -> None:
        """Overdue lasts until the task is done or cancelled."""
        assert overdue(due_on(YESTERDAY), status) is False


class TestDueDateAllowed:
    """A due date, when set, must be today or later in the user's timezone."""

    def test_yesterday_is_not_allowed(self) -> None:
        """A due date in the past is refused."""
        assert is_due_date_allowed(YESTERDAY, TODAY) is False

    @pytest.mark.parametrize("due_date", [TODAY, TOMORROW])
    def test_today_and_later_are_allowed(self, due_date: datetime.date) -> None:
        """Today counts — unlike a due journal, which must be strictly future."""
        assert is_due_date_allowed(due_date, TODAY) is True
        ensure_due_date_allowed(due_date, TODAY)

    def test_a_past_due_date_raises_a_domain_error_carrying_both_dates(
        self,
    ) -> None:
        """The refusal names the chosen day and the day it is, as a 400."""
        with pytest.raises(TaskDueDateInPastError) as raised:
            ensure_due_date_allowed(YESTERDAY, TODAY)

        error = raised.value
        assert isinstance(error, TaskDomainError)
        assert error.status_code == 400
        assert error.due_date == YESTERDAY
        assert error.today == TODAY
        assert str(YESTERDAY) in str(error)
        assert str(TODAY) in str(error)

    def test_a_datetime_is_refused_as_a_due_date(self) -> None:
        """A due date is a calendar day; an instant is a caller's bug."""
        with pytest.raises(TypeError, match="due_date"):
            is_due_date_allowed(
                datetime.datetime(2026, 8, 9, 14, tzinfo=datetime.UTC), TODAY
            )


class TestTaskDateState:
    """One answer, for any task, to "lapsed or overdue?"."""

    def test_a_list_task_past_its_due_date_is_overdue_and_not_lapsed(self) -> None:
        """Invariant 7: past its date a list task is overdue, never lapsed."""
        state = derive_task_date_state(
            task=make_task(due_date=YESTERDAY), due_journal=None, today=TODAY
        )

        assert state == TaskDateState(lapse_reason=None, overdue=True)

    @pytest.mark.parametrize(
        ("days", "expected_overdue"),
        [
            pytest.param(journal_days(YESTERDAY), True, id="passed"),
            pytest.param(
                journal_days(YESTERDAY, cancelled=True), False, id="cancelled"
            ),
        ],
    )
    def test_a_list_task_never_lapses_through_its_due_journal(
        self, days: DueJournalDays, expected_overdue: bool
    ) -> None:
        """Neither a passed nor a cancelled due journal lapses a list task."""
        task = make_task(due_journal_id=DUE_JOURNAL_ID)

        state = derive_task_date_state(task=task, due_journal=days, today=TODAY)

        assert state == TaskDateState(lapse_reason=None, overdue=expected_overdue)

    def test_an_undated_list_task_is_neither_lapsed_nor_overdue(self) -> None:
        """An undated task simply lives on its list."""
        state = derive_task_date_state(task=make_task(), due_journal=None, today=TODAY)

        assert state == TaskDateState(lapse_reason=None, overdue=False)

    def test_a_journal_only_task_past_its_due_journal_lapses(self) -> None:
        """Journal-only tasks keep the existing rule, and are never overdue."""
        state = derive_task_date_state(
            task=journal_only_task(), due_journal=journal_days(YESTERDAY), today=TODAY
        )

        assert state == TaskDateState(
            lapse_reason=LapseReason.DATE_PASSED, overdue=False
        )

    def test_a_journal_only_task_with_a_cancelled_due_journal_lapses(self) -> None:
        """Cancellation still lapses a journal-only task, whatever its date."""
        state = derive_task_date_state(
            task=journal_only_task(),
            due_journal=journal_days(TOMORROW, cancelled=True),
            today=TODAY,
        )

        assert state == TaskDateState(
            lapse_reason=LapseReason.DUE_JOURNAL_CANCELLED, overdue=False
        )

    def test_a_journal_only_task_due_in_a_multi_day_journal_lapses_after_its_start(
        self,
    ) -> None:
        """The lapse rule still dates a journal by its first day, unchanged."""
        state = derive_task_date_state(
            task=journal_only_task(),
            due_journal=journal_days(YESTERDAY, TOMORROW),
            today=TODAY,
        )

        assert state.lapse_reason is LapseReason.DATE_PASSED

    def test_a_journal_only_task_added_to_a_list_follows_list_rules(self) -> None:
        """Once on a list it stops lapsing and reads as overdue instead."""
        task = make_task(
            creating_journal_id=CREATING_JOURNAL_ID, due_journal_id=DUE_JOURNAL_ID
        )

        state = derive_task_date_state(
            task=task, due_journal=journal_days(YESTERDAY), today=TODAY
        )

        assert state == TaskDateState(lapse_reason=None, overdue=True)

    def test_a_done_list_task_past_its_date_is_neither(self) -> None:
        """A closed list task is not overdue."""
        state = derive_task_date_state(
            task=make_task(due_date=YESTERDAY, status=TaskStatus.DONE),
            due_journal=None,
            today=TODAY,
        )

        assert state == TaskDateState(lapse_reason=None, overdue=False)

    def test_due_journal_days_for_a_task_without_a_due_journal_are_refused(
        self,
    ) -> None:
        """Days for a journal the task is not due in are a caller's bug."""
        task = make_task()
        due_journal = journal_days(TODAY)

        with pytest.raises(ValueError, match="due_journal"):
            derive_task_date_state(task=task, due_journal=due_journal, today=TODAY)

    def test_missing_due_journal_days_for_a_task_with_one_are_refused(self) -> None:
        """A task with a due journal cannot be judged without its days."""
        task = make_task(due_journal_id=DUE_JOURNAL_ID)

        with pytest.raises(ValueError, match="due_journal"):
            derive_task_date_state(task=task, due_journal=None, today=TODAY)

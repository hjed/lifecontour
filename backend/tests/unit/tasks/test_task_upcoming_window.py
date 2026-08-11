"""Unit tests for the upcoming window: its arithmetic, its exclusions, its order.

The dashboard's tasks section asks for "not-done tasks whose due journal falls
between today and seven days ahead, inclusive". Three separate claims live in
that sentence — where the window starts and ends, which tasks it drops, and what
order the survivors come back in — and all three are pure, so they are asserted
here rather than through a service.

**The boundary day is the case worth writing.** "Inclusive" is exactly the word
an off-by-one gets wrong, and a fixture set that only ever puts tasks in the
middle of the window would pass against ``<`` as happily as against ``<=``. So
every edge is pinned from both sides: today and yesterday, the last day and the
day after it.

**The lapsed exclusion needs a cancelled due journal to be non-vacuous.** A
date-passed lapse cannot fall inside a *forward* window by construction — the
window starts today — so a test that only seeded a past-due task would prove the
window arithmetic and nothing about the lapse rule. The fixture that makes it
bite is a not-done task, dated inside the window, whose due journal is a
cancelled event.
"""

from __future__ import annotations

import datetime

import pytest
from core_shared.models.tasks import (
    DEFAULT_UPCOMING_DAYS_AHEAD,
    MAX_UPCOMING_DAYS_AHEAD,
    Task,
    TaskContactRef,
    TaskJournalRef,
    TaskReadModel,
    TaskStatus,
    TaskValidationError,
    build_task_read_model,
    select_upcoming_tasks,
    upcoming_window,
)

from tests.unit.tasks.task_doubles import CREATING_JOURNAL_ID, USER_ID

pytestmark = pytest.mark.unit

TODAY = datetime.date(2026, 8, 11)


def make_model(
    task_id: int,
    *,
    due_date: datetime.date,
    status: TaskStatus = TaskStatus.NOT_DONE,
    cancelled: bool = False,
    today: datetime.date = TODAY,
) -> TaskReadModel:
    """A read model built the way the service builds one.

    Through ``build_task_read_model`` rather than by constructing a
    ``TaskReadModel`` directly, so ``lapse_reason`` is *derived* here exactly as
    it is in production. A hand-set reason would let these tests agree with a
    selection rule that had stopped agreeing with the lapse rule.
    """
    due_journal = TaskJournalRef(
        id=900 + task_id, title=f"journal {task_id}", date=due_date, cancelled=cancelled
    )
    return build_task_read_model(
        task=Task(
            id=task_id,
            user_id=USER_ID,
            text=f"task {task_id}",
            creating_journal_id=CREATING_JOURNAL_ID,
            due_journal_id=due_journal.id,
            status=status,
        ),
        creating_journal=TaskJournalRef(
            id=CREATING_JOURNAL_ID,
            title="where it arose",
            date=TODAY - datetime.timedelta(days=30),
            cancelled=False,
        ),
        due_journal=due_journal,
        intermediate_journals=[],
        contacts=[TaskContactRef(id=5, display_name="Sarah", photo_url=None)],
        today=today,
    )


def selected_ids(
    models: list[TaskReadModel], *, days_ahead: int = DEFAULT_UPCOMING_DAYS_AHEAD
) -> list[int | None]:
    """The task ids the rule keeps, in the order it keeps them.

    ``int | None`` because ``Task.id`` is optional on the entity — every model
    here is persisted, but narrowing it in the helper would hide an unpersisted
    one behind an assertion rather than showing it in the result.
    """
    window = upcoming_window(TODAY, days_ahead)
    return [model.task.id for model in select_upcoming_tasks(models, window).tasks]


class TestWindowArithmetic:
    """Where the window starts and ends."""

    def test_default_window_is_seven_days_ahead(self) -> None:
        """The specification's default: today through today + 7, inclusive."""
        window = upcoming_window(TODAY)

        assert window.days_ahead == DEFAULT_UPCOMING_DAYS_AHEAD == 7
        assert window.first_day == TODAY
        assert window.last_day == datetime.date(2026, 8, 18)

    def test_window_starts_today_not_tomorrow(self) -> None:
        """Today is in the window.

        Unlike the *future-dated* invariant on a due journal, which excludes
        today deliberately. The two rules ask different questions — "may this
        become a deadline" versus "is this deadline coming up" — and a task
        created yesterday for today is precisely what the dashboard exists to
        surface.
        """
        assert upcoming_window(TODAY).contains(TODAY)

    def test_zero_days_ahead_is_today_only(self) -> None:
        """A window of zero days is a single day, not an empty one."""
        window = upcoming_window(TODAY, 0)

        assert window.first_day == window.last_day == TODAY
        assert window.contains(TODAY)
        assert not window.contains(TODAY + datetime.timedelta(days=1))

    @pytest.mark.parametrize("days_ahead", [1, 7, 30, MAX_UPCOMING_DAYS_AHEAD])
    def test_last_day_is_today_plus_days_ahead(self, days_ahead: int) -> None:
        """The window's far edge is exactly ``days_ahead`` days out."""
        window = upcoming_window(TODAY, days_ahead)

        assert window.last_day == TODAY + datetime.timedelta(days=days_ahead)
        assert window.contains(window.last_day)

    def test_rejects_a_negative_window(self) -> None:
        """A backwards window is not a small window; it is a bad request."""
        with pytest.raises(TaskValidationError) as exc_info:
            upcoming_window(TODAY, -1)

        assert exc_info.value.field == "days_ahead"

    def test_rejects_a_window_beyond_the_maximum(self) -> None:
        """The bound exists so a caller cannot ask for every task ever.

        There is deliberately no unbounded task list in this product, and an
        arbitrarily large window would be one through the back door.
        """
        with pytest.raises(TaskValidationError) as exc_info:
            upcoming_window(TODAY, MAX_UPCOMING_DAYS_AHEAD + 1)

        assert exc_info.value.field == "days_ahead"


class TestBoundaryDays:
    """Both edges, from both sides."""

    def test_a_task_due_on_the_last_day_is_included(self) -> None:
        """ "Inclusive" means the boundary day itself, which is the off-by-one."""
        boundary = TODAY + datetime.timedelta(days=DEFAULT_UPCOMING_DAYS_AHEAD)

        assert selected_ids([make_model(1, due_date=boundary)]) == [1]

    def test_a_task_due_the_day_after_the_window_is_excluded(self) -> None:
        """One day further out and it is somebody else's problem."""
        beyond = TODAY + datetime.timedelta(days=DEFAULT_UPCOMING_DAYS_AHEAD + 1)

        assert selected_ids([make_model(1, due_date=beyond)]) == []

    def test_a_task_due_today_is_included(self) -> None:
        """The near edge, which the window shares with the anchor day."""
        assert selected_ids([make_model(1, due_date=TODAY)]) == [1]

    def test_a_task_due_yesterday_is_excluded(self) -> None:
        """Before the window. It is also lapsed, which is why the next class
        exists: this alone would not prove the lapse rule is consulted."""
        yesterday = TODAY - datetime.timedelta(days=1)

        assert selected_ids([make_model(1, due_date=yesterday)]) == []


class TestExclusions:
    """Done, cancelled and lapsed tasks never reach the dashboard."""

    def test_a_done_task_in_the_window_is_excluded(self) -> None:
        """The section shows what is outstanding, not what was achieved."""
        models = [
            make_model(1, due_date=TODAY, status=TaskStatus.DONE),
            make_model(2, due_date=TODAY),
        ]

        assert selected_ids(models) == [2]

    def test_a_cancelled_task_in_the_window_is_excluded(self) -> None:
        """Cancelling is the ordinary way to retire a commitment."""
        models = [
            make_model(1, due_date=TODAY, status=TaskStatus.CANCELLED),
            make_model(2, due_date=TODAY),
        ]

        assert selected_ids(models) == [2]

    def test_a_task_whose_due_journal_was_cancelled_is_excluded(self) -> None:
        """**The fixture that makes the lapsed exclusion non-vacuous.**

        Not done, dated squarely inside the window, and lapsed only because the
        meeting it was due at was called off. A rule that filtered on status and
        dates alone — and never consulted the lapse — would return this task,
        and every other exclusion test here would still pass.
        """
        lapsed = make_model(
            1, due_date=TODAY + datetime.timedelta(days=2), cancelled=True
        )

        assert lapsed.lapsed is True
        assert selected_ids([lapsed, make_model(2, due_date=TODAY)]) == [2]

    def test_a_cancelled_journal_outside_the_window_changes_nothing(self) -> None:
        """The two exclusions compose rather than cancelling out."""
        beyond = TODAY + datetime.timedelta(days=DEFAULT_UPCOMING_DAYS_AHEAD + 1)

        assert selected_ids([make_model(1, due_date=beyond, cancelled=True)]) == []

    def test_an_empty_input_is_an_empty_window_not_an_error(self) -> None:
        """Nothing due this week is a good outcome, not a failure."""
        assert selected_ids([]) == []


class TestOrdering:
    """Soonest first, with a tie-break that cannot itself tie."""

    def test_ordered_by_due_date_soonest_first(self) -> None:
        """The specification's order, whatever order the models arrived in."""
        models = [
            make_model(1, due_date=TODAY + datetime.timedelta(days=5)),
            make_model(2, due_date=TODAY),
            make_model(3, due_date=TODAY + datetime.timedelta(days=2)),
        ]

        assert selected_ids(models) == [2, 3, 1]

    def test_same_day_tasks_are_ordered_by_id(self) -> None:
        """The tie-break, and a **total** order rather than a partial one.

        Several tasks due on the same day is the common case for a dashboard —
        a day's journal usually holds all of them — so without this the same
        request could answer in a different order between runs.
        """
        models = [
            make_model(9, due_date=TODAY),
            make_model(2, due_date=TODAY),
            make_model(5, due_date=TODAY),
        ]

        assert selected_ids(models) == [2, 5, 9]

    def test_the_date_wins_over_the_id(self) -> None:
        """A later-created task due sooner still comes first."""
        models = [
            make_model(1, due_date=TODAY + datetime.timedelta(days=3)),
            make_model(2, due_date=TODAY),
        ]

        assert selected_ids(models) == [2, 1]

    def test_the_models_are_handed_back_unchanged(self) -> None:
        """Pure: the same objects come back, so no verdict is recomputed here.

        The lapse verdict and the contacts were decided by the assembler. A
        selection rule that rebuilt a model could disagree with it.
        """
        model = make_model(1, due_date=TODAY)

        selected = select_upcoming_tasks([model], upcoming_window(TODAY))

        assert selected.tasks[0] is model
        assert selected.tasks[0].contacts[0].display_name == "Sarah"


class TestTheAnswerCarriesItsQuestion:
    """The window travels with the tasks, empty windows included."""

    def test_the_window_asked_for_comes_back(self) -> None:
        """A surface renders "the next N days", so it must be told which N."""
        window = upcoming_window(TODAY, 3)

        selected = select_upcoming_tasks([make_model(1, due_date=TODAY)], window)

        assert selected.window is window

    def test_an_empty_window_still_describes_itself(self) -> None:
        """The case a caller could not reconstruct from the rows.

        With no tasks there is nothing to derive a window from, and "nothing due
        between today and Tuesday" is exactly what the empty state says.
        """
        selected = select_upcoming_tasks([], upcoming_window(TODAY))

        assert selected.tasks == ()
        assert selected.total == 0
        assert selected.window.last_day == datetime.date(2026, 8, 18)

    def test_total_counts_the_survivors_not_the_candidates(self) -> None:
        """The count the show-more names is of what is shown, not what was read."""
        models = [
            make_model(1, due_date=TODAY),
            make_model(2, due_date=TODAY, status=TaskStatus.DONE),
            make_model(3, due_date=TODAY, cancelled=True),
        ]

        selected = select_upcoming_tasks(models, upcoming_window(TODAY))

        assert selected.total == 1 == len(selected.tasks)

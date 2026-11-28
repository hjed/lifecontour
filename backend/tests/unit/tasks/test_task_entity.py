"""Unit tests for the Task domain entity.

Construction-time validation covers what the entity alone can know: the owner,
the text, the presence of both journal anchors, and the status type. Whether the
due journal exists, belongs to the user, or is future-dated needs journal data
and a timezone, so those invariants live in the service layer.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from core_shared.models.tasks import (
    IntervalRecurrence,
    NoDateRecurrence,
    RecurrenceInterval,
    RecurrenceIntervalUnit,
    SeriesRecurrence,
    Task,
    TaskAnchorMissingError,
    TaskDomainError,
    TaskIcon,
    TaskJournalAnchor,
    TaskRecurrence,
    TaskStatus,
    TaskValidationError,
)

USER_ID = "test-user-123"
CREATING_JOURNAL_ID = 11
DUE_JOURNAL_ID = 22


def _task(**overrides: Any) -> Task:
    """Build a valid task, overriding individual fields per test."""
    kwargs: dict[str, Any] = {
        "user_id": USER_ID,
        "text": "Print out the permit before the meeting",
        "creating_journal_id": CREATING_JOURNAL_ID,
        "due_journal_id": DUE_JOURNAL_ID,
    }
    kwargs.update(overrides)
    return Task(**kwargs)


@pytest.mark.unit
class TestTaskConstruction:
    """Test valid Task construction."""

    def test_create_valid_task(self):
        """A task carries its owner, text and both journal anchors."""
        task = _task()

        assert task.user_id == USER_ID
        assert task.text == "Print out the permit before the meeting"
        assert task.creating_journal_id == CREATING_JOURNAL_ID
        assert task.due_journal_id == DUE_JOURNAL_ID
        assert task.id is None
        assert task.created_at is None
        assert task.updated_at is None

    def test_status_defaults_to_not_done(self):
        """Not done is the default on creation."""
        assert _task().status == TaskStatus.NOT_DONE

    def test_status_can_be_set_explicitly(self):
        """A persisted task can be rehydrated in any of the three statuses."""
        for status in TaskStatus:
            assert _task(status=status).status == status

    def test_creating_and_due_journal_may_be_the_same(self):
        """Core invariant 6 — the two anchors may point at one journal."""
        task = _task(
            creating_journal_id=CREATING_JOURNAL_ID,
            due_journal_id=CREATING_JOURNAL_ID,
        )

        assert task.creating_journal_id == task.due_journal_id

    def test_persisted_task_carries_id_and_timestamps(self):
        """A task read back from the database carries its id and timestamps."""
        now = datetime(2026, 7, 31, 9, 0, 0, tzinfo=UTC)

        task = _task(id=7, created_at=now, updated_at=now)

        assert task.id == 7
        assert task.created_at == now
        assert task.updated_at == now


@pytest.mark.unit
class TestTaskUserIdValidation:
    """Test user_id validation."""

    def test_empty_user_id_rejected(self):
        """A task must have an owner."""
        with pytest.raises(TaskValidationError, match="user_id"):
            _task(user_id="")

    def test_whitespace_user_id_rejected(self):
        """Whitespace is not an owner."""
        with pytest.raises(TaskValidationError, match="user_id"):
            _task(user_id="   ")


@pytest.mark.unit
class TestTaskTextValidation:
    """Test text validation."""

    def test_empty_text_rejected(self):
        """A task without text describes nothing."""
        with pytest.raises(TaskValidationError, match="text"):
            _task(text="")

    def test_whitespace_text_rejected(self):
        """Whitespace-only text is empty text."""
        with pytest.raises(TaskValidationError, match="text"):
            _task(text="   \n\t  ")

    def test_long_text_accepted(self):
        """Text is unbounded — the column is TEXT (open decision 3)."""
        long_text = "x" * 5000

        assert _task(text=long_text).text == long_text


@pytest.mark.unit
class TestTaskAnchorValidation:
    """Test that both journal anchors are present.

    Core invariants 1-3: a task must have a creating journal and a due journal,
    and can never exist with only one of them at any point in its life.
    """

    def test_missing_creating_journal_rejected(self):
        """Invariant 1 — the creating journal is mandatory."""
        with pytest.raises(TaskValidationError, match="creating_journal_id"):
            _task(creating_journal_id=None)

    def test_missing_due_journal_rejected(self):
        """Invariant 2 — the due journal is mandatory."""
        with pytest.raises(TaskValidationError, match="due_journal_id"):
            _task(due_journal_id=None)

    @pytest.mark.parametrize("invalid_id", [0, -1])
    def test_non_positive_creating_journal_rejected(self, invalid_id):
        """A journal id is a positive integer."""
        with pytest.raises(TaskValidationError, match="creating_journal_id"):
            _task(creating_journal_id=invalid_id)

    @pytest.mark.parametrize("invalid_id", [0, -1])
    def test_non_positive_due_journal_rejected(self, invalid_id):
        """A journal id is a positive integer."""
        with pytest.raises(TaskValidationError, match="due_journal_id"):
            _task(due_journal_id=invalid_id)


@pytest.mark.unit
class TestTaskStatusValidation:
    """Test status validation."""

    def test_non_enum_status_rejected(self):
        """A raw string is not a status — the enum is the contract."""
        with pytest.raises(TaskValidationError, match="status"):
            _task(status="done")

    def test_unknown_status_rejected(self):
        """A status outside the three-value enum is rejected."""
        with pytest.raises(TaskValidationError, match="status"):
            _task(status="in_progress")


@pytest.mark.unit
class TestTaskValidationErrorShape:
    """Test that validation errors are actionable."""

    def test_error_exposes_field_and_status_code(self):
        """Errors name the offending field and map to a 400."""
        with pytest.raises(TaskValidationError) as exc_info:
            _task(text="")

        assert exc_info.value.field == "text"
        assert exc_info.value.status_code == 400


# --- Tasks on a list ---------------------------------------------------------
#
# Spec *Core invariants* 1-5, mirroring migration 0146's CHECKs. Every test
# above is about journal-only tasks and is deliberately untouched: those rules
# do not change when a task can also live on a list.

LIST_ID = 5


def _list_task(**overrides: Any) -> Task:
    """Build a valid list task with no journal, overriding fields per test."""
    kwargs: dict[str, Any] = {
        "user_id": USER_ID,
        "text": "Pack the head torch",
        "task_list_id": LIST_ID,
        "position": 0,
    }
    kwargs.update(overrides)
    return Task(**kwargs)


@pytest.mark.unit
class TestListTaskShapes:
    """Every shape a list task may take (invariants 1, 4 and 5)."""

    def test_a_list_task_needs_no_journal(self) -> None:
        """Invariant 1 — a list is enough; neither anchor is required."""
        task = _list_task()

        assert task.task_list_id == LIST_ID
        assert task.creating_journal_id is None
        assert task.due_journal_id is None
        assert task.due_date is None

    def test_a_list_task_may_have_only_a_creating_journal(self) -> None:
        """A list task may remember where it arose without being due anywhere."""
        task = _list_task(creating_journal_id=CREATING_JOURNAL_ID)

        assert task.creating_journal_id == CREATING_JOURNAL_ID
        assert task.due_journal_id is None

    def test_a_list_task_may_have_only_a_due_journal(self) -> None:
        """Invariant 4 — a due journal alone dates a list task."""
        task = _list_task(due_journal_id=DUE_JOURNAL_ID)

        assert task.due_journal_id == DUE_JOURNAL_ID
        assert task.creating_journal_id is None

    def test_a_list_task_may_hold_both_journals(self) -> None:
        """A journal-only task added to a list keeps both of its journals."""
        task = _list_task(
            creating_journal_id=CREATING_JOURNAL_ID, due_journal_id=DUE_JOURNAL_ID
        )

        assert task.creating_journal_id == CREATING_JOURNAL_ID
        assert task.due_journal_id == DUE_JOURNAL_ID

    def test_a_list_task_may_have_a_due_date(self) -> None:
        """Invariant 5 — a due date is allowed on a list task."""
        task = _list_task(due_date=date(2026, 12, 1))

        assert task.due_date == date(2026, 12, 1)

    def test_a_list_task_may_have_a_creating_journal_and_a_due_date(self) -> None:
        """Invariant 4 forbids a due date beside a *due* journal, not a creating one."""
        task = _list_task(
            creating_journal_id=CREATING_JOURNAL_ID, due_date=date(2026, 12, 1)
        )

        assert task.creating_journal_id == CREATING_JOURNAL_ID
        assert task.due_date == date(2026, 12, 1)

    def test_an_unplaced_list_task_has_no_position_yet(self) -> None:
        """Like ``TaskList.position``, the repository places a new task on insert."""
        assert _list_task(position=None).position is None

    def test_a_list_task_may_sit_at_the_top(self) -> None:
        """Position 0 is the top of the list."""
        assert _list_task(position=0).position == 0

    def test_a_list_task_may_be_flagged_with_an_icon(self) -> None:
        """Flag and icon apply to list tasks."""
        task = _list_task(flagged=True, icon=TaskIcon.STAR)

        assert task.flagged is True
        assert task.icon is TaskIcon.STAR

    def test_a_journal_only_task_may_be_flagged_with_an_icon(self) -> None:
        """Flag and icon apply to every task, journal-only ones included."""
        task = _task(flagged=True, icon=TaskIcon.STAR)

        assert task.task_list_id is None
        assert task.flagged is True
        assert task.icon is TaskIcon.STAR

    def test_a_journal_only_task_built_as_today_has_list_defaults(self) -> None:
        """Existing construction needs no new arguments."""
        task = _task()

        assert task.task_list_id is None
        assert task.position is None
        assert task.due_date is None
        assert task.flagged is False
        assert task.icon is None


@pytest.mark.unit
class TestListTaskRefusals:
    """Each shape the invariants refuse, naming the field it is about."""

    def test_no_list_and_no_journal_is_refused(self) -> None:
        """Invariant 1 — a task with neither a list nor a due journal."""
        with pytest.raises(TaskValidationError) as exc_info:
            Task(user_id=USER_ID, text="Somewhere, someday")

        # The creating anchor is validated first, so it is the one named.
        assert exc_info.value.field == "creating_journal_id"

    def test_no_list_and_only_a_due_journal_is_refused(self) -> None:
        """Invariant 2 — a journal-only task still needs its creating journal."""
        with pytest.raises(TaskValidationError) as exc_info:
            Task(user_id=USER_ID, text="Bring chairs", due_journal_id=DUE_JOURNAL_ID)

        assert exc_info.value.field == "creating_journal_id"

    def test_no_list_and_only_a_creating_journal_is_refused(self) -> None:
        """Invariant 2 — a journal-only task still needs its due journal."""
        with pytest.raises(TaskValidationError) as exc_info:
            Task(
                user_id=USER_ID,
                text="Bring chairs",
                creating_journal_id=CREATING_JOURNAL_ID,
            )

        assert exc_info.value.field == "due_journal_id"

    def test_a_due_date_beside_a_due_journal_is_refused(self) -> None:
        """Invariant 4 — a date comes from one place only."""
        with pytest.raises(TaskValidationError) as exc_info:
            _list_task(due_journal_id=DUE_JOURNAL_ID, due_date=date(2026, 12, 1))

        assert exc_info.value.field == "due_date"

    def test_a_due_date_off_a_list_is_refused(self) -> None:
        """Invariant 5 — journal-only tasks never carry a bare date.

        A journal-only task always has a due journal, so invariant 4 would
        refuse this too; the test pins that the refusal names the due date.
        """
        with pytest.raises(TaskValidationError) as exc_info:
            _task(due_date=date(2026, 12, 1))

        assert exc_info.value.field == "due_date"

    def test_a_datetime_is_not_a_due_date(self) -> None:
        """A due date is a calendar day with no time of day.

        ``datetime`` subclasses ``date``, so the type alone would let one in.
        """
        with pytest.raises(TaskValidationError) as exc_info:
            _list_task(due_date=datetime(2026, 12, 1, 9, 0, tzinfo=UTC))

        assert exc_info.value.field == "due_date"

    def test_a_position_off_a_list_is_refused(self) -> None:
        """A task has a position only on a list (``ck_tasks_position_only_on_list``)."""
        with pytest.raises(TaskValidationError) as exc_info:
            _task(position=0)

        assert exc_info.value.field == "position"

    def test_a_negative_position_is_refused(self) -> None:
        """Positions start at 0 (``ck_tasks_position_non_negative``)."""
        with pytest.raises(TaskValidationError) as exc_info:
            _list_task(position=-1)

        assert exc_info.value.field == "position"

    @pytest.mark.parametrize("invalid_id", [0, -1])
    def test_a_non_positive_list_id_is_refused(self, invalid_id: int) -> None:
        """A list id is a positive integer."""
        with pytest.raises(TaskValidationError) as exc_info:
            _list_task(task_list_id=invalid_id)

        assert exc_info.value.field == "task_list_id"

    @pytest.mark.parametrize("invalid_id", [0, -1])
    def test_a_list_tasks_anchor_ids_are_still_positive(self, invalid_id: int) -> None:
        """An optional anchor, when set, is still a real journal id."""
        with pytest.raises(TaskValidationError) as exc_info:
            _list_task(due_journal_id=invalid_id)

        assert exc_info.value.field == "due_journal_id"

    def test_a_bare_string_icon_is_refused(self) -> None:
        """Surfaces parse into ``TaskIcon`` first, as for lists."""
        with pytest.raises(TaskValidationError) as exc_info:
            _task(icon="star")

        assert exc_info.value.field == "icon"

    def test_a_non_bool_flag_is_refused(self) -> None:
        """The flag is on or off; a truthy value is not a flag."""
        with pytest.raises(TaskValidationError) as exc_info:
            _task(flagged=1)

        assert exc_info.value.field == "flagged"

    def test_replace_revalidates(self) -> None:
        """A copy with a new shape passes the same rules as a new task."""
        with pytest.raises(TaskValidationError) as exc_info:
            replace(_task(), due_date=date(2026, 12, 1))

        assert exc_info.value.field == "due_date"

    def test_fields_are_keyword_only(self) -> None:
        """Positional construction would break silently as columns are added."""
        with pytest.raises(TypeError):
            Task(USER_ID, "text", CREATING_JOURNAL_ID, DUE_JOURNAL_ID)  # type: ignore[call-arg]


@pytest.mark.unit
class TestRequireAnchor:
    """The narrowing used where an existing contract still needs a journal."""

    def test_it_returns_each_anchor(self) -> None:
        """A journal-only task always has both."""
        task = _task()

        assert task.require_anchor("creating") == CREATING_JOURNAL_ID
        assert task.require_anchor("due") == DUE_JOURNAL_ID

    @pytest.mark.parametrize("anchor", ["creating", "due"])
    def test_a_missing_anchor_raises_naming_the_task_and_anchor(
        self, anchor: TaskJournalAnchor
    ) -> None:
        """An internal invariant breach, not a client refusal."""
        task = _list_task(id=42)

        with pytest.raises(TaskAnchorMissingError) as exc_info:
            task.require_anchor(anchor)

        assert exc_info.value.task_id == 42
        assert exc_info.value.anchor == anchor
        assert not isinstance(exc_info.value, TaskDomainError)


_SERIES_RECURRENCE = SeriesRecurrence(series_id=UUID(int=7))
_RECURRENCES: list[TaskRecurrence] = [
    NoDateRecurrence(),
    IntervalRecurrence(
        interval=RecurrenceInterval(count=2, unit=RecurrenceIntervalUnit.WEEK)
    ),
    _SERIES_RECURRENCE,
]


@pytest.mark.unit
class TestRecurrence:
    """Invariant 6, its list half: only a list task recurs."""

    def test_a_task_does_not_recur_by_default(self) -> None:
        task = _list_task()

        assert task.recurrence is None
        assert task.recurrence_of_task_id is None

    @pytest.mark.parametrize("recurrence", _RECURRENCES)
    def test_a_list_task_accepts_each_mode(self, recurrence: TaskRecurrence) -> None:
        assert _list_task(recurrence=recurrence).recurrence == recurrence

    def test_a_journal_only_task_cannot_recur(self) -> None:
        with pytest.raises(TaskValidationError) as exc_info:
            _task(recurrence=NoDateRecurrence())

        assert exc_info.value.field == "recurrence"

    def test_a_bare_mode_string_is_refused(self) -> None:
        """Surfaces parse into a value object first, as they do for the icon."""
        with pytest.raises(TaskValidationError) as exc_info:
            _list_task(recurrence="no_date")

        assert exc_info.value.field == "recurrence"

    def test_leaving_the_list_while_recurring_is_refused(self) -> None:
        """``replace`` re-validates, so a recurring task cannot drop its list."""
        task = _list_task(
            recurrence=NoDateRecurrence(),
            creating_journal_id=CREATING_JOURNAL_ID,
            due_journal_id=DUE_JOURNAL_ID,
        )

        with pytest.raises(TaskValidationError) as exc_info:
            replace(task, task_list_id=None, position=None)

        assert exc_info.value.field == "recurrence"


@pytest.mark.unit
class TestRecurrenceOf:
    """The task a copy was made from: a past, not a setting."""

    def test_a_copy_records_its_original(self) -> None:
        assert _list_task(recurrence_of_task_id=41).recurrence_of_task_id == 41

    def test_a_journal_only_task_may_record_its_original(self) -> None:
        """Not a setting, so it is not limited to list tasks."""
        assert _task(recurrence_of_task_id=41).recurrence_of_task_id == 41

    @pytest.mark.parametrize("invalid_id", [0, -1])
    def test_a_non_positive_original_is_refused(self, invalid_id: int) -> None:
        with pytest.raises(TaskValidationError) as exc_info:
            _list_task(recurrence_of_task_id=invalid_id)

        assert exc_info.value.field == "recurrence_of_task_id"

    def test_a_task_is_never_a_copy_of_itself(self) -> None:
        with pytest.raises(TaskValidationError) as exc_info:
            _list_task(id=41, recurrence_of_task_id=41)

        assert exc_info.value.field == "recurrence_of_task_id"

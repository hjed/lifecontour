"""Unit tests for the Task domain entity.

Construction-time validation covers what the entity alone can know: the owner,
the text, the presence of both journal anchors, and the status type. Whether the
due journal exists, belongs to the user, or is future-dated needs journal data
and a timezone, so those invariants live in the service layer.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.tasks import Task, TaskStatus, TaskValidationError

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

"""Unit tests for the task row -> entity mapper.

``SqlTaskRepository`` declares its column list once and maps rows through a
single ``_row_to_task`` helper, rather than repeating the mapping per query —
the ``_row_to_tag`` lesson from ITER17-001 Phase 1. That helper is the only
piece of pure logic in the repository, so it is unit-tested here against a row
stub; everything else needs a real database and lives in the integration suite.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from core_shared.models.tasks import Task, TaskStatus

from app.core.tasks.adapters.sql.task_repository import _TASK_COLUMN_NAMES, _row_to_task


def _row(**overrides: object) -> SimpleNamespace:
    """Build a stub row carrying exactly the declared task columns."""
    row = {
        "id": 7,
        "user_id": "test-user-123",
        "text": "print out the permit before the meeting",
        "status": "not_done",
        "creating_journal_id": 11,
        "due_journal_id": 12,
        "created_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 2, 10, 30, tzinfo=UTC),
    }
    row.update(overrides)
    return SimpleNamespace(**row)


@pytest.mark.unit
class TestRowToTask:
    """Test the single row-mapping helper."""

    def test_maps_every_column_onto_the_entity(self):
        """Each declared column lands on the matching entity attribute."""
        task = _row_to_task(_row())

        assert isinstance(task, Task)
        assert task.id == 7
        assert task.user_id == "test-user-123"
        assert task.text == "print out the permit before the meeting"
        assert task.creating_journal_id == 11
        assert task.due_journal_id == 12
        assert task.created_at == datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
        assert task.updated_at == datetime(2026, 8, 2, 10, 30, tzinfo=UTC)

    @pytest.mark.parametrize("status", list(TaskStatus))
    def test_maps_stored_status_string_back_to_the_enum(self, status: TaskStatus):
        """The stored string becomes the domain enum, never a bare string."""
        task = _row_to_task(_row(status=status.value))

        assert task.status is status

    def test_creating_and_due_may_be_the_same_journal(self):
        """Invariant 6 holds at the mapping layer as well as in the schema."""
        task = _row_to_task(_row(creating_journal_id=11, due_journal_id=11))

        assert task.creating_journal_id == 11
        assert task.due_journal_id == 11

    def test_unknown_status_raises(self):
        """A status the enum does not know is a fault, not a silent bad entity."""
        with pytest.raises(ValueError):
            _row_to_task(_row(status="in_progress"))

    def test_mapper_reads_exactly_the_declared_columns(self):
        """The column tuple and the mapper cannot drift apart.

        A row carrying only the declared columns must map cleanly, which fails
        the moment the mapper reaches for a column the query does not select.
        """
        declared_only = SimpleNamespace(
            **{name: getattr(_row(), name) for name in _TASK_COLUMN_NAMES}
        )

        assert _row_to_task(declared_only).id == 7

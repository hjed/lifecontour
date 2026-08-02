"""Unit tests for the TaskStatus enum.

A task has exactly three statuses — not done (the default), done, and cancelled.
The values are the ones the ``ck_tasks_status`` CHECK constraint accepts, so the
enum and the column can never drift apart silently.
"""

import pytest
from core_shared.models.tasks import TaskStatus


@pytest.mark.unit
class TestTaskStatus:
    """Test TaskStatus enum."""

    def test_enum_has_exactly_three_values(self):
        """The specification allows three statuses and no more."""
        assert len(TaskStatus) == 3

    def test_enum_values(self):
        """Members carry the database's string values."""
        assert TaskStatus.NOT_DONE.value == "not_done"
        assert TaskStatus.DONE.value == "done"
        assert TaskStatus.CANCELLED.value == "cancelled"

    def test_str_representation(self):
        """String representation returns the value, for SQL binding."""
        assert str(TaskStatus.NOT_DONE) == "not_done"
        assert str(TaskStatus.DONE) == "done"
        assert str(TaskStatus.CANCELLED) == "cancelled"

    def test_construction_from_string(self):
        """Constructing from a stored string value round-trips."""
        assert TaskStatus("not_done") == TaskStatus.NOT_DONE
        assert TaskStatus("done") == TaskStatus.DONE
        assert TaskStatus("cancelled") == TaskStatus.CANCELLED

    def test_invalid_value_raises(self):
        """An unknown or wrongly-cased value raises ValueError."""
        with pytest.raises(ValueError):
            TaskStatus("in_progress")

        with pytest.raises(ValueError):
            TaskStatus("NOT_DONE")  # Case-sensitive

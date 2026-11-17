"""Unit tests for the TaskList domain entity.

Construction-time validation covers what the entity alone can know: the owner,
the name, the icon and the position. Ownership of the list and whether it may be
written while archived need the repository and the acting user, so those rules
live in the service layer.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.tasks import (
    MAX_TASK_LIST_NAME_LENGTH,
    TaskIcon,
    TaskList,
    TaskListValidationError,
    TaskValidationError,
)

USER_ID = "test-user-123"
ARCHIVED_AT = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)


def _task_list(**overrides: Any) -> TaskList:
    """Build a valid list, overriding individual fields per test."""
    kwargs: dict[str, Any] = {"user_id": USER_ID, "name": "Packing"}
    kwargs.update(overrides)
    return TaskList(**kwargs)


@pytest.mark.unit
class TestTaskListConstruction:
    """Valid TaskList construction."""

    def test_a_list_needs_only_an_owner_and_a_name(self) -> None:
        task_list = _task_list()

        assert task_list.user_id == USER_ID
        assert task_list.name == "Packing"
        assert task_list.icon is None
        assert task_list.position is None
        assert task_list.archived_at is None
        assert task_list.id is None
        assert task_list.created_at is None
        assert task_list.updated_at is None

    def test_a_list_carries_its_icon_position_and_archive_time(self) -> None:
        task_list = _task_list(
            icon=TaskIcon.LUGGAGE, position=3, archived_at=ARCHIVED_AT, id=7
        )

        assert task_list.icon is TaskIcon.LUGGAGE
        assert task_list.position == 3
        assert task_list.archived_at == ARCHIVED_AT
        assert task_list.id == 7

    def test_position_zero_is_the_top(self) -> None:
        assert _task_list(position=0).position == 0

    def test_a_name_at_the_length_bound_is_accepted(self) -> None:
        name = "x" * MAX_TASK_LIST_NAME_LENGTH

        assert _task_list(name=name).name == name

    def test_fields_are_keyword_only(self) -> None:
        """Later phases add fields; positional construction would break then."""
        with pytest.raises(TypeError):
            TaskList(USER_ID, "Packing")  # type: ignore[call-arg]


@pytest.mark.unit
class TestTaskListArchivedState:
    """Archived is derived from the archive time, never stored separately."""

    def test_a_list_without_an_archive_time_is_not_archived(self) -> None:
        assert _task_list().is_archived is False

    def test_a_list_with_an_archive_time_is_archived(self) -> None:
        assert _task_list(archived_at=ARCHIVED_AT).is_archived is True


@pytest.mark.unit
class TestTaskListValidation:
    """Each refusal names the field it is about."""

    @pytest.mark.parametrize("user_id", ["", "   "])
    def test_an_owner_is_required(self, user_id: str) -> None:
        with pytest.raises(TaskListValidationError) as exc_info:
            _task_list(user_id=user_id)

        assert exc_info.value.field == "user_id"

    @pytest.mark.parametrize("name", ["", "   ", "\t\n"])
    def test_a_name_is_required(self, name: str) -> None:
        with pytest.raises(TaskListValidationError) as exc_info:
            _task_list(name=name)

        assert exc_info.value.field == "name"

    def test_a_name_over_the_length_bound_is_refused(self) -> None:
        with pytest.raises(TaskListValidationError) as exc_info:
            _task_list(name="x" * (MAX_TASK_LIST_NAME_LENGTH + 1))

        assert exc_info.value.field == "name"

    @pytest.mark.parametrize("icon", ["plane", "not-an-icon"])
    def test_an_icon_must_come_from_the_fixed_set(self, icon: str) -> None:
        """A bare string is refused even when it spells a real key: the
        surfaces parse into ``TaskIcon`` before the entity sees it."""
        with pytest.raises(TaskListValidationError) as exc_info:
            _task_list(icon=icon)

        assert exc_info.value.field == "icon"

    def test_a_negative_position_is_refused(self) -> None:
        with pytest.raises(TaskListValidationError) as exc_info:
            _task_list(position=-1)

        assert exc_info.value.field == "position"


@pytest.mark.unit
class TestTaskListValidationError:
    """List refusals reach the surfaces exactly as task refusals do."""

    def test_is_a_task_validation_error(self) -> None:
        with pytest.raises(TaskValidationError):
            _task_list(name="")

    def test_carries_a_400_and_the_field_as_data(self) -> None:
        with pytest.raises(TaskListValidationError) as exc_info:
            _task_list(name="")

        assert exc_info.value.status_code == 400
        assert exc_info.value.error_meta() == {"field": "name"}

"""Unit tests for the body of ``POST /api/tasks/{task_id}/move``.

A move names one thing — the list the task should be on — so the body is one
required attribute under an operation type, with extras forbidden at every
level. ``task_list_id`` is a strict integer: a string or a boolean is a client
bug, not a list id, and ``null`` is refused because leaving a list is not a
move.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.api.common.identifiers import INT32_MAX
from app.api.tasks.schemas import TASK_MOVE_RESOURCE_TYPE, TaskMoveRequest

pytestmark = pytest.mark.unit


def _body(**attributes: Any) -> dict[str, Any]:
    return {
        "data": {
            "type": "task-moves",
            "attributes": {"task_list_id": 5, **attributes},
        }
    }


class TestTaskMoveRequest:
    def test_a_list_id_is_accepted(self) -> None:
        request = TaskMoveRequest.model_validate(_body())

        assert request.data.attributes.task_list_id == 5
        assert request.data.type == TASK_MOVE_RESOURCE_TYPE == "task-moves"

    def test_the_type_names_the_operation(self) -> None:
        body = _body()
        body["data"]["type"] = "tasks"

        with pytest.raises(ValidationError):
            TaskMoveRequest.model_validate(body)

    def test_the_list_id_is_required(self) -> None:
        body = _body()
        del body["data"]["attributes"]["task_list_id"]

        with pytest.raises(ValidationError):
            TaskMoveRequest.model_validate(body)

    @pytest.mark.parametrize("value", [None, "5", True, 5.0, [5]])
    def test_only_a_json_integer_is_a_list_id(self, value: object) -> None:
        with pytest.raises(ValidationError):
            TaskMoveRequest.model_validate(_body(task_list_id=value))

    @pytest.mark.parametrize("value", [0, -1, INT32_MAX + 1])
    def test_the_id_is_bounded_to_what_a_column_can_hold(self, value: int) -> None:
        with pytest.raises(ValidationError):
            TaskMoveRequest.model_validate(_body(task_list_id=value))

    def test_the_largest_column_value_is_accepted(self) -> None:
        request = TaskMoveRequest.model_validate(_body(task_list_id=INT32_MAX))

        assert request.data.attributes.task_list_id == INT32_MAX

    def test_an_unknown_attribute_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            TaskMoveRequest.model_validate(_body(position=0))

    def test_unknown_members_are_refused_at_every_level(self) -> None:
        top = _body()
        top["meta"] = {}
        data = _body()
        data["data"]["id"] = "7"

        for body in (top, data):
            with pytest.raises(ValidationError):
                TaskMoveRequest.model_validate(body)

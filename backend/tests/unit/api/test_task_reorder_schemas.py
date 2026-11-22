"""Unit tests for the body of ``POST /api/tasks/{task_id}/reorder``.

The list page's single move names the open task the moved one should follow,
or ``null`` for the top. ``after_task_id`` is required: a body that leaves it
out is refused rather than read as "the top", so a client bug cannot quietly
send a task to the head of its list. Ids are strict JSON integers in the
database's range, as every other task id is.
"""

import pytest
from pydantic import ValidationError

from app.api.common.identifiers import INT32_MAX
from app.api.tasks.schemas import TaskReorderRequest

pytestmark = pytest.mark.unit


def _body(attributes: dict[str, object], **data: object) -> dict[str, object]:
    return {"data": {"type": "task-reorders", "attributes": attributes, **data}}


@pytest.mark.parametrize("after", [7, None, INT32_MAX], ids=["id", "top", "max"])
def test_an_anchor_or_null_is_accepted(after: int | None) -> None:
    request = TaskReorderRequest.model_validate(_body({"after_task_id": after}))

    assert request.data.attributes.after_task_id == after


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_body({}), id="missing-anchor"),
        pytest.param(_body({"after_task_id": True}), id="boolean"),
        pytest.param(_body({"after_task_id": "7"}), id="string"),
        pytest.param(_body({"after_task_id": 7.0}), id="float"),
        pytest.param(_body({"after_task_id": 0}), id="zero"),
        pytest.param(_body({"after_task_id": -1}), id="negative"),
        pytest.param(_body({"after_task_id": INT32_MAX + 1}), id="too-large"),
        pytest.param(_body({"after_task_id": 7, "index": 0}), id="extra-attribute"),
        pytest.param(
            {"data": {"type": "tasks", "attributes": {"after_task_id": 7}}},
            id="another-type",
        ),
        pytest.param(_body({"after_task_id": 7}, id="7"), id="unknown-data-member"),
    ],
)
def test_a_malformed_body_is_refused(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TaskReorderRequest.model_validate(body)

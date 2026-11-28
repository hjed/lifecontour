"""Unit tests for the journal association on the task list update body.

``associated_journal_id`` follows the icon's rule: ``null`` removes the
association and an absent field leaves it alone, so the two are told apart by
presence. The id is strict, as the task's ``due_journal_id`` is: a string or a
boolean is a client bug, and coercing one would associate a journal nobody
named.
"""

from typing import Any

import pytest
from core_shared.models.tasks import TaskList
from pydantic import ValidationError

from app.api.common.identifiers import INT32_MAX
from app.api.tasks.task_list_schemas import (
    TaskListResource,
    TaskListUpdateAttributes,
    to_task_list_resource,
)
from app.core.tasks.services.task_list_patch import TaskListPatch
from app.shared.patch import UNSET

pytestmark = pytest.mark.unit


class TestTheAssociationOnAnUpdate:
    def test_an_id_associates(self) -> None:
        body = TaskListUpdateAttributes.model_validate({"associated_journal_id": 31})

        assert body.to_patch() == TaskListPatch(associated_journal_id=31)

    def test_null_removes_and_is_a_change_on_its_own(self) -> None:
        body = TaskListUpdateAttributes.model_validate({"associated_journal_id": None})

        assert body.to_patch() == TaskListPatch(associated_journal_id=None)

    def test_absent_leaves_it_alone(self) -> None:
        body = TaskListUpdateAttributes.model_validate({"name": "Packing"})

        assert body.to_patch().associated_journal_id is UNSET

    @pytest.mark.parametrize("value", ["31", True, 0, -1, 1.0, INT32_MAX + 1], ids=repr)
    def test_anything_but_a_positive_integer_is_refused(self, value: Any) -> None:
        with pytest.raises(ValidationError):
            TaskListUpdateAttributes.model_validate({"associated_journal_id": value})

    def test_a_body_naming_nothing_says_the_association_is_a_change(self) -> None:
        with pytest.raises(ValidationError, match="associated_journal_id"):
            TaskListUpdateAttributes.model_validate({})


class TestTheAssociationOnTheRead:
    @pytest.mark.parametrize("journal_id", [31, None])
    def test_the_list_carries_its_journal(self, journal_id: int | None) -> None:
        resource: TaskListResource = to_task_list_resource(
            TaskList(
                id=7,
                user_id="user-1",
                name="Packing",
                position=0,
                associated_journal_id=journal_id,
            )
        )

        assert resource.attributes.associated_journal_id == journal_id

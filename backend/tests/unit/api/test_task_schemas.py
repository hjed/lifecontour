"""Unit tests for the task REST schemas.

These pin the *shape of the contract* rather than any behaviour: which fields a
client may send, which it may not, and what a created task looks like coming
back. Two of them are load-bearing beyond documentation.

``now`` is the seam the future-dated invariant is judged against. A request able
to set it would make that invariant opt-out for every client, so the schema must
not carry such a field — and, because a field's *absence* is not enforceable on
its own, unknown fields must be rejected outright.

There is deliberately no bare date either. A task is due in a *journal*, so the
only way to say when is to name one that already exists; a date field would
invite a journal to be created implicitly.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.tasks import Task, TaskStatus
from pydantic import ValidationError

from app.api.tasks.schemas import (
    TaskAttributes,
    TaskCreateAttributes,
    TaskCreateRequest,
    TaskResource,
    TaskResponse,
)


def _valid_body(**overrides: object) -> dict[str, object]:
    """A minimal valid create body, with attribute-level overrides applied."""
    attributes: dict[str, object] = {
        "text": "book the campsite",
        "due_journal_id": 42,
    }
    attributes.update(overrides)
    return {"data": {"type": "tasks", "attributes": attributes}}


class TestTaskCreateRequest:
    """What a client may send to create a task."""

    def test_a_minimal_body_needs_only_text_and_a_due_journal(self) -> None:
        request = TaskCreateRequest.model_validate(_valid_body())

        assert request.data.attributes.text == "book the campsite"
        assert request.data.attributes.due_journal_id == 42
        assert request.data.attributes.contact_ids is None

    def test_contacts_are_optional_and_accepted_as_a_list_of_ids(self) -> None:
        request = TaskCreateRequest.model_validate(_valid_body(contact_ids=[7, 9]))

        assert request.data.attributes.contact_ids == [7, 9]

    def test_the_resource_type_defaults_to_tasks(self) -> None:
        request = TaskCreateRequest.model_validate(
            {"data": {"attributes": {"text": "x", "due_journal_id": 1}}}
        )

        assert request.data.type == "tasks"

    def test_a_mismatched_resource_type_is_rejected(self) -> None:
        """Declaring one resource type and mutating another is a contract breach.

        A generic JSON:API client picks its request shape from the type it
        declares, so accepting ``"contacts"`` here and returning a task means
        that client performed a mutation it did not ask for.
        """
        with pytest.raises(ValidationError):
            TaskCreateRequest.model_validate(
                {
                    "data": {
                        "type": "contacts",
                        "attributes": {"text": "x", "due_journal_id": 1},
                    }
                }
            )

    def test_text_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreateRequest.model_validate(
                {"data": {"type": "tasks", "attributes": {"due_journal_id": 1}}}
            )

    def test_a_due_journal_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreateRequest.model_validate(
                {"data": {"type": "tasks", "attributes": {"text": "x"}}}
            )


class TestTheCreatingJournalIsNeverABodyField:
    """The creating journal comes from the path, and only from the path."""

    def test_creating_journal_id_is_not_an_attribute(self) -> None:
        assert "creating_journal_id" not in TaskCreateAttributes.model_fields

    def test_sending_a_creating_journal_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreateRequest.model_validate(_valid_body(creating_journal_id=99))


class TestTheNowSeamIsNotReachableFromARequest:
    """Invariant 4 is not opt-out, and cannot be made so by a later edit."""

    def test_no_attribute_is_named_now(self) -> None:
        assert "now" not in TaskCreateAttributes.model_fields

    def test_sending_now_is_rejected_rather_than_ignored(self) -> None:
        # Silently dropping it would be safe today and unsafe the moment somebody
        # wires the attributes model through to the service with **model_dump().
        with pytest.raises(ValidationError):
            TaskCreateRequest.model_validate(
                _valid_body(now="2020-01-01T00:00:00+00:00")
            )

    def test_unknown_attributes_are_rejected_in_general(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreateRequest.model_validate(_valid_body(nonsense="x"))

    def test_unknown_fields_alongside_the_attributes_are_rejected(self) -> None:
        # ``now`` smuggled one level up, beside ``attributes`` rather than inside.
        with pytest.raises(ValidationError):
            TaskCreateRequest.model_validate(
                {
                    "data": {
                        "type": "tasks",
                        "attributes": {"text": "x", "due_journal_id": 1},
                        "now": "2020-01-01T00:00:00+00:00",
                    }
                }
            )


class TestNoBareDateIsOffered:
    """A task is due in a journal; naming a date would imply creating one."""

    def test_no_attribute_offers_a_date(self) -> None:
        assert not [
            name
            for name in TaskCreateAttributes.model_fields
            if "date" in name or name == "due"
        ]

    def test_sending_a_due_date_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreateRequest.model_validate(_valid_body(due_date="2026-09-01"))


class TestTaskResponse:
    """What a created task looks like coming back."""

    def _task(self) -> Task:
        return Task(
            id=5,
            user_id="test-user-123",
            text="book the campsite",
            creating_journal_id=1,
            due_journal_id=2,
            status=TaskStatus.NOT_DONE,
            created_at=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
            updated_at=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
        )

    def test_the_resource_carries_both_anchors_and_the_status(self) -> None:
        resource = TaskResource(
            id="5",
            attributes=TaskAttributes(
                text=self._task().text,
                status=self._task().status,
                creating_journal_id=1,
                due_journal_id=2,
                created_at=self._task().created_at,
                updated_at=self._task().updated_at,
            ),
        )

        assert resource.type == "tasks"
        assert resource.attributes.creating_journal_id == 1
        assert resource.attributes.due_journal_id == 2

    def test_the_status_serialises_as_its_domain_string(self) -> None:
        response = TaskResponse(
            data=TaskResource(
                id="5",
                attributes=TaskAttributes(
                    text="book the campsite",
                    status=TaskStatus.NOT_DONE,
                    creating_journal_id=1,
                    due_journal_id=2,
                ),
            )
        )

        assert response.model_dump(mode="json")["data"]["attributes"]["status"] == (
            "not_done"
        )

    def test_timestamps_are_optional_so_an_unsaved_task_still_renders(self) -> None:
        attributes = TaskAttributes(
            text="book the campsite",
            status=TaskStatus.NOT_DONE,
            creating_journal_id=1,
            due_journal_id=2,
        )

        assert attributes.created_at is None
        assert attributes.updated_at is None

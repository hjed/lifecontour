"""Unit tests for the body of ``POST /api/task-lists/{list_id}/tasks``.

A task created on a list names its text, optionally a due date and contacts.
The list is the path, so it is never a body field; a due journal arrives in a
later phase, so until then it is refused rather than silently dropped. The due
date is a calendar day sent as an ISO string: a JSON number would otherwise be
read as a timestamp and cut to its UTC day.
"""

import datetime

import pytest
from pydantic import ValidationError

from app.api.tasks.schemas import ListTaskCreateRequest


def _body(**attributes: object) -> dict[str, object]:
    """A create body over ``attributes``, with text unless a case overrides it."""
    return {
        "data": {
            "type": "tasks",
            "attributes": {"text": "pack the tent", **attributes},
        }
    }


def test_text_alone_is_a_valid_body() -> None:
    request = ListTaskCreateRequest.model_validate(_body())

    attributes = request.data.attributes
    assert attributes.text == "pack the tent"
    assert attributes.due_date is None
    assert attributes.contact_ids is None


def test_an_iso_due_date_is_read_as_that_day() -> None:
    request = ListTaskCreateRequest.model_validate(_body(due_date="2026-11-30"))

    assert request.data.attributes.due_date == datetime.date(2026, 11, 30)


def test_contacts_are_accepted_as_a_list_of_ids() -> None:
    request = ListTaskCreateRequest.model_validate(_body(contact_ids=[3, 4]))

    assert request.data.attributes.contact_ids == [3, 4]


@pytest.mark.parametrize(
    "due_date",
    [20261130, 1764460800, "2026-11-30T09:00:00Z", "30/11/2026", "2026-11-31"],
    ids=repr,
)
def test_anything_but_an_iso_calendar_date_is_refused(due_date: object) -> None:
    with pytest.raises(ValidationError):
        ListTaskCreateRequest.model_validate(_body(due_date=due_date))


@pytest.mark.parametrize(
    "attribute",
    [
        "due_journal_id",
        "creating_journal_id",
        "task_list_id",
        "position",
        "flagged",
        "icon",
        "now",
    ],
)
def test_an_attribute_this_create_does_not_take_is_refused(attribute: str) -> None:
    """Refused rather than dropped, so a client never believes it was applied."""
    with pytest.raises(ValidationError):
        ListTaskCreateRequest.model_validate(_body(**{attribute: 1}))


def test_text_is_required() -> None:
    body = {"data": {"type": "tasks", "attributes": {}}}

    with pytest.raises(ValidationError):
        ListTaskCreateRequest.model_validate(body)


def test_another_resource_type_is_refused() -> None:
    body = _body()
    body["data"] = {**body["data"], "type": "task-lists"}  # type: ignore[dict-item]

    with pytest.raises(ValidationError):
        ListTaskCreateRequest.model_validate(body)


def test_an_unknown_field_at_the_root_is_refused() -> None:
    with pytest.raises(ValidationError):
        ListTaskCreateRequest.model_validate({**_body(), "now": "2026-01-01"})

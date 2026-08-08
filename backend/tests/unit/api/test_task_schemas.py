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
    TaskContactLinkData,
    TaskContactLinkRequest,
    TaskCreateAttributes,
    TaskCreateRequest,
    TaskIntermediateJournalLinkData,
    TaskIntermediateJournalLinkRequest,
    TaskResource,
    TaskResponse,
    TaskUpdateAttributes,
    TaskUpdateRequest,
)


def _valid_link_body(**overrides: object) -> dict[str, object]:
    """A minimal valid contact-link body, with data-level overrides applied."""
    data: dict[str, object] = {"type": "contacts", "id": "7"}
    data.update(overrides)
    return {"data": data}


def _valid_journal_link_body(**overrides: object) -> dict[str, object]:
    """A minimal valid intermediate-journal link body, with data-level overrides."""
    data: dict[str, object] = {"type": "journals", "id": "9"}
    data.update(overrides)
    return {"data": data}


def _valid_body(**overrides: object) -> dict[str, object]:
    """A minimal valid create body, with attribute-level overrides applied."""
    attributes: dict[str, object] = {
        "text": "book the campsite",
        "due_journal_id": 42,
    }
    attributes.update(overrides)
    return {"data": {"type": "tasks", "attributes": attributes}}


def _valid_update_body(**overrides: object) -> dict[str, object]:
    """A minimal valid status-update body, with attribute-level overrides."""
    attributes: dict[str, object] = {"status": "done"}
    attributes.update(overrides)
    return {"data": {"type": "tasks", "id": "5", "attributes": attributes}}


def _update_body(**attributes: object) -> dict[str, object]:
    """An update body carrying exactly the attributes given, and no default.

    ``_valid_update_body`` always starts from a status, which is the wrong base
    for the optionality rules: a test that "text alone is accepted" has to be
    able to send a body with no status in it at all.
    """
    return {"data": {"type": "tasks", "id": "5", "attributes": attributes}}


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

    def test_unknown_fields_at_the_request_root_are_rejected(self) -> None:
        """The outermost level needs its own guard, and did not have one.

        Raised in review: forbidding extras on the attributes and data models
        leaves the request envelope itself permissive, because the shared
        ``JsonApiCreateRequest`` base ignores unknown members. ``now`` beside
        ``data`` was silently dropped rather than refused — harmless while
        nothing reads it, and exactly the shape of omission the other two
        guards exist to prevent.
        """
        with pytest.raises(ValidationError):
            TaskCreateRequest.model_validate(
                {
                    "data": {
                        "type": "tasks",
                        "attributes": {"text": "x", "due_journal_id": 1},
                    },
                    "now": "2020-01-01T00:00:00+00:00",
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


class TestTaskUpdateRequest:
    """What a client may send to change a task's status."""

    @pytest.mark.parametrize("value", ["not_done", "done", "cancelled"])
    def test_each_domain_status_is_accepted(self, value: str) -> None:
        request = TaskUpdateRequest.model_validate(_valid_update_body(status=value))

        assert request.data.attributes.status == TaskStatus(value)

    def test_an_unknown_status_is_rejected(self) -> None:
        """The three values are the whole vocabulary; there is no in-progress."""
        with pytest.raises(ValidationError):
            TaskUpdateRequest.model_validate(_valid_update_body(status="in_progress"))

    def test_the_resource_id_is_required(self) -> None:
        """JSON:API identifies the resource in the body as well as the path."""
        with pytest.raises(ValidationError):
            TaskUpdateRequest.model_validate(
                {"data": {"type": "tasks", "attributes": {"status": "done"}}}
            )

    def test_a_mismatched_resource_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskUpdateRequest.model_validate(
                {
                    "data": {
                        "type": "contacts",
                        "id": "5",
                        "attributes": {"status": "done"},
                    }
                }
            )


class TestTheUpdateRequestCarriesTextAndStatus:
    """Both are optional individually, and at least one must be present.

    JSON:API sends the attributes that changed, so a client rewording a task
    sends no status and a client completing one sends no text — and a client
    doing both in one request sends both, which is why the two are applied by a
    single service call rather than two.
    """

    def test_text_alone_is_accepted(self) -> None:
        request = TaskUpdateRequest.model_validate(_update_body(text="rewritten"))

        assert request.data.attributes.text == "rewritten"
        assert request.data.attributes.status is None

    def test_status_alone_is_accepted(self) -> None:
        request = TaskUpdateRequest.model_validate(_update_body(status="done"))

        assert request.data.attributes.status == TaskStatus.DONE
        assert request.data.attributes.text is None

    def test_both_together_are_accepted(self) -> None:
        """One request, one decision — the reason the service applies both at once."""
        request = TaskUpdateRequest.model_validate(
            _update_body(text="rewritten", status="done")
        )

        assert request.data.attributes.text == "rewritten"
        assert request.data.attributes.status == TaskStatus.DONE

    def test_a_body_naming_no_change_is_rejected(self) -> None:
        """An update that updates nothing is a malformed request, not a no-op.

        The *service* treats it as nothing to do, because down there it is. Over
        JSON:API it is a client that built a body wrong, and answering 200 would
        tell it the edit it thinks it made was applied.
        """
        with pytest.raises(ValidationError):
            TaskUpdateRequest.model_validate(_update_body())

    def test_an_explicitly_null_attribute_counts_as_naming_no_change(self) -> None:
        """``{"text": null}`` is not a way to blank a task's text.

        Text is required on a task, so null cannot mean "remove it"; treating it
        as "not sent" is the only reading that does not invent a fourth state.
        """
        with pytest.raises(ValidationError):
            TaskUpdateRequest.model_validate(_update_body(text=None, status=None))

    def test_empty_text_reaches_the_domain_rather_than_being_refused_twice(
        self,
    ) -> None:
        """One definition of an acceptable task, not two that can drift apart.

        The schema's job is the envelope; whether a text is acceptable is the
        entity's, and it answers the same way for a create, a ``PATCH`` and an
        MCP call. Adding ``min_length`` here would put a second rule beside it
        that a later change to one would silently leave inconsistent with the
        other.
        """
        request = TaskUpdateRequest.model_validate(_update_body(text=""))

        assert request.data.attributes.text == ""


class TestTheUpdateRequestChangesNothingElse:
    """Text and status are the whole of it; everything else is refused.

    The due journal (Phase 8) and contact links (Phase 11) are edited through
    their own surfaces; accepting either here now would ship a half-implemented
    field that silently did nothing.
    """

    @pytest.mark.parametrize(
        "field", ["due_journal_id", "creating_journal_id", "contact_ids"]
    )
    def test_no_other_attribute_exists(self, field: str) -> None:
        assert field not in TaskUpdateAttributes.model_fields

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("due_journal_id", 9),
            ("creating_journal_id", 9),
            ("now", "2020-01-01T00:00:00+00:00"),
            ("nonsense", "x"),
        ],
    )
    def test_sending_another_attribute_is_rejected(
        self, field: str, value: object
    ) -> None:
        with pytest.raises(ValidationError):
            TaskUpdateRequest.model_validate(_valid_update_body(**{field: value}))

    def test_unknown_fields_alongside_the_attributes_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskUpdateRequest.model_validate(
                {
                    "data": {
                        "type": "tasks",
                        "id": "5",
                        "attributes": {"status": "done"},
                        "now": "2020-01-01T00:00:00+00:00",
                    }
                }
            )

    def test_unknown_fields_at_the_request_root_are_rejected(self) -> None:
        """All three nesting levels, as the create request had to learn."""
        with pytest.raises(ValidationError):
            TaskUpdateRequest.model_validate(
                {
                    "data": {
                        "type": "tasks",
                        "id": "5",
                        "attributes": {"status": "done"},
                    },
                    "now": "2020-01-01T00:00:00+00:00",
                }
            )


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


class TestTaskContactLinkRequest:
    """What a client may send to link a contact to a task.

    The body is a **resource identifier object** — a type and an id, no
    attributes — because that is all a task-contact link is. The specification
    is explicit that these links *"do not carry a relationship type, a role, or
    an attendance status"*, so every one of those is a field this schema must
    refuse rather than merely omit.
    """

    def test_a_minimal_body_names_a_contact(self) -> None:
        request = TaskContactLinkRequest.model_validate(_valid_link_body())

        assert request.data.id == "7"
        assert request.data.type == "contacts"

    def test_the_resource_type_defaults_to_contacts(self) -> None:
        request = TaskContactLinkRequest.model_validate({"data": {"id": "7"}})

        assert request.data.type == "contacts"

    def test_a_mismatched_resource_type_is_rejected(self) -> None:
        """The linked resource is a contact; declaring anything else is an error.

        A generic JSON:API client picks its request shape from the type it
        declares, so accepting ``"tasks"`` here and linking a contact would mean
        that client mutated a relationship it never asked for.
        """
        with pytest.raises(ValidationError):
            TaskContactLinkRequest.model_validate(_valid_link_body(type="tasks"))

    def test_the_contact_id_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TaskContactLinkRequest.model_validate({"data": {"type": "contacts"}})

    def test_the_data_member_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TaskContactLinkRequest.model_validate({})


class TestTheLinkCarriesNoRelationshipData:
    """Criterion 2, stated where a client can be told about it."""

    @pytest.mark.parametrize(
        "field", ["relationship_type", "role", "status", "attendance"]
    )
    def test_relationship_fields_are_rejected(self, field: str) -> None:
        """A journal-contact link carries these; a task-contact link never does.

        Accepting one silently would be worse than refusing it: the client would
        believe it had recorded a role, and nothing would have stored it.
        """
        with pytest.raises(ValidationError):
            TaskContactLinkRequest.model_validate(_valid_link_body(**{field: "x"}))

    def test_attributes_are_rejected(self) -> None:
        """There is nothing a link *has*, so there is nowhere to put it."""
        with pytest.raises(ValidationError):
            TaskContactLinkRequest.model_validate(
                _valid_link_body(attributes={"role": "organiser"})
            )

    def test_unknown_fields_are_rejected_beside_the_data_member(self) -> None:
        """The envelope level Phase 5's review found open on the create request.

        A guard with a gap is no guard to whoever finds the gap, and a JSON:API
        envelope has more than one nesting depth.
        """
        with pytest.raises(ValidationError):
            TaskContactLinkRequest.model_validate(
                {
                    "data": {"type": "contacts", "id": "7"},
                    "relationship_type": "MENTION",
                }
            )

    def test_unknown_fields_are_rejected_inside_the_data_member(self) -> None:
        with pytest.raises(ValidationError):
            TaskContactLinkData.model_validate(
                {"type": "contacts", "id": "7", "surprise": 1}
            )


class TestTaskIntermediateJournalLinkRequest:
    """What a client may send to attach an intermediate journal to a task.

    The same resource-identifier shape as the contact link, and for the same
    reason: an intermediate link records *that* a task was discussed or revisited
    in a journal, and nothing else. There is no role to send, because the three
    journal roles a task has are not a property of this row — the creating and
    due journals are columns on the task, and attaching either through here is
    refused by the service.

    The resource **type** is ``journals``: the relationship's name lives in the
    path (``/relationships/intermediate-journals``) and the type names what the
    identifier points at, which is an ordinary journal.
    """

    def test_a_minimal_body_names_a_journal(self) -> None:
        request = TaskIntermediateJournalLinkRequest.model_validate(
            _valid_journal_link_body()
        )

        assert request.data.id == "9"
        assert request.data.type == "journals"
        assert request.data.journal_id == 9

    def test_the_resource_type_defaults_to_journals(self) -> None:
        request = TaskIntermediateJournalLinkRequest.model_validate(
            {"data": {"id": "9"}}
        )

        assert request.data.type == "journals"

    def test_a_mismatched_resource_type_is_rejected(self) -> None:
        """Declaring ``contacts`` here would attach a journal to a task.

        The two link routes take structurally identical bodies, so the type is
        the only thing standing between them for a generic client that posts to
        the wrong one.
        """
        with pytest.raises(ValidationError):
            TaskIntermediateJournalLinkRequest.model_validate(
                _valid_journal_link_body(type="contacts")
            )

    def test_the_journal_id_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TaskIntermediateJournalLinkRequest.model_validate(
                {"data": {"type": "journals"}}
            )

    def test_the_data_member_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TaskIntermediateJournalLinkRequest.model_validate({})

    def test_a_non_integer_id_is_a_bad_request_rather_than_a_crash(self) -> None:
        """Checked in the schema so it is a 400 like every other bad field.

        Casting in the controller instead would let a ``ValueError`` escape as a
        500 for what is plainly a malformed request.
        """
        with pytest.raises(ValidationError):
            TaskIntermediateJournalLinkRequest.model_validate(
                _valid_journal_link_body(id="not-a-number")
            )

    @pytest.mark.parametrize("journal_id", ["0", "-1", "2147483648"])
    def test_an_id_no_row_could_have_is_rejected(self, journal_id: str) -> None:
        """Python's ``int`` is unbounded; ``journals.id`` is a PostgreSQL INTEGER.

        Without the bound, ``2147483648`` parses cleanly, reaches the repository
        and dies in asyncpg's parameter binding — a 500 for an id no row could
        ever have. The lower bound is ``1`` because serial columns start there.
        """
        with pytest.raises(ValidationError):
            TaskIntermediateJournalLinkRequest.model_validate(
                _valid_journal_link_body(id=journal_id)
            )


class TestTheJournalLinkCarriesNoRole:
    """Criterion: an intermediate link is a plain mention, with no role field.

    A client that has seen the journal-contact relationship — which does carry a
    type, a role and an attendance status — will reach for one of those here.
    Every one is refused rather than dropped, because a field silently ignored is
    a field the client believes was stored.
    """

    @pytest.mark.parametrize("field", ["relationship_type", "role", "status", "anchor"])
    def test_role_fields_are_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError):
            TaskIntermediateJournalLinkRequest.model_validate(
                _valid_journal_link_body(**{field: "due"})
            )

    def test_attributes_are_rejected(self) -> None:
        """There is nothing an intermediate link *has*, so nowhere to put it."""
        with pytest.raises(ValidationError):
            TaskIntermediateJournalLinkRequest.model_validate(
                _valid_journal_link_body(attributes={"role": "due"})
            )

    @pytest.mark.parametrize("field", ["relationship_type", "role", "status", "anchor"])
    def test_role_fields_are_rejected_beside_the_data_member_too(
        self, field: str
    ) -> None:
        """Both nesting levels, not just the inner one.

        Review caught the claim that all four were refused at both levels when
        only ``role`` was tested out here. A guard with a gap is no guard to
        whoever finds the gap, and a JSON:API envelope has more than one depth.
        """
        with pytest.raises(ValidationError):
            TaskIntermediateJournalLinkRequest.model_validate(
                {"data": {"type": "journals", "id": "9"}, field: "due"}
            )

    def test_unknown_fields_are_rejected_inside_the_data_member(self) -> None:
        with pytest.raises(ValidationError):
            TaskIntermediateJournalLinkData.model_validate(
                {"type": "journals", "id": "9", "surprise": 1}
            )

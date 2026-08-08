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

from app.api.common.identifiers import INT32_MAX
from app.api.tasks.schemas import (
    TaskAttributes,
    TaskContactLinkData,
    TaskContactLinkRequest,
    TaskCreateAttributes,
    TaskCreateRequest,
    TaskResource,
    TaskResponse,
    TaskRetargetRequest,
    TaskUpdateAttributes,
    TaskUpdateRequest,
)


def _valid_link_body(**overrides: object) -> dict[str, object]:
    """A minimal valid contact-link body, with data-level overrides applied."""
    data: dict[str, object] = {"type": "contacts", "id": "7"}
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


def _valid_retarget_body(**overrides: object) -> dict[str, object]:
    """A minimal valid retarget body, with attribute-level overrides applied."""
    attributes: dict[str, object] = {"due_journal_id": 42}
    attributes.update(overrides)
    return {"data": {"type": "task-retarget", "attributes": attributes}}


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


class TestTaskRetargetRequest:
    """What a client may send to move a task onto a new due journal.

    The retarget is its own request rather than a field on the status ``PATCH``
    because it is not a field assignment: it forces the status to *not done* and
    writes an intermediate link. A body able to carry both a ``status`` and a
    ``due_journal_id`` would have two answers and no rule for choosing one.
    """

    def test_a_minimal_body_needs_only_the_new_due_journal(self) -> None:
        request = TaskRetargetRequest.model_validate(_valid_retarget_body())

        assert request.data.attributes.due_journal_id == 42

    def test_the_acknowledgement_defaults_to_not_given(self) -> None:
        """An unaware caller must get the refusal, not the reopen.

        The gate exists because moving a date is rarely how a user means to undo
        a completion, so the *absence* of a confirmation has to read as "no".
        """
        request = TaskRetargetRequest.model_validate(_valid_retarget_body())

        assert request.data.attributes.acknowledge_reopen is False

    def test_the_acknowledgement_is_accepted_when_given(self) -> None:
        request = TaskRetargetRequest.model_validate(
            _valid_retarget_body(acknowledge_reopen=True)
        )

        assert request.data.attributes.acknowledge_reopen is True

    def test_a_non_boolean_acknowledgement_is_rejected(self) -> None:
        """A confirmation coerced from prose would be a confirmation nobody gave."""
        with pytest.raises(ValidationError):
            TaskRetargetRequest.model_validate(
                _valid_retarget_body(acknowledge_reopen="maybe")
            )

    def test_the_due_journal_is_required(self) -> None:
        """There is nothing else this request could be asking for."""
        with pytest.raises(ValidationError):
            TaskRetargetRequest.model_validate(
                {"data": {"type": "task-retarget", "attributes": {}}}
            )

    def test_the_resource_type_defaults_to_the_operation(self) -> None:
        request = TaskRetargetRequest.model_validate(
            {"data": {"attributes": {"due_journal_id": 42}}}
        )

        assert request.data.type == "task-retarget"

    def test_a_mismatched_resource_type_is_rejected(self) -> None:
        """The body describes an operation, not the task resource itself.

        Typing it ``tasks`` would say a client was sending the task's own
        attributes, when what it is sending is an instruction with its own
        preconditions — the shape ``journal-merge`` already uses.
        """
        with pytest.raises(ValidationError):
            TaskRetargetRequest.model_validate(_valid_retarget_body(type="tasks"))

    def test_the_data_member_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TaskRetargetRequest.model_validate({})


class TestTheRetargetIdIsBoundedToWhatAColumnCanHold:
    """Every id column in this schema is a PostgreSQL ``INTEGER``.

    Python's ``int`` is unbounded, so ``2147483648`` parses cleanly, reaches the
    repository and dies in asyncpg's parameter binding — a 500 for an id no row
    could ever have. Found on five routes by the Phase 11 review; the bound
    belongs on this one from the start.
    """

    def test_the_largest_id_a_row_can_have_is_accepted(self) -> None:
        request = TaskRetargetRequest.model_validate(
            _valid_retarget_body(due_journal_id=INT32_MAX)
        )

        assert request.data.attributes.due_journal_id == INT32_MAX

    def test_an_id_beyond_the_column_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskRetargetRequest.model_validate(
                _valid_retarget_body(due_journal_id=INT32_MAX + 1)
            )

    @pytest.mark.parametrize("value", [0, -1])
    def test_an_id_no_serial_column_issues_is_rejected(self, value: int) -> None:
        with pytest.raises(ValidationError):
            TaskRetargetRequest.model_validate(
                _valid_retarget_body(due_journal_id=value)
            )


class TestTheRetargetChangesNothingButTheDueJournal:
    """The creating journal stays unreachable, and there is still no bare date.

    Only the *rejection* is asserted, not also the field's absence from
    ``model_fields``. The two said the same thing and the rejection is the
    stronger claim — a field that existed but was ignored would pass a
    membership check's inverse and fail this one.
    """

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            # Immutable by absence: the specification's "set once and never
            # changes" is enforced by there being nothing to send, and the
            # service has no parameter for it either.
            ("creating_journal_id", 9),
            # A retarget always lands on *not done*. A status here would be a
            # second answer to a question the operation has already settled.
            ("status", "done"),
            ("text", "rewritten"),
            # ``now`` is the seam invariant 4 is judged against.
            ("now", "2020-01-01T00:00:00+00:00"),
            # A task is due *in a journal*; a date would invite one to be
            # created implicitly, which invariant 5 forbids.
            ("due_date", "2026-09-01"),
            ("nonsense", "x"),
        ],
    )
    def test_sending_another_attribute_is_rejected(
        self, field: str, value: object
    ) -> None:
        with pytest.raises(ValidationError):
            TaskRetargetRequest.model_validate(_valid_retarget_body(**{field: value}))

    def test_unknown_fields_alongside_the_attributes_are_rejected(self) -> None:
        """The middle of the three nesting levels the create request had to close."""
        with pytest.raises(ValidationError):
            TaskRetargetRequest.model_validate(
                {
                    "data": {
                        "type": "task-retarget",
                        "attributes": {"due_journal_id": 42},
                        "now": "2020-01-01T00:00:00+00:00",
                    }
                }
            )

    def test_unknown_fields_at_the_request_root_are_rejected(self) -> None:
        """And the outermost, where the shared base is permissive by default.

        A misspelled ``acknowledge_reopen`` silently dropped here would be worse
        than one refused: the caller would believe it had confirmed a reopen.
        """
        with pytest.raises(ValidationError):
            TaskRetargetRequest.model_validate(
                {
                    "data": {
                        "type": "task-retarget",
                        "attributes": {"due_journal_id": 42},
                    },
                    "acknowledge_reopen": True,
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


class TestTheTaskResourceCarriesItsJournalTrail:
    """A retarget's answer includes the journal it just left.

    The specification's third success criterion is that a user can *"extend a
    deadline by moving a task to a later journal, and still see the trail of
    journals it passed through"*, and the phase's criterion is that the caller
    sees it without a second read.

    It is an **attribute** rather than a JSON:API ``relationships`` member
    because this resource already carries ``creating_journal_id`` and
    ``due_journal_id`` as attributes. One convention, not two.
    """

    def test_the_trail_is_part_of_the_resource(self) -> None:
        attributes = TaskAttributes(
            text="book the campsite",
            status=TaskStatus.NOT_DONE,
            creating_journal_id=1,
            due_journal_id=2,
            intermediate_journal_ids=[7, 8],
        )

        assert attributes.intermediate_journal_ids == [7, 8]

    def test_a_task_that_has_passed_through_nothing_renders_an_empty_trail(
        self,
    ) -> None:
        """Empty rather than absent: the field means "these, and no others"."""
        attributes = TaskAttributes(
            text="book the campsite",
            status=TaskStatus.NOT_DONE,
            creating_journal_id=1,
            due_journal_id=2,
        )

        assert attributes.intermediate_journal_ids == []

    def test_the_trail_survives_serialisation(self) -> None:
        response = TaskResponse(
            data=TaskResource(
                id="5",
                attributes=TaskAttributes(
                    text="book the campsite",
                    status=TaskStatus.NOT_DONE,
                    creating_journal_id=1,
                    due_journal_id=2,
                    intermediate_journal_ids=[7],
                ),
            )
        )

        rendered = response.model_dump(mode="json")["data"]["attributes"]
        assert rendered["intermediate_journal_ids"] == [7]

    def test_each_default_trail_is_its_own_list(self) -> None:
        """A shared mutable default would leak one task's trail into another's."""
        first = TaskAttributes(
            text="a",
            status=TaskStatus.NOT_DONE,
            creating_journal_id=1,
            due_journal_id=2,
        )
        second = TaskAttributes(
            text="b",
            status=TaskStatus.NOT_DONE,
            creating_journal_id=1,
            due_journal_id=2,
        )
        first.intermediate_journal_ids.append(99)

        assert second.intermediate_journal_ids == []


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

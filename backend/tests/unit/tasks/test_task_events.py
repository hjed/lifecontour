"""Unit tests for the tasks domain's domain events.

The specification makes tasks first-class domain entities that "emit domain
events through the same transactional outbox and stream that contacts and
journals use", each carrying provenance and the actor. These tests pin the two
things the rest of the pipeline depends on and that nothing downstream can
recover if they are wrong:

* the **payload shape**, asserted as a whole-key comparison rather than a
  handful of ``in`` checks, because the history projection (Phase 6) reads these
  keys by name and a silently added or renamed one would be found by the
  projection's tests rather than by these; and
* the **JSON round trip**, because the payload reaches that projection through
  ``outbox_events.event_data`` and a Redis stream, never as the Python objects
  constructed here.

``TaskUpdated`` adds a third thing to pin: ``changed_fields`` is read *by index*
downstream, so the ``(old, new)`` ordering is asserted positionally rather than
by unpacking, in the same form ``HistoryService._rows_from_changed_fields``
reads it.

Constants come from :mod:`tests.unit.tasks.task_doubles` so an event's idea of a
task and the service tests' idea of one cannot drift apart.
"""

import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskJournalRepointing, TaskStatus

from app.core.tasks.models.events import (
    TaskCreated,
    TaskDeleted,
    TaskDueJournalRetargeted,
    TaskJournalLinked,
    TaskJournalLinkOrigin,
    TaskJournalLinksRepointed,
    TaskJournalUnlinked,
    TaskUpdated,
    journal_field_name,
)
from tests.unit.tasks.task_doubles import (
    ABSORBED_JOURNAL_ID,
    CONTACT_ID,
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    INTERMEDIATE_JOURNAL_ID,
    NEW_DUE_JOURNAL_ID,
    ORIGINAL_TEXT,
    OTHER_CONTACT_ID,
    SURVIVING_JOURNAL_ID,
    TASK_ID,
    UPDATED_TEXT,
    USER_ID,
)

TEXT_CHANGE: dict[str, Any] = {"text": (ORIGINAL_TEXT, UPDATED_TEXT)}
STATUS_CHANGE: dict[str, Any] = {
    "status": (TaskStatus.NOT_DONE.value, TaskStatus.DONE.value)
}
# Contact membership travels as a ``changed_fields`` key like any other field of
# the task, keyed *per contact* so two people never share a history row. A link
# is ``(None, id)`` and an unlink ``(id, None)`` — the shape
# ``JournalTagAssigned`` already projects, where the absent side is the state the
# link did not have.
CONTACT_LINKED: dict[str, Any] = {f"contact:{CONTACT_ID}": (None, CONTACT_ID)}
CONTACT_UNLINKED: dict[str, Any] = {f"contact:{CONTACT_ID}": (CONTACT_ID, None)}


def make_created(
    *,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
    status: TaskStatus = TaskStatus.NOT_DONE,
    contact_ids: list[int] | None = None,
    transaction: AsyncMock | None = None,
) -> TaskCreated:
    """A ``TaskCreated`` over the shared task constants.

    ``contact_ids`` defaults to *none linked*, which is the ordinary create. The
    argument is defaulted **here** rather than on the event, which requires it
    for the reason ``TaskJournalLinked.origin`` does: a create that named people
    and forgot to pass them would silently report a task with nobody on it.
    """
    return TaskCreated(
        task_id=TASK_ID,
        user_id=USER_ID,
        text=ORIGINAL_TEXT,
        status=status,
        creating_journal_id=CREATING_JOURNAL_ID,
        due_journal_id=DUE_JOURNAL_ID,
        contact_ids=[] if contact_ids is None else contact_ids,
        source=source,
        changed_by=changed_by,
        transaction=transaction,
    )


def make_updated(
    *,
    changed_fields: dict[str, Any] | None = None,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
    transaction: AsyncMock | None = None,
) -> TaskUpdated:
    """A ``TaskUpdated`` over the shared task constants, rewording by default."""
    return TaskUpdated(
        task_id=TASK_ID,
        user_id=USER_ID,
        changed_fields=TEXT_CHANGE if changed_fields is None else changed_fields,
        source=source,
        changed_by=changed_by,
        transaction=transaction,
    )


def make_retargeted(
    *,
    previous_status: TaskStatus = TaskStatus.NOT_DONE,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
    transaction: AsyncMock | None = None,
) -> TaskDueJournalRetargeted:
    """A ``TaskDueJournalRetargeted`` over the shared task constants.

    The default is the ordinary case: a not-done task moved from
    ``DUE_JOURNAL_ID`` to ``NEW_DUE_JOURNAL_ID``. The journal it left is retained
    as an intermediate link, but that is announced by its own
    ``TaskJournalLinked`` rather than carried here.
    """
    return TaskDueJournalRetargeted(
        task_id=TASK_ID,
        user_id=USER_ID,
        previous_due_journal_id=DUE_JOURNAL_ID,
        due_journal_id=NEW_DUE_JOURNAL_ID,
        previous_status=previous_status,
        source=source,
        changed_by=changed_by,
        transaction=transaction,
    )


def make_linked(
    *,
    journal_id: int = INTERMEDIATE_JOURNAL_ID,
    origin: TaskJournalLinkOrigin = TaskJournalLinkOrigin.MANUAL,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
    transaction: AsyncMock | None = None,
) -> TaskJournalLinked:
    """A ``TaskJournalLinked`` over the shared task constants.

    The default is the case the user drives: somebody attached a journal the task
    is merely mentioned in.
    """
    return TaskJournalLinked(
        task_id=TASK_ID,
        user_id=USER_ID,
        journal_id=journal_id,
        origin=origin,
        source=source,
        changed_by=changed_by,
        transaction=transaction,
    )


def make_unlinked(
    *,
    journal_id: int = INTERMEDIATE_JOURNAL_ID,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
    transaction: AsyncMock | None = None,
) -> TaskJournalUnlinked:
    """A ``TaskJournalUnlinked`` over the shared task constants."""
    return TaskJournalUnlinked(
        task_id=TASK_ID,
        user_id=USER_ID,
        journal_id=journal_id,
        source=source,
        changed_by=changed_by,
        transaction=transaction,
    )


def make_repointed(
    *,
    task_id: int = TASK_ID,
    source_journal_id: int = ABSORBED_JOURNAL_ID,
    target_journal_id: int = SURVIVING_JOURNAL_ID,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
    transaction: AsyncMock | None = None,
    **facts: bool,
) -> TaskJournalLinksRepointed:
    """A ``TaskJournalLinksRepointed`` over the shared task constants.

    The default is the plainest case a merge produces: the absorbed journal was
    the task's due anchor, and now the survivor is. ``facts`` names whichever
    others a test is about, so each test reads as the merge outcome it describes
    rather than as five booleans.
    """
    return TaskJournalLinksRepointed(
        repointing=TaskJournalRepointing(
            task_id=task_id,
            user_id=USER_ID,
            **(facts or {"due_anchor_moved": True}),
        ),
        source_journal_id=source_journal_id,
        target_journal_id=target_journal_id,
        source=source,
        changed_by=changed_by,
        transaction=transaction,
    )


def make_deleted(
    *,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
    transaction: AsyncMock | None = None,
) -> TaskDeleted:
    """A ``TaskDeleted`` over the shared task constants."""
    return TaskDeleted(
        task_id=TASK_ID,
        user_id=USER_ID,
        source=source,
        changed_by=changed_by,
        transaction=transaction,
    )


class TestTaskCreated:
    """The event a successful create publishes."""

    def test_identifies_itself_as_a_task_created_event(self) -> None:
        event = make_created()

        assert event.event_type == "TaskCreated"
        assert event.event_id.startswith(f"task_created_{TASK_ID}_")

    def test_aggregate_id_is_the_integer_task_id(self) -> None:
        """The aggregate is the task, keyed by its own integer id.

        Phase 6 projects rows under ``entity_id`` from this field and
        ``field_history.entity_id`` is an ``Integer`` column, so a task event
        that aggregated under anything else — the due journal, a hashed UUID —
        would land its history on the wrong entity.
        """
        event = make_created()

        assert event.aggregate_id == TASK_ID
        assert isinstance(event.aggregate_id, int)

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """A whole-key comparison, so a new key is a deliberate change.

        ``contact_ids`` is the one key this test has ever gained, and it was
        gained deliberately. Phase 1 left it out and pinned the absence so that
        *"whether a create with contacts publishes one event or two"* would be
        decided where it belonged; this phase decides it — **one event, and it
        names them** — because contact membership is a field of the task rather
        than an aggregate of its own, and a create silent about it would leave a
        later unlink writing an "unlinked Sarah" line into a history with no
        matching "linked" line before it.
        """
        event = make_created()

        assert event.event_data == {
            "task_id": TASK_ID,
            "user_id": USER_ID,
            "text": ORIGINAL_TEXT,
            "status": TaskStatus.NOT_DONE.value,
            "creating_journal_id": CREATING_JOURNAL_ID,
            "due_journal_id": DUE_JOURNAL_ID,
            "contact_ids": [],
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_status_is_stored_as_its_string_value(self) -> None:
        """The enum is the argument; JSON is what the payload has to hold."""
        event = make_created(status=TaskStatus.NOT_DONE)

        assert event.event_data["status"] == "not_done"

    def test_carries_the_contacts_the_create_actually_linked(self) -> None:
        event = make_created(contact_ids=[CONTACT_ID, OTHER_CONTACT_ID])

        assert event.event_data["contact_ids"] == [CONTACT_ID, OTHER_CONTACT_ID]

    def test_a_create_naming_nobody_carries_an_empty_list(self) -> None:
        """An empty list rather than a missing key or ``None``.

        The projection reads this by name, and three ways of saying "nobody"
        would be three branches there. A create with no contacts is by far the
        common case, so the shape it produces is the one worth pinning.
        """
        assert make_created().event_data["contact_ids"] == []

    def test_the_contact_order_is_the_order_they_were_linked(self) -> None:
        """Not sorted here.

        ``TaskService._resolve_contacts`` de-duplicates while preserving the
        caller's order and ``_link_contacts`` returns the ids a row was written
        for, so the list already means something by the time it arrives.
        Re-ordering it would discard that for no gain.
        """
        event = make_created(contact_ids=[OTHER_CONTACT_ID, CONTACT_ID])

        assert event.event_data["contact_ids"] == [OTHER_CONTACT_ID, CONTACT_ID]

    def test_the_contacts_must_be_stated_rather_than_defaulted(self) -> None:
        """No default, for the reason ``TaskJournalLinked.origin`` has none.

        Every other optional argument on these events defaults to the safest
        reading. There is none here: ``[]`` is right for the common create and a
        **lie** for the one that named people, and the failure would be silent —
        a task with three people on it whose own creation event says nobody was
        involved. Requiring it makes the one production caller say so.
        """
        with pytest.raises(TypeError):
            TaskCreated(  # type: ignore[call-arg]
                task_id=TASK_ID,
                user_id=USER_ID,
                text=ORIGINAL_TEXT,
                status=TaskStatus.NOT_DONE,
                creating_journal_id=CREATING_JOURNAL_ID,
                due_journal_id=DUE_JOURNAL_ID,
            )

    def test_defaults_to_system_provenance(self) -> None:
        event = TaskCreated(
            task_id=TASK_ID,
            user_id=USER_ID,
            text=ORIGINAL_TEXT,
            status=TaskStatus.NOT_DONE,
            creating_journal_id=CREATING_JOURNAL_ID,
            due_journal_id=DUE_JOURNAL_ID,
            contact_ids=[],
        )

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_records_ui_provenance_from_the_caller(self) -> None:
        event = make_created(source=Provenance.UI, changed_by="ui")

        assert event.event_data["source"] == "ui"
        assert event.event_data["changed_by"] == "ui"

    def test_records_mcp_provenance_from_the_caller(self) -> None:
        event = make_created(source=Provenance.MCP, changed_by="mcp")

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    def test_occurred_at_is_timezone_aware_utc(self) -> None:
        """History rows take their timestamp from this field (Phase 6).

        A naive datetime would be written as whatever the projection host's
        clock happened to mean, so the awareness is part of the contract rather
        than an implementation detail.
        """
        event = make_created()

        assert isinstance(event.occurred_at, datetime)
        assert event.occurred_at.tzinfo is not None
        assert event.occurred_at.utcoffset() == timedelta(0)

    def test_carries_the_transaction_it_was_given(self) -> None:
        """Satisfies ``DomainEventProtocol``; it does **not** route the write.

        ``OutboxEventPublisher`` inserts on the connection *it* was constructed
        with and never reads this field — it is part of the protocol every
        domain event in this codebase implements, and is carried for that
        conformance alone. What actually puts the outbox row in the same
        transaction as the task row is that DI hands the publisher and the
        repositories the same request connection; that is asserted where it can
        be observed, in ``test_task_events_integration.py``.
        """
        transaction = AsyncMock()

        event = make_created(transaction=transaction)

        assert event.transaction is transaction

    def test_transaction_defaults_to_none(self) -> None:
        assert make_created().transaction is None


class TestTaskUpdated:
    """The single event a successful text and/or status change publishes.

    **One event, not one per field.** A ``PATCH`` may reword a task and complete
    it in the same request, and that is one write in one unit of work; publishing
    a separate event per changed field would announce two things happening where
    one did. ``JournalUpdated``, ``ContactUpdated``, ``RouteUpdated`` and
    ``GearItemUpdated`` all carry ``changed_fields`` for exactly this reason, and
    ``HistoryService._rows_from_changed_fields`` already fans that dict out into
    one ``field_history`` row per field — so the user still reads a distinct
    "text" line and a distinct "status" line in their history.
    """

    def test_identifies_itself_as_a_task_updated_event(self) -> None:
        event = make_updated()

        assert event.event_type == "TaskUpdated"
        assert event.event_id.startswith(f"task_updated_{TASK_ID}_")

    def test_aggregate_id_is_the_integer_task_id(self) -> None:
        event = make_updated()

        assert event.aggregate_id == TASK_ID
        assert isinstance(event.aggregate_id, int)

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """A whole-key comparison, as on the other two types.

        ``user_id`` is carried for the same reason it is on every task event:
        Phase 8 scopes a task-scoped history read by owner, and reading it off
        the event rather than the row is what lets that read answer for a task
        that has since been deleted.
        """
        event = make_updated()

        assert event.event_data == {
            "task_id": TASK_ID,
            "user_id": USER_ID,
            "changed_fields": TEXT_CHANGE,
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_a_reword_carries_only_the_text_field(self) -> None:
        event = make_updated(changed_fields=TEXT_CHANGE)

        assert list(event.event_data["changed_fields"]) == ["text"]

    def test_a_status_change_carries_only_the_status_field(self) -> None:
        event = make_updated(changed_fields=STATUS_CHANGE)

        assert list(event.event_data["changed_fields"]) == ["status"]

    def test_one_event_carries_both_fields_when_both_moved(self) -> None:
        """The assertion the one-event-per-write decision rests on.

        The event does not decide *what* changed — the service does — but it has
        to be able to say both in one payload, or the decision is not available
        to it.
        """
        event = make_updated(changed_fields={**TEXT_CHANGE, **STATUS_CHANGE})

        assert set(event.event_data["changed_fields"]) == {"text", "status"}

    def test_each_change_is_an_old_new_pair_in_that_order(self) -> None:
        """Asserted **positionally**, because that is how it is read.

        ``_rows_from_changed_fields`` guards ``len(change) == 2`` and then takes
        ``change[0]`` as the old value and ``change[1]`` as the new one. A pair
        written the other way round would project a history line claiming the
        user renamed their task back to what it was called before, and nothing
        downstream could tell.
        """
        event = make_updated(changed_fields={**TEXT_CHANGE, **STATUS_CHANGE})

        changed_fields = event.event_data["changed_fields"]
        for change in changed_fields.values():
            assert len(change) == 2
        assert changed_fields["text"][0] == ORIGINAL_TEXT
        assert changed_fields["text"][1] == UPDATED_TEXT
        assert changed_fields["status"][0] == TaskStatus.NOT_DONE.value
        assert changed_fields["status"][1] == TaskStatus.DONE.value

    def test_status_values_are_strings_rather_than_enum_members(self) -> None:
        """``json.dumps`` would refuse a ``TaskStatus``; the pair must be scalars."""
        event = make_updated(changed_fields=STATUS_CHANGE)

        old, new = event.event_data["changed_fields"]["status"]
        assert isinstance(old, str)
        assert isinstance(new, str)
        assert (old, new) == ("not_done", "done")

    def test_defaults_to_system_provenance(self) -> None:
        event = TaskUpdated(
            task_id=TASK_ID, user_id=USER_ID, changed_fields=TEXT_CHANGE
        )

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_records_ui_provenance_from_the_caller(self) -> None:
        event = make_updated(source=Provenance.UI, changed_by="ui")

        assert event.event_data["source"] == "ui"
        assert event.event_data["changed_by"] == "ui"

    def test_records_mcp_provenance_from_the_caller(self) -> None:
        event = make_updated(source=Provenance.MCP, changed_by="mcp")

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    def test_occurred_at_is_timezone_aware_utc(self) -> None:
        event = make_updated()

        assert isinstance(event.occurred_at, datetime)
        assert event.occurred_at.tzinfo is not None
        assert event.occurred_at.utcoffset() == timedelta(0)

    def test_carries_the_transaction_it_was_given(self) -> None:
        transaction = AsyncMock()

        event = make_updated(transaction=transaction)

        assert event.transaction is transaction


class TestTaskUpdatedCarriesContactMembership:
    """Linking and unlinking a contact are changes to a field of the task.

    **No event type of their own**, which is a divergence from this phase's
    criterion wording — *"event classes for contact linked and unlinked"* — and
    the same one Phase 2 made from *"event classes for text updated and status
    changed"*. The specification calls a task-contact link *"a plain reference"*
    with no relationship type, role or attendance status, and it has exactly one
    cause: somebody asking for it. There is nothing a dedicated type would carry
    that a ``changed_fields`` entry does not, and
    ``_rows_from_changed_fields`` already fans the dict out into one
    ``field_history`` row per key — so a reader still gets a line per person.

    **Not what Phase 4 did for journal links**, deliberately. Those *do* have
    their own types, because a journal link has structure to carry: an ``origin``
    (two writes cause it) and a place in the ordered pair a retarget publishes. A
    contact link has neither.
    """

    def test_a_link_is_a_none_to_id_pair_under_the_contacts_own_key(self) -> None:
        event = make_updated(changed_fields=CONTACT_LINKED)

        assert event.event_data["changed_fields"] == {
            f"contact:{CONTACT_ID}": (None, CONTACT_ID)
        }

    def test_an_unlink_is_the_same_pair_the_other_way_round(self) -> None:
        event = make_updated(changed_fields=CONTACT_UNLINKED)

        assert event.event_data["changed_fields"] == {
            f"contact:{CONTACT_ID}": (CONTACT_ID, None)
        }

    def test_the_direction_is_positional_like_every_other_pair(self) -> None:
        """The link and the unlink differ only by which side is ``None``.

        ``_rows_from_changed_fields`` reads ``change[0]`` as the old value and
        ``change[1]`` as the new one and never looks at the key, so the two
        directions are told apart by position alone. A pair built the wrong way
        round would render a link as a removal in the user's own history, and
        nothing downstream could notice.
        """
        linked = make_updated(changed_fields=CONTACT_LINKED)
        unlinked = make_updated(changed_fields=CONTACT_UNLINKED)

        assert linked.event_data["changed_fields"][f"contact:{CONTACT_ID}"][0] is None
        assert (
            linked.event_data["changed_fields"][f"contact:{CONTACT_ID}"][1]
            == CONTACT_ID
        )
        assert (
            unlinked.event_data["changed_fields"][f"contact:{CONTACT_ID}"][0]
            == CONTACT_ID
        )
        assert unlinked.event_data["changed_fields"][f"contact:{CONTACT_ID}"][1] is None

    def test_two_contacts_produce_two_keys_rather_than_one(self) -> None:
        """Why the key names the contact instead of being a shared ``contacts``.

        Phase 6 writes history rows ``ON CONFLICT (event_id, entity_type,
        entity_id, field_name) DO NOTHING``. Two people under one field name
        would collide on all four columns, and the second would be dropped as a
        redelivery of the first — one of them silently missing from the user's
        history. Keying by contact id costs nothing and removes the question,
        following the collection prefixes ``journal_write_service`` already uses
        (``plan:doc``, ``abseil:pitch``).
        """
        event = make_updated(
            changed_fields={
                f"contact:{CONTACT_ID}": (None, CONTACT_ID),
                f"contact:{OTHER_CONTACT_ID}": (None, OTHER_CONTACT_ID),
            }
        )

        assert set(event.event_data["changed_fields"]) == {
            f"contact:{CONTACT_ID}",
            f"contact:{OTHER_CONTACT_ID}",
        }

    def test_a_contact_change_sits_beside_a_text_change_without_merging(self) -> None:
        """One type now carries three kinds of change, and they stay separable.

        Nothing publishes a text change and a contact change together today —
        they are different write paths — but the projection Phase 6 builds reads
        one dict either way, and it has to produce a distinct row per key rather
        than one row per event.
        """
        event = make_updated(changed_fields={**TEXT_CHANGE, **CONTACT_LINKED})

        assert set(event.event_data["changed_fields"]) == {
            "text",
            f"contact:{CONTACT_ID}",
        }

    def test_the_payload_says_nothing_about_a_role_or_a_relationship(self) -> None:
        """The specification's *"plain reference"*, asserted rather than assumed.

        *"Task-contact links do not carry a relationship type, a role, or an
        attendance status."* The whole-key comparisons elsewhere in this class
        would fail on such a key; this states the rule directly so the next
        person to consider adding one meets the sentence rather than a diff.
        """
        event = make_updated(changed_fields=CONTACT_LINKED)

        assert set(event.event_data) == {
            "task_id",
            "user_id",
            "changed_fields",
            "source",
            "changed_by",
        }

    def test_records_the_provenance_of_whoever_linked(self) -> None:
        event = make_updated(
            changed_fields=CONTACT_LINKED, source=Provenance.MCP, changed_by="mcp"
        )

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"


class TestTaskDueJournalRetargeted:
    """The anchor half of what a successful retarget publishes.

    **One of two events now.** A retarget does two things — moves the due anchor
    and retains the journal it left as an intermediate link — and this event
    announces only the first. The link is a ``TaskJournalLinked`` of its own,
    published before this one because the service writes the link first. The two
    payload keys that stood in for it while that type did not exist,
    ``auto_linked_journal_id`` and ``auto_link_created``, are gone: the first is
    the link event's ``journal_id`` and the second is answered by whether a link
    event exists at all.

    **The event builds its own ``changed_fields``**, unlike ``TaskUpdated``,
    which is handed one. Retargeting's "always lands not done" is a property of
    the operation rather than a decision the caller makes, so the rule that a
    ``status`` pair appears only when the status actually moved lives here, in
    one place, and is asserted directly.
    """

    def test_identifies_itself_as_a_retarget_event(self) -> None:
        event = make_retargeted()

        assert event.event_type == "TaskDueJournalRetargeted"
        assert event.event_id.startswith(f"task_due_journal_retargeted_{TASK_ID}_")

    def test_aggregate_id_is_the_integer_task_id(self) -> None:
        """The task, not either journal.

        Both journals appear in the payload and neither is the aggregate: the
        history this projects is the *task's*, and filing it under a journal
        would put a task's trail on a page that merely hosted one step of it.
        """
        event = make_retargeted()

        assert event.aggregate_id == TASK_ID
        assert isinstance(event.aggregate_id, int)

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """A whole-key comparison, as on the other three types.

        The two auto-link keys the previous phase put here are **absent**, and
        their absence is the point of this assertion rather than a tidy-up: a
        retarget that carried them *and* published a ``TaskJournalLinked`` would
        put the same link into a reader's hands twice, in two shapes, and only
        one of them would be an event the projection knows how to read.
        """
        event = make_retargeted()

        assert event.event_data == {
            "task_id": TASK_ID,
            "user_id": USER_ID,
            "changed_fields": {"due_journal_id": (DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID)},
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_the_due_journal_pair_is_old_then_new(self) -> None:
        """Positionally, for the reason ``TaskUpdated``'s pairs are.

        ``_rows_from_changed_fields`` reads ``change[0]`` as the old value and
        ``change[1]`` as the new one. Reversed, a user's history would say they
        moved the task *back* to the journal they had just left.
        """
        change = make_retargeted().event_data["changed_fields"]["due_journal_id"]

        assert len(change) == 2
        assert change[0] == DUE_JOURNAL_ID
        assert change[1] == NEW_DUE_JOURNAL_ID

    def test_a_retarget_of_a_not_done_task_names_no_status_change(self) -> None:
        """Nothing moved, so nothing is announced.

        Retargeting always *lands* not done, but a task that was already not
        done had no status change — and a payload that said otherwise would put
        a "not done → not done" line in the user's history for every deferral.
        """
        event = make_retargeted(previous_status=TaskStatus.NOT_DONE)

        assert list(event.event_data["changed_fields"]) == ["due_journal_id"]

    def test_reopening_a_done_task_puts_the_status_change_in_the_stream(self) -> None:
        """The phase's third criterion, at the event.

        A retarget that reopens a completed task is the case the specification
        singles out as "rarely what the user meant", and the one the UI has to
        confirm before it happens. If the reopen were visible only in the task
        row, a person reading their own history would see the date move and no
        record that their completion was undone.
        """
        event = make_retargeted(previous_status=TaskStatus.DONE)

        change = event.event_data["changed_fields"]["status"]
        assert change[0] == TaskStatus.DONE.value
        assert change[1] == TaskStatus.NOT_DONE.value

    def test_reopening_a_cancelled_task_puts_the_status_change_in_the_stream(
        self,
    ) -> None:
        """The other reopen, which needs no acknowledgement but the same record.

        Retargeting is the documented way out of cancelled, so this path is
        *ordinary* rather than exceptional — which is exactly why it would be
        easy to leave out of the payload.
        """
        event = make_retargeted(previous_status=TaskStatus.CANCELLED)

        change = event.event_data["changed_fields"]["status"]
        assert change[0] == TaskStatus.CANCELLED.value
        assert change[1] == TaskStatus.NOT_DONE.value

    def test_a_reopen_carries_both_pairs_in_one_payload(self) -> None:
        """One write, one event, both facts."""
        event = make_retargeted(previous_status=TaskStatus.DONE)

        assert set(event.event_data["changed_fields"]) == {"due_journal_id", "status"}

    def test_status_values_are_plain_strings_not_task_status_members(self) -> None:
        """``type() is str``, not ``isinstance``, because the enum *is* a ``str``.

        ``TaskStatus`` is a ``StrEnum``, so ``isinstance(TaskStatus.DONE, str)``
        is true and ``json.dumps`` emits ``"done"`` for the member unchanged —
        an ``isinstance`` assertion here would pass against a payload carrying
        the member itself, and so would the whole-key comparison above, since a
        ``StrEnum`` compares equal to its value.

        The distinction is still worth pinning: the payload is a wire format, and
        a member reaching it hands an in-process subscriber a domain type where
        one that read the same event back out of Redis gets a bare string.
        """
        change = make_retargeted(previous_status=TaskStatus.DONE).event_data[
            "changed_fields"
        ]["status"]

        assert type(change[0]) is str
        assert type(change[1]) is str

    def test_says_nothing_about_the_link_the_retarget_retained(self) -> None:
        """The auto-link keys are gone, named rather than merely dropped.

        The whole-key assertion above already fails if either comes back, but it
        fails as "the payload changed". This one says *which* keys must not
        return and why: the retained journal is announced by its own
        ``TaskJournalLinked``, so a reader that found it here as well would have
        to decide which of the two to believe when they disagreed.
        """
        payload = make_retargeted().event_data

        assert "auto_linked_journal_id" not in payload
        assert "auto_link_created" not in payload

    def test_defaults_to_system_provenance(self) -> None:
        event = TaskDueJournalRetargeted(
            task_id=TASK_ID,
            user_id=USER_ID,
            previous_due_journal_id=DUE_JOURNAL_ID,
            due_journal_id=NEW_DUE_JOURNAL_ID,
            previous_status=TaskStatus.NOT_DONE,
        )

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_records_ui_provenance_from_the_caller(self) -> None:
        event = make_retargeted(source=Provenance.UI, changed_by="ui")

        assert event.event_data["source"] == "ui"
        assert event.event_data["changed_by"] == "ui"

    def test_records_mcp_provenance_from_the_caller(self) -> None:
        event = make_retargeted(source=Provenance.MCP, changed_by="mcp")

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    def test_occurred_at_is_timezone_aware_utc(self) -> None:
        event = make_retargeted()

        assert isinstance(event.occurred_at, datetime)
        assert event.occurred_at.tzinfo is not None
        assert event.occurred_at.utcoffset() == timedelta(0)

    def test_carries_the_transaction_it_was_given(self) -> None:
        transaction = AsyncMock()

        event = make_retargeted(transaction=transaction)

        assert event.transaction is transaction

    def test_transaction_defaults_to_none(self) -> None:
        assert make_retargeted().transaction is None


class TestTaskJournalLinked:
    """The event published when a journal becomes an intermediate link.

    **Two ways in, one type.** A person attaches a journal the task was
    discussed in, or a retarget retains the journal the task has just left —
    the model's one automatic link. Both are the same fact about the task, so
    both publish this, and ``origin`` says which happened.

    **``origin`` is not provenance.** ``source`` records *who acted*, and a
    retarget is something the user did: a link derived from a retarget somebody
    performed in the browser is ``ui``, not ``system``, because filing it under
    the system would tell that user's own history that half of one action was
    not theirs. ``SYSTEM`` is for a write no person triggered — an integration
    sync — which a retarget is not. What is genuinely derived is the link's
    *cause*, and that is what ``origin`` carries.
    """

    def test_identifies_itself_as_a_journal_linked_event(self) -> None:
        event = make_linked()

        assert event.event_type == "TaskJournalLinked"
        assert event.event_id.startswith(
            f"task_journal_linked_{TASK_ID}_{INTERMEDIATE_JOURNAL_ID}_"
        )

    def test_aggregate_id_is_the_integer_task_id(self) -> None:
        """The task, not the journal that was linked to it.

        The tempting alternative is real: this event names a journal, and a
        journal is an aggregate elsewhere in this codebase. Filing it there
        would put a task's trail on the journal's history page and leave the
        task's own read surface (Phase 8) unable to find it at all.
        """
        event = make_linked()

        assert event.aggregate_id == TASK_ID
        assert type(event.aggregate_id) is int

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """A whole-key comparison, as on every other type in this module."""
        event = make_linked()

        assert event.event_data == {
            "task_id": TASK_ID,
            "user_id": USER_ID,
            "journal_id": INTERMEDIATE_JOURNAL_ID,
            "origin": "manual",
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_a_retarget_derived_link_names_its_cause(self) -> None:
        """The one thing separating the two ways this event is reached.

        Without it a reader has an event saying "this journal became a link"
        and no way to tell a deliberate attach from the automatic retention a
        deferral performed — which is the distinction the phase's second
        criterion exists to preserve.
        """
        event = make_linked(origin=TaskJournalLinkOrigin.RETARGET)

        assert event.event_data["origin"] == "retarget"

    def test_a_derived_link_keeps_the_actor_that_triggered_it(self) -> None:
        """A ``ui`` retarget produces a ``ui`` link. The divergence, asserted.

        The phase's criterion words this distinction as being carried "with
        provenance", which would make this ``system``. It is not, deliberately:
        the retarget event published alongside says ``ui``, and two events of
        one user action disagreeing about who performed it is worse than the
        wording being followed literally. This is the test that fails if someone
        later "corrects" it back.
        """
        event = make_linked(
            origin=TaskJournalLinkOrigin.RETARGET,
            source=Provenance.UI,
            changed_by="ui",
        )

        assert event.event_data["source"] == "ui"
        assert event.event_data["changed_by"] == "ui"

    def test_origin_reaches_the_payload_as_a_plain_string(self) -> None:
        """``type() is str``, not ``isinstance``, for the ``StrEnum`` reason.

        ``TaskJournalLinkOrigin`` is a ``StrEnum``, so a member left in the
        payload is ``isinstance(..., str)``, serialises to the same JSON and
        compares equal to its value — the whole-key assertion above would not
        catch it either. The payload is a wire format: a member in it hands an
        in-process subscriber a domain type where a reader coming back through
        Redis gets a bare string.
        """
        for origin in TaskJournalLinkOrigin:
            assert type(make_linked(origin=origin).event_data["origin"]) is str

    def test_origin_has_no_default(self) -> None:
        """A caller that forgets must fail loudly, not file a retarget as manual.

        Every other optional argument on these events defaults to the safest
        reading. There is no safe default here: whichever value were chosen,
        the *other* caller would silently publish a lie about why the link
        exists, and nothing downstream could recover it.
        """
        with pytest.raises(TypeError):
            TaskJournalLinked(  # type: ignore[call-arg]
                task_id=TASK_ID,
                user_id=USER_ID,
                journal_id=INTERMEDIATE_JOURNAL_ID,
            )

    def test_defaults_to_system_provenance(self) -> None:
        event = TaskJournalLinked(
            task_id=TASK_ID,
            user_id=USER_ID,
            journal_id=INTERMEDIATE_JOURNAL_ID,
            origin=TaskJournalLinkOrigin.MANUAL,
        )

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_records_ui_provenance_from_the_caller(self) -> None:
        event = make_linked(source=Provenance.UI, changed_by="ui")

        assert event.event_data["source"] == "ui"
        assert event.event_data["changed_by"] == "ui"

    def test_records_mcp_provenance_from_the_caller(self) -> None:
        event = make_linked(source=Provenance.MCP, changed_by="mcp")

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    def test_occurred_at_is_timezone_aware_utc(self) -> None:
        event = make_linked()

        assert isinstance(event.occurred_at, datetime)
        assert event.occurred_at.tzinfo is not None
        assert event.occurred_at.utcoffset() == timedelta(0)

    def test_carries_the_transaction_it_was_given(self) -> None:
        transaction = AsyncMock()

        event = make_linked(transaction=transaction)

        assert event.transaction is transaction

    def test_transaction_defaults_to_none(self) -> None:
        assert make_linked().transaction is None


class TestTaskJournalUnlinked:
    """The event published when an intermediate link is removed.

    **No ``origin``, deliberately.** The linked event has two causes and needs
    to name one. This has exactly one — a user asking for the link to go —
    because the other two things that remove a link publish nothing at all
    today: a journal merge collapsing redundant links, which is a later phase's
    to give an event to, and a journal delete cascading, which removes the row
    from underneath the task without anyone acting on the task. A key with a
    single possible value would advertise a second case that does not exist.
    """

    def test_identifies_itself_as_a_journal_unlinked_event(self) -> None:
        event = make_unlinked()

        assert event.event_type == "TaskJournalUnlinked"
        assert event.event_id.startswith(
            f"task_journal_unlinked_{TASK_ID}_{INTERMEDIATE_JOURNAL_ID}_"
        )

    def test_aggregate_id_is_the_integer_task_id(self) -> None:
        event = make_unlinked()

        assert event.aggregate_id == TASK_ID
        assert type(event.aggregate_id) is int

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """A whole-key comparison — and the one that pins ``origin``'s absence."""
        event = make_unlinked()

        assert event.event_data == {
            "task_id": TASK_ID,
            "user_id": USER_ID,
            "journal_id": INTERMEDIATE_JOURNAL_ID,
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_defaults_to_system_provenance(self) -> None:
        event = TaskJournalUnlinked(
            task_id=TASK_ID,
            user_id=USER_ID,
            journal_id=INTERMEDIATE_JOURNAL_ID,
        )

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_records_ui_provenance_from_the_caller(self) -> None:
        event = make_unlinked(source=Provenance.UI, changed_by="ui")

        assert event.event_data["source"] == "ui"
        assert event.event_data["changed_by"] == "ui"

    def test_records_mcp_provenance_from_the_caller(self) -> None:
        event = make_unlinked(source=Provenance.MCP, changed_by="mcp")

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    def test_occurred_at_is_timezone_aware_utc(self) -> None:
        event = make_unlinked()

        assert isinstance(event.occurred_at, datetime)
        assert event.occurred_at.tzinfo is not None
        assert event.occurred_at.utcoffset() == timedelta(0)

    def test_carries_the_transaction_it_was_given(self) -> None:
        transaction = AsyncMock()

        event = make_unlinked(transaction=transaction)

        assert event.transaction is transaction

    def test_transaction_defaults_to_none(self) -> None:
        assert make_unlinked().transaction is None


class TestTaskJournalLinksRepointed:
    """The event a journal merge publishes about each task it moved.

    **Not a retarget, and that is the first thing to pin.** A merge does not
    force the task *not done*, it can move the **creating** anchor — the one
    field the specification calls set once and never changed — and it can
    *delete* links. Publishing ``TaskDueJournalRetargeted`` would tell a user
    they deferred a task they never touched.

    **The payload is ``changed_fields``, like the retarget's**, so the
    projection reuses ``_project_task_updated`` rather than growing a parallel
    shape for the same kind of fact. What each key means is the merge's own
    vocabulary: the anchors carry the ``(absorbed, survivor)`` pair, and each
    intermediate link is a ``journal:{id}`` row in the direction it moved — the
    same key a manual attach and detach land under, so a merge's removal and a
    person's removal of the same journal read as the same kind of line.
    """

    def test_identifies_itself_as_a_repointing_event(self) -> None:
        event = make_repointed()

        assert event.event_type == "TaskJournalLinksRepointed"
        assert event.event_id.startswith(
            f"task_journal_links_repointed_{TASK_ID}_{ABSORBED_JOURNAL_ID}_"
        )

    def test_aggregate_id_is_the_integer_task_id(self) -> None:
        """The task, not either journal.

        This is the phase's whole point: the merge already publishes under both
        journal ids, and that is exactly why the affected tasks' own histories
        never mention it.
        """
        event = make_repointed()

        assert event.aggregate_id == TASK_ID
        assert type(event.aggregate_id) is int

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """A whole-key comparison, as on every other type in this module.

        The two journal ids are here as well as inside ``changed_fields``
        because they say *why* the fields moved — this task was caught in a
        merge of these two journals — which no ``(old, new)`` pair carries on
        its own.
        """
        event = make_repointed()

        assert event.event_data == {
            "task_id": TASK_ID,
            "user_id": USER_ID,
            "source_journal_id": ABSORBED_JOURNAL_ID,
            "target_journal_id": SURVIVING_JOURNAL_ID,
            "changed_fields": {
                "due_journal_id": (ABSORBED_JOURNAL_ID, SURVIVING_JOURNAL_ID)
            },
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_a_moved_creating_anchor_is_named_as_itself(self) -> None:
        """The field the specification calls immutable, moving.

        A merge is its sole legitimate exception, which is precisely the kind of
        exception a history exists to record — so it gets its own key rather
        than being folded into the due anchor's.
        """
        event = make_repointed(creating_anchor_moved=True)

        assert event.event_data["changed_fields"] == {
            "creating_journal_id": (ABSORBED_JOURNAL_ID, SURVIVING_JOURNAL_ID)
        }

    def test_both_anchors_moving_produces_both_lines(self) -> None:
        """A task anchored to the absorbed journal in both roles.

        The specification permits the survivor becoming both, and the two
        changes are two lines because they are two facts about the task.
        """
        event = make_repointed(creating_anchor_moved=True, due_anchor_moved=True)

        assert event.event_data["changed_fields"] == {
            "creating_journal_id": (ABSORBED_JOURNAL_ID, SURVIVING_JOURNAL_ID),
            "due_journal_id": (ABSORBED_JOURNAL_ID, SURVIVING_JOURNAL_ID),
        }

    def test_a_moved_intermediate_link_reads_as_a_departure_and_an_arrival(
        self,
    ) -> None:
        """Two rows, because a link is keyed by the journal it names.

        ``journal:{id}`` is one key per journal — history rows dedup on
        ``(event_id, entity_type, entity_id, field_name)``, so a shared
        ``"journals"`` key would drop the second of the pair as a redelivery of
        the first. The consequence here is that a link *moving* cannot be one
        row: it is the absorbed journal leaving and the survivor arriving, which
        is also what actually happened to the rows in the table.
        """
        event = make_repointed(source_link_removed=True, target_link_added=True)

        assert event.event_data["changed_fields"] == {
            journal_field_name(ABSORBED_JOURNAL_ID): (ABSORBED_JOURNAL_ID, None),
            journal_field_name(SURVIVING_JOURNAL_ID): (None, SURVIVING_JOURNAL_ID),
        }

    def test_a_link_collapsed_as_a_duplicate_records_only_the_departure(
        self,
    ) -> None:
        """The task was linked to both journals, so nothing arrived.

        The survivor's link was already there and stays; only the absorbed
        journal's row is gone. Writing an arrival too would put a second
        "linked" line in a history that already has one, for a link the user
        never gained.
        """
        event = make_repointed(source_link_removed=True)

        assert event.event_data["changed_fields"] == {
            journal_field_name(ABSORBED_JOURNAL_ID): (ABSORBED_JOURNAL_ID, None)
        }

    def test_a_link_dropped_as_redundant_reads_as_a_removal(self) -> None:
        """The survivor became one of the task's anchors, so the weaker claim goes.

        "The task was mentioned in this journal" is what the anchor role already
        says, more strongly. The link really is deleted, so a task's trail would
        otherwise lose a journal it passed through with nothing to explain the
        loss — the third of the three consequences this phase exists to close.
        """
        event = make_repointed(due_anchor_moved=True, target_link_removed=True)

        assert event.event_data["changed_fields"] == {
            "due_journal_id": (ABSORBED_JOURNAL_ID, SURVIVING_JOURNAL_ID),
            journal_field_name(SURVIVING_JOURNAL_ID): (SURVIVING_JOURNAL_ID, None),
        }

    def test_a_link_moved_and_then_dropped_records_only_the_departure(self) -> None:
        """The one case where two statements cancel, and the net effect is the truth.

        The task's link is re-pointed onto the survivor and the redundancy
        cleanup immediately removes it, because an anchor moved onto the same
        journal. It never existed on the survivor between two committed states,
        so announcing an arrival and a removal would invent a link the user
        never had.
        """
        event = make_repointed(due_anchor_moved=True, source_link_removed=True)

        assert event.event_data["changed_fields"] == {
            "due_journal_id": (ABSORBED_JOURNAL_ID, SURVIVING_JOURNAL_ID),
            journal_field_name(ABSORBED_JOURNAL_ID): (ABSORBED_JOURNAL_ID, None),
        }

    def test_the_pairs_are_old_then_new_positionally(self) -> None:
        """Direction is carried by position and by nothing else.

        ``_rows_from_changed_fields`` reads ``change[0]`` as the old value and
        never looks at the key, so a pair built the wrong way round renders the
        merge as having moved the task *out of* the surviving journal, with
        nothing downstream able to notice.
        """
        change = make_repointed().event_data["changed_fields"]["due_journal_id"]

        assert change[0] == ABSORBED_JOURNAL_ID
        assert change[1] == SURVIVING_JOURNAL_ID

    def test_it_carries_the_provenance_of_the_merge_that_caused_it(self) -> None:
        """A merge in the browser and one over MCP are distinguishable here.

        The merge is a write the user performed on a *journal*; the tasks it
        moved are consequences of that action, so they carry the actor who
        performed it rather than ``system``. Same reasoning as the link a
        retarget retains.
        """
        event = make_repointed(source=Provenance.MCP, changed_by="mcp")

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    def test_provenance_defaults_to_the_system(self) -> None:
        event = make_repointed()

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_carries_the_transaction_it_was_given(self) -> None:
        transaction = AsyncMock()

        event = make_repointed(transaction=transaction)

        assert event.transaction is transaction

    def test_transaction_defaults_to_none(self) -> None:
        assert make_repointed().transaction is None


class TestTaskDeleted:
    """The event a successful hard delete publishes."""

    def test_identifies_itself_as_a_task_deleted_event(self) -> None:
        event = make_deleted()

        assert event.event_type == "TaskDeleted"
        assert event.event_id.startswith(f"task_deleted_{TASK_ID}_")

    def test_aggregate_id_is_the_integer_task_id(self) -> None:
        event = make_deleted()

        assert event.aggregate_id == TASK_ID
        assert isinstance(event.aggregate_id, int)

    def test_payload_carries_exactly_the_documented_keys(self) -> None:
        """Deliberately minimal — the task itself is already gone.

        ``delete_task`` reads nothing before deleting, so there is no text or
        anchor to carry without adding the read that decision rejected.
        ``user_id`` is here because Phase 8 must read a hard-deleted task's
        history with no task row left to scope it by.
        """
        event = make_deleted()

        assert event.event_data == {
            "task_id": TASK_ID,
            "user_id": USER_ID,
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_defaults_to_system_provenance(self) -> None:
        event = TaskDeleted(task_id=TASK_ID, user_id=USER_ID)

        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    def test_records_ui_provenance_from_the_caller(self) -> None:
        event = make_deleted(source=Provenance.UI, changed_by="ui")

        assert event.event_data["source"] == "ui"
        assert event.event_data["changed_by"] == "ui"

    def test_records_mcp_provenance_from_the_caller(self) -> None:
        event = make_deleted(source=Provenance.MCP, changed_by="mcp")

        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    def test_occurred_at_is_timezone_aware_utc(self) -> None:
        event = make_deleted()

        assert isinstance(event.occurred_at, datetime)
        assert event.occurred_at.tzinfo is not None
        assert event.occurred_at.utcoffset() == timedelta(0)

    def test_carries_the_transaction_it_was_given(self) -> None:
        transaction = AsyncMock()

        event = make_deleted(transaction=transaction)

        assert event.transaction is transaction


class TestEventIdentity:
    """``event_id`` is what dedup keys on, so collisions are the risk."""

    def test_a_create_and_a_delete_of_one_task_never_collide(self) -> None:
        """Same aggregate id, same clock tick — only the prefix separates them.

        Phase 6 writes history rows ``ON CONFLICT DO NOTHING`` over
        ``(event_id, entity_type, entity_id, field_name)``. Two events sharing an
        id would let the second be dropped as a redelivery of the first, so a
        task's deletion could vanish from its own history.
        """
        ids = {
            make_created().event_id,
            make_updated().event_id,
            make_retargeted().event_id,
            make_linked().event_id,
            make_unlinked().event_id,
            make_repointed().event_id,
            make_deleted().event_id,
        }

        assert len(ids) == 7

    def test_an_id_is_separated_from_its_neighbours_by_its_own_timestamp(self) -> None:
        """Two events of one type on one task are told apart by ``occurred_at``.

        Asserted through the id's *composition* rather than by building two
        events and comparing them: that comparison is a clock race — the
        timestamp has microsecond resolution and two constructions in a row can
        land in the same one — and a test that usually passes is worse than no
        test. This says the same thing deterministically.
        """
        event = make_created()

        assert (
            event.event_id == f"task_created_{TASK_ID}_{event.occurred_at.isoformat()}"
        )

    def test_ids_are_scoped_to_their_task(self) -> None:
        other = TaskDeleted(task_id=TASK_ID + 1, user_id=USER_ID)

        assert make_deleted().event_id != other.event_id

    def test_a_retarget_id_is_composed_the_same_way_as_the_others(self) -> None:
        """Same deterministic composition, asserted rather than raced.

        Two retargets of one task are separated only by ``occurred_at``, and
        constructing two in a row to compare them is a microsecond-resolution
        clock race. This says the same thing without one.
        """
        event = make_retargeted()

        assert (
            event.event_id
            == f"task_due_journal_retargeted_{TASK_ID}_{event.occurred_at.isoformat()}"
        )

    def test_a_link_id_names_the_journal_as_well_as_the_task(self) -> None:
        """The one type whose id needs more than the task and the clock.

        Every other event on a task is *about* the task, so two of a kind on one
        task are separated by time alone. Two links are not: a task can gain
        several journals, and if two of those writes ever shared a microsecond
        the pair would collide — and Phase 6's ``ON CONFLICT DO NOTHING`` over
        ``event_id`` would silently drop one link from the user's history as a
        redelivery of the other. The journal id costs nothing and removes the
        question.
        """
        event = make_linked()

        assert event.event_id == (
            f"task_journal_linked_{TASK_ID}_{INTERMEDIATE_JOURNAL_ID}_"
            f"{event.occurred_at.isoformat()}"
        )

    def test_an_unlink_id_is_composed_the_same_way(self) -> None:
        event = make_unlinked()

        assert event.event_id == (
            f"task_journal_unlinked_{TASK_ID}_{INTERMEDIATE_JOURNAL_ID}_"
            f"{event.occurred_at.isoformat()}"
        )

    def test_a_repointing_id_names_the_absorbed_journal_as_well_as_the_task(
        self,
    ) -> None:
        """The second type whose id needs more than the task and the clock.

        One merge publishes at most one of these per task, so the clock would do
        — but ``auto_merge_review_items`` performs *several* merges in one unit
        of work, and a task caught in two of them would publish two of these.
        Each merge absorbs a different journal, so naming the absorbed one
        removes the question that ``ON CONFLICT DO NOTHING`` over ``event_id``
        would otherwise answer by dropping one of the two.
        """
        event = make_repointed()

        assert event.event_id == (
            f"task_journal_links_repointed_{TASK_ID}_{ABSORBED_JOURNAL_ID}_"
            f"{event.occurred_at.isoformat()}"
        )

    def test_two_merges_touching_one_task_are_told_apart_by_the_id_alone(self) -> None:
        """Deterministic, as with the link ids: one timestamp, two journals."""
        event = make_repointed()
        other = f"task_journal_links_repointed_{TASK_ID}_{ABSORBED_JOURNAL_ID + 1}_"

        assert not event.event_id.startswith(other)

    def test_links_to_two_journals_are_told_apart_by_the_id_alone(self) -> None:
        """Deterministic, unlike constructing two and racing the clock.

        Both ids are built here from *one* event's timestamp, so the assertion
        is about the journal id doing the separating rather than about how fast
        two constructions happen to run.
        """
        event = make_linked()
        other = f"task_journal_linked_{TASK_ID}_{INTERMEDIATE_JOURNAL_ID + 1}_"

        assert not event.event_id.startswith(other)


class TestPayloadSurvivesTheStream:
    """The projection sees JSON, not these objects."""

    def test_created_payload_round_trips_through_json_unchanged(self) -> None:
        event = make_created(source=Provenance.UI, changed_by="ui")

        assert json.loads(json.dumps(event.event_data)) == event.event_data

    def test_deleted_payload_round_trips_through_json_unchanged(self) -> None:
        event = make_deleted(source=Provenance.MCP, changed_by="mcp")

        assert json.loads(json.dumps(event.event_data)) == event.event_data

    def test_updated_payload_reaches_the_stream_with_both_pairs_intact(self) -> None:
        """Asserted against the *arrived* form, not for equality with the sent one.

        The other two types round trip to something equal to themselves. This one
        cannot: the pairs are built as tuples, following ``JournalUpdated`` and
        ``ContactUpdated``, and ``json.dumps`` writes a tuple as an array that
        ``json.loads`` reads back as a ``list`` — and ``("a", "b") == ["a", "b"]``
        is ``False``. Nothing downstream cares, because the projection indexes
        rather than compares, so the payload keeps the domain's convention and
        the test states what actually arrives.
        """
        event = make_updated(
            changed_fields={**TEXT_CHANGE, **STATUS_CHANGE},
            source=Provenance.UI,
            changed_by="ui",
        )

        round_tripped = json.loads(json.dumps(event.event_data))

        assert round_tripped["changed_fields"] == {
            "text": [ORIGINAL_TEXT, UPDATED_TEXT],
            "status": ["not_done", "done"],
        }

    def test_a_status_pair_reaches_the_projection_as_an_indexable_two_list(
        self,
    ) -> None:
        """The phase's own criterion, asserted in the form that reads it.

        "``[old, new]`` after the JSON round trip through Redis" is not a
        statement about tuples — it is a statement about what
        ``_rows_from_changed_fields`` finds when it applies its
        ``isinstance(change, (list, tuple)) and len(change) == 2`` guard and then
        indexes. This asserts that, so a payload that arrived as a dict
        ``{"old": ..., "new": ...}``, or as a bare string, fails here rather than
        by silently projecting no rows at all.
        """
        event = make_updated(changed_fields=STATUS_CHANGE)

        change = json.loads(json.dumps(event.event_data))["changed_fields"]["status"]

        assert isinstance(change, list)
        assert len(change) == 2
        assert change[0] == TaskStatus.NOT_DONE.value
        assert change[1] == TaskStatus.DONE.value

    def test_a_contact_pair_reaches_the_projection_as_an_indexable_two_list(
        self,
    ) -> None:
        """The same guard the status pair has to satisfy, for the same reason.

        ``_rows_from_changed_fields`` applies ``len(change) == 2`` and then
        indexes; a payload shaped any other way does not raise there, it projects
        **no rows at all** — a contact silently missing from a task's history
        rather than a failure anybody would see. The ``None`` half is the part
        worth checking survives: JSON writes it as ``null`` and reads it back as
        ``None``, which is what makes the "there was nobody here before"
        direction legible downstream.
        """
        event = make_updated(changed_fields=CONTACT_LINKED)

        change = json.loads(json.dumps(event.event_data))["changed_fields"][
            f"contact:{CONTACT_ID}"
        ]

        assert isinstance(change, list)
        assert len(change) == 2
        assert change[0] is None
        assert change[1] == CONTACT_ID

    def test_an_unlink_pair_arrives_with_the_none_on_the_new_side(self) -> None:
        event = make_updated(changed_fields=CONTACT_UNLINKED)

        change = json.loads(json.dumps(event.event_data))["changed_fields"][
            f"contact:{CONTACT_ID}"
        ]

        assert change[0] == CONTACT_ID
        assert change[1] is None

    def test_created_contacts_arrive_as_a_list_of_plain_integers(self) -> None:
        """What Phase 6 will read off a create to know who was on the task."""
        event = make_created(contact_ids=[CONTACT_ID, OTHER_CONTACT_ID])

        arrived = json.loads(json.dumps(event.event_data))["contact_ids"]

        assert arrived == [CONTACT_ID, OTHER_CONTACT_ID]
        assert all(type(contact_id) is int for contact_id in arrived)

    def test_a_retarget_reaches_the_stream_with_both_pairs_intact(self) -> None:
        """The reopen case, in the form the projection will actually receive.

        Asserted against the *arrived* shape rather than for equality with the
        sent one, for the reason the update test gives: the pairs are tuples and
        JSON has no tuple, so they arrive as lists — which is what
        ``_rows_from_changed_fields`` indexes into.
        """
        event = make_retargeted(
            previous_status=TaskStatus.DONE, source=Provenance.MCP, changed_by="mcp"
        )

        round_tripped = json.loads(json.dumps(event.event_data))

        assert round_tripped["changed_fields"] == {
            "due_journal_id": [DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID],
            "status": ["done", "not_done"],
        }

    def test_linked_payload_round_trips_through_json_unchanged(self) -> None:
        """All scalars, so it arrives equal to what was sent — pairs excepted.

        Asserted for the *derived* link with a user's provenance on it, because
        that combination is the one this phase invented and the one a reader
        will meet in the outbox.
        """
        event = make_linked(
            origin=TaskJournalLinkOrigin.RETARGET,
            source=Provenance.UI,
            changed_by="ui",
        )

        assert json.loads(json.dumps(event.event_data)) == event.event_data

    def test_unlinked_payload_round_trips_through_json_unchanged(self) -> None:
        event = make_unlinked(source=Provenance.MCP, changed_by="mcp")

        assert json.loads(json.dumps(event.event_data)) == event.event_data

    def test_origin_arrives_as_a_bare_string_rather_than_a_member(self) -> None:
        """What the projection actually reads, after Redis.

        The round trip above cannot catch a ``StrEnum`` member left in the
        payload — it serialises identically and compares equal to its value — so
        the type is asserted on the *arrived* object, which is where a consumer
        matching ``origin == "retarget"`` will look.
        """
        event = make_linked(origin=TaskJournalLinkOrigin.RETARGET)

        arrived = json.loads(json.dumps(event.event_data))["origin"]

        assert type(arrived) is str
        assert arrived == "retarget"

    def test_a_repointing_reaches_the_stream_with_every_pair_intact(self) -> None:
        """The busiest payload a merge can produce, in the form it arrives in.

        Both anchors moved and the task's intermediate link departed — three
        pairs under three keys, one of which is built from a journal id. If the
        keys collided or a pair arrived as anything but a two-element list, the
        projection would write fewer rows than the merge performed changes and
        nothing would report the shortfall.
        """
        event = make_repointed(
            creating_anchor_moved=True,
            due_anchor_moved=True,
            source_link_removed=True,
            source=Provenance.UI,
            changed_by="ui",
        )

        round_tripped = json.loads(json.dumps(event.event_data))

        assert round_tripped["changed_fields"] == {
            "creating_journal_id": [ABSORBED_JOURNAL_ID, SURVIVING_JOURNAL_ID],
            "due_journal_id": [ABSORBED_JOURNAL_ID, SURVIVING_JOURNAL_ID],
            journal_field_name(ABSORBED_JOURNAL_ID): [ABSORBED_JOURNAL_ID, None],
        }

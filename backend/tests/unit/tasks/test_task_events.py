"""Unit tests for the tasks domain's ``TaskCreated`` and ``TaskDeleted`` events.

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

Constants come from :mod:`tests.unit.tasks.task_doubles` so an event's idea of a
task and the service tests' idea of one cannot drift apart.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskStatus

from app.core.tasks.models.events import TaskCreated, TaskDeleted
from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    ORIGINAL_TEXT,
    TASK_ID,
    USER_ID,
)


def make_created(
    *,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
    status: TaskStatus = TaskStatus.NOT_DONE,
    transaction: AsyncMock | None = None,
) -> TaskCreated:
    """A ``TaskCreated`` over the shared task constants."""
    return TaskCreated(
        task_id=TASK_ID,
        user_id=USER_ID,
        text=ORIGINAL_TEXT,
        status=status,
        creating_journal_id=CREATING_JOURNAL_ID,
        due_journal_id=DUE_JOURNAL_ID,
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

        Later phases add event *types* rather than fields to this one; if one of
        them does need a field here, this test is where that decision is made
        visible instead of arriving unnoticed in the projection.
        """
        event = make_created()

        assert event.event_data == {
            "task_id": TASK_ID,
            "user_id": USER_ID,
            "text": ORIGINAL_TEXT,
            "status": TaskStatus.NOT_DONE.value,
            "creating_journal_id": CREATING_JOURNAL_ID,
            "due_journal_id": DUE_JOURNAL_ID,
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    def test_status_is_stored_as_its_string_value(self) -> None:
        """The enum is the argument; JSON is what the payload has to hold."""
        event = make_created(status=TaskStatus.NOT_DONE)

        assert event.event_data["status"] == "not_done"

    def test_defaults_to_system_provenance(self) -> None:
        event = TaskCreated(
            task_id=TASK_ID,
            user_id=USER_ID,
            text=ORIGINAL_TEXT,
            status=TaskStatus.NOT_DONE,
            creating_journal_id=CREATING_JOURNAL_ID,
            due_journal_id=DUE_JOURNAL_ID,
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
        created = make_created()
        deleted = make_deleted()

        assert created.event_id != deleted.event_id

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


class TestPayloadSurvivesTheStream:
    """The projection sees JSON, not these objects."""

    def test_created_payload_round_trips_through_json_unchanged(self) -> None:
        event = make_created(source=Provenance.UI, changed_by="ui")

        assert json.loads(json.dumps(event.event_data)) == event.event_data

    def test_deleted_payload_round_trips_through_json_unchanged(self) -> None:
        event = make_deleted(source=Provenance.MCP, changed_by="mcp")

        assert json.loads(json.dumps(event.event_data)) == event.event_data

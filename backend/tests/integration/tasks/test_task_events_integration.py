"""Integration tests for the task domain events, against a real outbox.

The unit tests own the payloads. What only a database can show:

- **the row is really there.** The service hands an object to a publisher; that
  the publisher turns it into an ``outbox_events`` row with the right type,
  aggregate id and JSON is a claim about an ``INSERT``, and the only place to
  check an ``INSERT`` is a database.
- **exactly one row per write.** A count is the assertion; "a ``TaskCreated``
  exists" would pass just as happily for a write that published twice.
- **the event and the write are one unit of work.** This is the acceptance
  criterion — *an event never exists for a write that rolled back* — and it is
  a property of a transaction, so nothing below a real one can demonstrate it.
  The tests roll back a **caller's** unit of work rather than reaching into the
  service, because that is the shape a request actually has: ``@transactional``
  is re-entrant, so the service joins the enclosing unit of work and its event
  lives or dies with it.

The payload is compared against the ``tasks`` row that was written, not against
the arguments the test passed, so a service that published a *different* task
than it saved could not pass.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    TaskDueJournalNotFutureError,
    TaskNotFoundError,
    TaskStatus,
    TaskStatusTransitionError,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.tasks.task_seeding import (
    COUNT_TASKS,
    USER_ID,
    count,
    create_journal,
    stored_text,
    task_events,
)

TASK_TEXT = "print the permit before the meeting"
UPDATED_TEXT = "print the permit and the map before the meeting"


async def _update(
    service: TaskService,
    connection: AsyncConnection,
    task_id: int,
    *,
    text: str | None = None,
    status: TaskStatus | None = None,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
) -> None:
    """Change a task through the service, naming whichever fields a test needs."""
    await service.update_task(
        user_id=USER_ID,
        task_id=task_id,
        text=text,
        status=status,
        transaction=connection,
        source=source,
        changed_by=changed_by,
    )


async def _create(
    service: TaskService,
    connection: AsyncConnection,
    anchors: tuple[int, int],
    *,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
) -> int:
    """Create a task through the service and return its id."""
    creating_id, due_id = anchors
    created = await service.create_task(
        user_id=USER_ID,
        creating_journal_id=creating_id,
        due_journal_id=due_id,
        text=TASK_TEXT,
        transaction=connection,
        source=source,
        changed_by=changed_by,
    )
    assert created.id is not None
    return created.id


@pytest.mark.integration
class TestCreationLeavesAnOutboxRow:
    """One create, one row, describing the task that was actually written."""

    @pytest.mark.asyncio
    async def test_exactly_one_task_created_row_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)

        events = await task_events(async_connection)
        assert [event.event_type for event in events] == ["TaskCreated"]
        assert events[0].aggregate_id == task_id

    @pytest.mark.asyncio
    async def test_the_payload_describes_the_row_that_was_saved(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Compared against the ``tasks`` row, not against the request.

        A service that published one task's details while saving another's would
        satisfy any assertion written against the arguments the test passed in.
        """
        creating_id, due_id = task_anchors
        task_id = await _create(service, async_connection, task_anchors)

        (event,) = await task_events(async_connection)
        assert event.payload == {
            "task_id": task_id,
            "user_id": USER_ID,
            "text": await stored_text(async_connection, task_id),
            "status": TaskStatus.NOT_DONE.value,
            "creating_journal_id": creating_id,
            "due_journal_id": due_id,
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    @pytest.mark.asyncio
    async def test_the_row_records_when_the_change_happened(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The column holds the *event's* clock, which Phase 6 projects from.

        Bracketing the call is the assertion. ``occurred_at`` is ``NOT NULL``, so
        checking it is merely present proves nothing — a column filled by a
        database default, or later by the projection, would satisfy that just as
        well and would date every history entry to when it was processed rather
        than when the user acted.

        The stored value is naive: the publisher strips the timezone on the way
        in, so it is compared against naive UTC bounds.
        """
        before = datetime.now(UTC).replace(tzinfo=None)
        await _create(service, async_connection, task_anchors)
        after = datetime.now(UTC).replace(tzinfo=None)

        (event,) = await task_events(async_connection)
        assert before <= event.occurred_at <= after

    @pytest.mark.asyncio
    async def test_the_row_is_written_on_the_same_connection_as_the_task(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Both are visible to this connection before anything commits.

        The outbox row is written by the request's own connection rather than a
        second one of the publisher's, which is the mechanical reason the two can
        share a transaction at all.
        """
        task_id = await _create(service, async_connection, task_anchors)

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 1
        assert len(await task_events(async_connection, task_id=task_id)) == 1


@pytest.mark.integration
class TestAnUpdateLeavesOneOutboxRow:
    """One ``PATCH`` is one row, however many fields it moved.

    The unit tests own the decision — what goes in ``changed_fields`` — and this
    owns the two things only a database shows: that the decision reaches
    ``outbox_events`` as a single row, and what the projection will actually read
    back out of the JSON column. That second one is the phase's own criterion:
    ``[old, new]`` **after** the round trip, not the tuple that went in.
    """

    @pytest.mark.asyncio
    async def test_a_reword_appends_exactly_one_task_updated_row(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)

        await _update(service, async_connection, task_id, text=UPDATED_TEXT)

        events = await task_events(async_connection, task_id=task_id)
        assert [event.event_type for event in events] == ["TaskCreated", "TaskUpdated"]
        assert events[-1].aggregate_id == task_id

    @pytest.mark.asyncio
    async def test_a_status_change_appends_exactly_one_task_updated_row(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        events = await task_events(async_connection, task_id=task_id)
        assert [event.event_type for event in events] == ["TaskCreated", "TaskUpdated"]

    @pytest.mark.asyncio
    async def test_rewording_and_completing_together_still_appends_one_row(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The one-event-per-write decision, asserted against the outbox itself.

        The service tests make this claim against a mock. Here it is the row
        count in a real table, which is what a consumer would actually see — and
        what a regression to per-field events would double.
        """
        task_id = await _create(service, async_connection, task_anchors)

        await _update(
            service,
            async_connection,
            task_id,
            text=UPDATED_TEXT,
            status=TaskStatus.DONE,
        )

        events = await task_events(async_connection, task_id=task_id)
        assert [event.event_type for event in events] == ["TaskCreated", "TaskUpdated"]
        assert set(events[-1].payload["changed_fields"]) == {"text", "status"}

    @pytest.mark.asyncio
    async def test_the_payload_describes_the_row_that_was_saved(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Whole-key, and the new text compared against the ``tasks`` row.

        A service that published one wording while saving another would satisfy
        an assertion written against the argument the test passed in.
        """
        task_id = await _create(service, async_connection, task_anchors)

        await _update(service, async_connection, task_id, text=UPDATED_TEXT)

        updated = (await task_events(async_connection, task_id=task_id))[-1]
        assert updated.payload == {
            "task_id": task_id,
            "user_id": USER_ID,
            "changed_fields": {
                "text": [TASK_TEXT, await stored_text(async_connection, task_id)]
            },
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    @pytest.mark.asyncio
    async def test_a_status_pair_reads_back_as_an_indexable_two_element_list(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The criterion, against a real round trip rather than an in-memory one.

        ``changed_fields`` is written as a tuple and stored as JSON, so what the
        history projection eventually receives is a ``list``. It reads that list
        by index, after guarding ``len(change) == 2`` — a payload shaped any
        other way would not raise there, it would silently project no rows at
        all. So the assertion is made in the form the guard applies.
        """
        task_id = await _create(service, async_connection, task_anchors)

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.CANCELLED,
            transaction=async_connection,
        )

        updated = (await task_events(async_connection, task_id=task_id))[-1]
        change = updated.payload["changed_fields"]["status"]
        assert isinstance(change, list)
        assert len(change) == 2
        assert change[0] == TaskStatus.NOT_DONE.value
        assert change[1] == TaskStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_the_row_records_when_the_change_happened(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Bracketed around the update alone, so the create's clock cannot pass it."""
        task_id = await _create(service, async_connection, task_anchors)

        before = datetime.now(UTC).replace(tzinfo=None)
        await _update(service, async_connection, task_id, text=UPDATED_TEXT)
        after = datetime.now(UTC).replace(tzinfo=None)

        updated = (await task_events(async_connection, task_id=task_id))[-1]
        assert before <= updated.occurred_at <= after

    @pytest.mark.asyncio
    async def test_a_create_reword_and_status_change_read_as_a_trail(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Three writes, three distinctly identified rows, in order.

        ``event_id`` is what the projection's ``ON CONFLICT DO NOTHING`` keys on,
        so two updates to one task sharing an id would let the second be dropped
        as a redelivery of the first — losing a change the user made.
        """
        task_id = await _create(service, async_connection, task_anchors)

        await _update(service, async_connection, task_id, text=UPDATED_TEXT)
        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        created, reworded, completed = await task_events(
            async_connection, task_id=task_id
        )
        assert [event.event_type for event in (created, reworded, completed)] == [
            "TaskCreated",
            "TaskUpdated",
            "TaskUpdated",
        ]
        assert created.occurred_at <= reworded.occurred_at <= completed.occurred_at
        assert len({reworded.event_id, completed.event_id}) == 2
        assert list(reworded.payload["changed_fields"]) == ["text"]
        assert list(completed.payload["changed_fields"]) == ["status"]


@pytest.mark.integration
class TestAnUpdateThatChangedNothingLeavesNoRow:
    """No write, no row — the half a "publishes an event" test cannot show."""

    @pytest.mark.asyncio
    async def test_resending_the_current_values_appends_nothing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)

        await _update(
            service,
            async_connection,
            task_id,
            text=TASK_TEXT,
            status=TaskStatus.NOT_DONE,
        )

        events = await task_events(async_connection, task_id=task_id)
        assert [event.event_type for event in events] == ["TaskCreated"]

    @pytest.mark.asyncio
    async def test_a_refused_transition_appends_nothing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Leaving cancelled is refused, and a refusal is not a change."""
        task_id = await _create(service, async_connection, task_anchors)
        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.CANCELLED,
            transaction=async_connection,
        )

        with pytest.raises(TaskStatusTransitionError):
            await service.set_status(
                user_id=USER_ID,
                task_id=task_id,
                status=TaskStatus.DONE,
                transaction=async_connection,
            )

        events = await task_events(async_connection, task_id=task_id)
        assert [event.event_type for event in events] == ["TaskCreated", "TaskUpdated"]

    @pytest.mark.asyncio
    async def test_an_update_to_an_unknown_task_appends_nothing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            await _update(service, async_connection, 999_999, text=UPDATED_TEXT)

        assert await task_events(async_connection) == []


@pytest.mark.integration
class TestDeletionLeavesAnOutboxRow:
    """The one change whose only record is its event."""

    @pytest.mark.asyncio
    async def test_exactly_one_task_deleted_row_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)

        await service.delete_task(
            user_id=USER_ID, task_id=task_id, transaction=async_connection
        )

        deletions = [
            event
            for event in await task_events(async_connection)
            if event.event_type == "TaskDeleted"
        ]
        assert len(deletions) == 1
        assert deletions[0].aggregate_id == task_id

    @pytest.mark.asyncio
    async def test_the_payload_is_the_task_and_its_owner(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)

        await service.delete_task(
            user_id=USER_ID, task_id=task_id, transaction=async_connection
        )

        deleted = (await task_events(async_connection))[-1]
        assert deleted.payload == {
            "task_id": task_id,
            "user_id": USER_ID,
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    @pytest.mark.asyncio
    async def test_the_event_outlives_the_row_it_describes(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Deletion is hard, so this row is all that is left of the task.

        The task-scoped history read added in a later phase depends on exactly
        this: history for a task whose row no longer exists.
        """
        task_id = await _create(service, async_connection, task_anchors)

        await service.delete_task(
            user_id=USER_ID, task_id=task_id, transaction=async_connection
        )

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert len(await task_events(async_connection, task_id=task_id)) == 2

    @pytest.mark.asyncio
    async def test_a_create_then_delete_reads_as_a_trail(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Ordered, and distinctly identified, so a feed can render both."""
        task_id = await _create(service, async_connection, task_anchors)

        await service.delete_task(
            user_id=USER_ID, task_id=task_id, transaction=async_connection
        )

        created, deleted = await task_events(async_connection, task_id=task_id)
        assert [created.event_type, deleted.event_type] == [
            "TaskCreated",
            "TaskDeleted",
        ]
        assert created.occurred_at <= deleted.occurred_at
        assert created.event_id != deleted.event_id

    @pytest.mark.asyncio
    async def test_a_refused_delete_writes_no_row(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
    ) -> None:
        """A second delete must not put a second deletion in the record."""
        with pytest.raises(TaskNotFoundError):
            await service.delete_task(
                user_id=USER_ID, task_id=999_999, transaction=async_connection
            )

        assert await task_events(async_connection) == []


@pytest.mark.integration
class TestProvenanceReachesTheRow:
    """Provenance survives the trip through JSON into the column."""

    @pytest.mark.asyncio
    async def test_a_ui_create_is_recorded_as_ui(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        await _create(
            service,
            async_connection,
            task_anchors,
            source=Provenance.UI,
            changed_by="ui",
        )

        (event,) = await task_events(async_connection)
        assert event.payload["source"] == "ui"
        assert event.payload["changed_by"] == "ui"

    @pytest.mark.asyncio
    async def test_an_mcp_delete_is_recorded_as_mcp(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)

        await service.delete_task(
            user_id=USER_ID,
            task_id=task_id,
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        deleted = (await task_events(async_connection))[-1]
        assert deleted.payload["source"] == "mcp"
        assert deleted.payload["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_a_ui_reword_is_recorded_as_ui(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)

        await _update(
            service,
            async_connection,
            task_id,
            text=UPDATED_TEXT,
            source=Provenance.UI,
            changed_by="ui",
        )

        updated = (await task_events(async_connection, task_id=task_id))[-1]
        assert updated.payload["source"] == "ui"
        assert updated.payload["changed_by"] == "ui"

    @pytest.mark.asyncio
    async def test_an_mcp_status_change_is_recorded_as_mcp(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Through ``set_status``, so the delegation is exercised against the row."""
        task_id = await _create(service, async_connection, task_anchors)

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        updated = (await task_events(async_connection, task_id=task_id))[-1]
        assert updated.payload["source"] == "mcp"
        assert updated.payload["changed_by"] == "mcp"


@pytest.mark.integration
class TestTheEventAndTheWriteAreOneUnitOfWork:
    """The acceptance criterion, asserted where transactions are real.

    Each test opens a unit of work of its own and then fails inside it. Because
    ``unit_of_work`` is re-entrant, the service's ``@transactional`` joins that
    one instead of committing, which is exactly what happens when a request
    handler calls two services and the second raises. When the caller's unit
    unwinds, the task row and its event have to go together — an outbox row left
    behind would be an event for a task that never existed, and a missing one
    would be a task with no history.
    """

    @pytest.mark.asyncio
    async def test_a_rolled_back_create_leaves_neither_task_nor_event(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        with pytest.raises(RuntimeError):
            async with unit_of_work(async_connection):
                await _create(service, async_connection, task_anchors)
                raise RuntimeError("the caller failed after the task was written")

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await task_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_a_rolled_back_delete_leaves_both_task_and_no_event(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The mirror: the task comes back, so its deletion must not be recorded."""
        task_id = await _create(service, async_connection, task_anchors)

        with pytest.raises(RuntimeError):
            async with unit_of_work(async_connection):
                await service.delete_task(
                    user_id=USER_ID, task_id=task_id, transaction=async_connection
                )
                raise RuntimeError("the caller failed after the task was deleted")

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 1
        assert [event.event_type for event in await task_events(async_connection)] == [
            "TaskCreated"
        ]

    @pytest.mark.asyncio
    async def test_a_rolled_back_reword_leaves_the_old_text_and_no_event(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The task keeps its old wording, so no reword may be recorded.

        Both halves matter: an event surviving a rolled-back write would tell the
        user their task was reworded to something it does not say.
        """
        task_id = await _create(service, async_connection, task_anchors)

        with pytest.raises(RuntimeError):
            async with unit_of_work(async_connection):
                await _update(service, async_connection, task_id, text=UPDATED_TEXT)
                raise RuntimeError("the caller failed after the task was reworded")

        assert await stored_text(async_connection, task_id) == TASK_TEXT
        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated"]

    @pytest.mark.asyncio
    async def test_a_rolled_back_status_change_leaves_the_old_status_and_no_event(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)

        with pytest.raises(RuntimeError):
            async with unit_of_work(async_connection):
                await service.set_status(
                    user_id=USER_ID,
                    task_id=task_id,
                    status=TaskStatus.DONE,
                    transaction=async_connection,
                )
                raise RuntimeError("the caller failed after the task was completed")

        stored_status = (
            await async_connection.execute(
                text("SELECT status FROM tasks WHERE id = :task_id"),
                {"task_id": task_id},
            )
        ).scalar_one()
        assert stored_status == TaskStatus.NOT_DONE.value
        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated"]

    @pytest.mark.asyncio
    async def test_a_rejected_create_writes_neither(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """Integrity by construction: no event for a change that did not happen.

        Nothing rolls back here — the invariant refuses the create before a row
        is written at all, which is the cheaper half of the same guarantee.
        """
        creating_id, _ = task_anchors
        past_due_id = await create_journal(
            journal_repository, title="Already gone", days_offset=-3
        )

        with pytest.raises(TaskDueJournalNotFutureError):
            await service.create_task(
                user_id=USER_ID,
                creating_journal_id=creating_id,
                due_journal_id=past_due_id,
                text=TASK_TEXT,
                transaction=async_connection,
            )

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await task_events(async_connection) == []


@pytest.mark.integration
class TestNoOtherDomainIsDisturbed:
    """Task events go in the shared outbox without becoming anyone else's problem."""

    @pytest.mark.asyncio
    async def test_the_shared_outbox_gains_only_task_rows(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The create adds its own event and disturbs no other domain's.

        ``outbox_events`` is shared with contacts and journals, so this pins that
        a task write publishes for the task and for nothing else — no cascade
        into the journals it anchors to.

        **Both halves are asserted.** Counting only the foreign rows would leave
        a service that published nothing at all passing, which is the failure
        mode a "nothing else changed" test invites.
        """
        before = (
            await async_connection.execute(
                text(
                    "SELECT COUNT(*) FROM outbox_events WHERE event_type NOT LIKE 'Task%'"
                )
            )
        ).scalar_one()

        await _create(service, async_connection, task_anchors)

        assert len(await task_events(async_connection)) == 1
        after = (
            await async_connection.execute(
                text(
                    "SELECT COUNT(*) FROM outbox_events WHERE event_type NOT LIKE 'Task%'"
                )
            )
        ).scalar_one()
        assert after == before

    @pytest.mark.asyncio
    async def test_an_update_publishes_for_the_task_and_nothing_else(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """A reword must not cascade into the journals the task is anchored to.

        Both halves again: the foreign count is unchanged **and** the task's own
        row appeared, so a service that published nothing cannot pass.
        """
        task_id = await _create(service, async_connection, task_anchors)
        before = (
            await async_connection.execute(
                text(
                    "SELECT COUNT(*) FROM outbox_events WHERE event_type NOT LIKE 'Task%'"
                )
            )
        ).scalar_one()

        await _update(service, async_connection, task_id, text=UPDATED_TEXT)

        assert len(await task_events(async_connection, task_id=task_id)) == 2
        after = (
            await async_connection.execute(
                text(
                    "SELECT COUNT(*) FROM outbox_events WHERE event_type NOT LIKE 'Task%'"
                )
            )
        ).scalar_one()
        assert after == before

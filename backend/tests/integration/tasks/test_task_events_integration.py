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
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskNotFoundError,
    TaskReopenNotAcknowledgedError,
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
    TaskEventRow,
    count,
    create_journal,
    intermediate_journal_ids,
    stored_anchors,
    stored_status,
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


async def _retarget(
    service: TaskService,
    connection: AsyncConnection,
    task_id: int,
    due_journal_id: int,
    *,
    acknowledge_reopen: bool = False,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
) -> None:
    """Move a task onto a new due journal through the service."""
    await service.retarget_due_journal(
        user_id=USER_ID,
        task_id=task_id,
        due_journal_id=due_journal_id,
        transaction=connection,
        acknowledge_reopen=acknowledge_reopen,
        source=source,
        changed_by=changed_by,
    )


def _retarget_events(events: list[TaskEventRow]) -> list[TaskEventRow]:
    """Just the retarget rows, so a trail assertion can name its own subject."""
    return [event for event in events if event.event_type == "TaskDueJournalRetargeted"]


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
class TestARetargetLeavesOneOutboxRow:
    """One retarget, one row — carrying the move, the auto-link and any reopen.

    The unit tests own the payload's shape. What only a database shows is that
    the *decision* reaches ``outbox_events`` as a single row, and what a
    consumer reads back out of the JSON column: pairs arrive as lists, and the
    auto-link's boolean arrives as a boolean rather than as the string
    ``"False"``, which is truthy.
    """

    @pytest.mark.asyncio
    async def test_exactly_one_retarget_row_is_appended(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Not a retarget row *and* a ``TaskUpdated`` for the forced status."""
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )

        await _retarget(service, async_connection, task_id, later_id)

        events = await task_events(async_connection, task_id=task_id)
        assert [event.event_type for event in events] == [
            "TaskCreated",
            "TaskDueJournalRetargeted",
        ]

    @pytest.mark.asyncio
    async def test_the_payload_describes_the_row_that_was_saved(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Compared against the ``tasks`` row and the link table, not the request.

        A whole-payload comparison, as the create's is: the journal the event
        says the task is now due in is read back out of the anchor columns, and
        the journal it says was retained is read back out of
        ``task_intermediate_journals``. A service that published one journal
        while writing another could not pass.
        """
        _, due_id = task_anchors
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )

        await _retarget(service, async_connection, task_id, later_id)

        _, stored_due_id = await stored_anchors(async_connection, task_id)
        (event,) = _retarget_events(
            await task_events(async_connection, task_id=task_id)
        )
        assert event.aggregate_id == task_id
        assert event.payload == {
            "task_id": task_id,
            "user_id": USER_ID,
            "changed_fields": {"due_journal_id": [due_id, stored_due_id]},
            "auto_linked_journal_id": (
                await intermediate_journal_ids(async_connection, task_id)
            )[0],
            "auto_link_created": True,
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    @pytest.mark.asyncio
    async def test_the_due_journal_pair_reads_back_as_an_indexable_two_list(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The form ``_rows_from_changed_fields`` applies its guard to.

        A payload shaped any other way — a dict with ``old``/``new`` keys, a
        bare id — does not raise in that helper. It silently projects **no rows
        at all**, so the retarget would be missing from the user's history with
        nothing anywhere reporting a failure.
        """
        _, due_id = task_anchors
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )

        await _retarget(service, async_connection, task_id, later_id)

        (event,) = _retarget_events(
            await task_events(async_connection, task_id=task_id)
        )
        change = event.payload["changed_fields"]["due_journal_id"]
        assert isinstance(change, list)
        assert len(change) == 2
        assert change[0] == due_id
        assert change[1] == later_id

    @pytest.mark.asyncio
    async def test_the_journal_named_as_auto_linked_really_is_linked(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The event's claim, checked against the link table that backs it."""
        _, due_id = task_anchors
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )

        await _retarget(service, async_connection, task_id, later_id)

        (event,) = _retarget_events(
            await task_events(async_connection, task_id=task_id)
        )
        assert event.payload["auto_linked_journal_id"] == due_id
        assert event.payload["auto_link_created"] is True
        assert await intermediate_journal_ids(async_connection, task_id) == [due_id]

    @pytest.mark.asyncio
    async def test_a_journal_already_in_the_trail_is_recorded_as_not_newly_linked(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A→B→A→C: the second time the task leaves A, A is already attached.

        Reachable precisely because a **retarget** only ever adds an intermediate
        link and never removes one — a due anchor that is also an intermediate
        link is a shape retargeting produces on its own. Other operations do
        remove links (`detach_intermediate_journal`, a merge, a cascading journal
        delete), and none of them runs in this sequence, which is why the
        sequence is performed here rather than mocked: the claim is about what
        three consecutive retargets leave behind, and only a real one can show
        it. Without the flag, Phase 7 would write "linked A" into the user's
        history twice for one link.
        """
        _, journal_a = task_anchors
        task_id = await _create(service, async_connection, task_anchors)
        journal_b = await create_journal(journal_repository, title="B", days_offset=14)
        journal_c = await create_journal(journal_repository, title="C", days_offset=21)

        await _retarget(service, async_connection, task_id, journal_b)
        await _retarget(service, async_connection, task_id, journal_a)
        await _retarget(service, async_connection, task_id, journal_c)

        third = _retarget_events(await task_events(async_connection, task_id=task_id))[
            -1
        ]
        assert third.payload["auto_linked_journal_id"] == journal_a
        assert third.payload["auto_link_created"] is False

    @pytest.mark.asyncio
    async def test_the_row_records_when_the_change_happened(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """``occurred_at`` is the event's clock, which Phase 7 dates rows from.

        Bracketing the call is the assertion, for the reason the create's
        equivalent gives: the column is ``NOT NULL``, so "it is present" would
        also pass for a value a database default supplied.
        """
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )

        before = datetime.now(UTC).replace(tzinfo=None)
        await _retarget(service, async_connection, task_id, later_id)
        after = datetime.now(UTC).replace(tzinfo=None)

        (event,) = _retarget_events(
            await task_events(async_connection, task_id=task_id)
        )
        assert before <= event.occurred_at <= after


@pytest.mark.integration
class TestRetargetsReadAsAnOrderedTrail:
    """The phase's ordering criterion, over the column order a consumer reads.

    ``task_events`` orders by ``(occurred_at, id)`` — the same order the relay
    hands rows to the stream — so a repeatedly-deferred task's events have to
    come back in the order they happened, and each one's "from" has to be the
    previous one's "to". A trail that did not chain would render as a set of
    unrelated moves.
    """

    @pytest.mark.asyncio
    async def test_repeated_deferrals_chain_end_to_end(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        _, journal_a = task_anchors
        task_id = await _create(service, async_connection, task_anchors)
        journal_b = await create_journal(journal_repository, title="B", days_offset=14)
        journal_c = await create_journal(journal_repository, title="C", days_offset=21)

        await _retarget(service, async_connection, task_id, journal_b)
        await _retarget(service, async_connection, task_id, journal_c)

        events = await task_events(async_connection, task_id=task_id)
        assert [event.event_type for event in events] == [
            "TaskCreated",
            "TaskDueJournalRetargeted",
            "TaskDueJournalRetargeted",
        ]
        first, second = (
            event.payload["changed_fields"]["due_journal_id"]
            for event in _retarget_events(events)
        )
        assert first == [journal_a, journal_b]
        assert second == [journal_b, journal_c]

    @pytest.mark.asyncio
    async def test_a_reopen_appends_one_row_rather_than_two(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A completion and a deferral in one write are one announcement.

        The whole trail is asserted rather than the last row, so an
        implementation that published a ``TaskUpdated`` beside the retarget
        fails here instead of passing a test that only checked the retarget was
        present.
        """
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )
        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        await _retarget(
            service, async_connection, task_id, later_id, acknowledge_reopen=True
        )

        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated", "TaskUpdated", "TaskDueJournalRetargeted"]


@pytest.mark.integration
class TestAReopenReachesTheStoredPayload:
    """The phase's third criterion, in the column a consumer reads it from."""

    @pytest.mark.asyncio
    async def test_reopening_a_done_task_stores_the_status_pair(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )
        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        await _retarget(
            service, async_connection, task_id, later_id, acknowledge_reopen=True
        )

        (event,) = _retarget_events(
            await task_events(async_connection, task_id=task_id)
        )
        assert event.payload["changed_fields"]["status"] == ["done", "not_done"]
        assert await stored_status(async_connection, task_id) == "not_done"

    @pytest.mark.asyncio
    async def test_reopening_a_cancelled_task_stores_the_status_pair(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The documented way out of cancelled, and no acknowledgement needed."""
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )
        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.CANCELLED,
            transaction=async_connection,
        )

        await _retarget(service, async_connection, task_id, later_id)

        (event,) = _retarget_events(
            await task_events(async_connection, task_id=task_id)
        )
        assert event.payload["changed_fields"]["status"] == ["cancelled", "not_done"]

    @pytest.mark.asyncio
    async def test_a_deferral_that_changed_no_status_stores_no_status_pair(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The common case: moving a date on an open task changed one thing."""
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )

        await _retarget(service, async_connection, task_id, later_id)

        (event,) = _retarget_events(
            await task_events(async_connection, task_id=task_id)
        )
        assert list(event.payload["changed_fields"]) == ["due_journal_id"]


@pytest.mark.integration
class TestARetargetThatDidNotHappenLeavesNoRow:
    """Each way a retarget can decline, and the silence it has to leave."""

    @pytest.mark.asyncio
    async def test_retargeting_onto_the_current_due_journal_appends_nothing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        _, due_id = task_anchors
        task_id = await _create(service, async_connection, task_anchors)

        await _retarget(service, async_connection, task_id, due_id)

        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated"]

    @pytest.mark.asyncio
    async def test_a_journal_that_is_not_in_the_future_appends_nothing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Refused before anything is written — the cheaper half of the guarantee."""
        task_id = await _create(service, async_connection, task_anchors)
        past_id = await create_journal(
            journal_repository, title="Already gone", days_offset=-3
        )

        with pytest.raises(TaskDueJournalNotFutureError):
            await _retarget(service, async_connection, task_id, past_id)

        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated"]

    @pytest.mark.asyncio
    async def test_an_unacknowledged_reopen_appends_nothing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The 409, and the link it must not leave behind either.

        The acknowledgement is checked **last**, after the journal has been
        resolved and validated, so this refusal gets further through the method
        than any other before deciding to write nothing.
        """
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )
        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        with pytest.raises(TaskReopenNotAcknowledgedError):
            await _retarget(service, async_connection, task_id, later_id)

        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated", "TaskUpdated"]
        assert await intermediate_journal_ids(async_connection, task_id) == []

    @pytest.mark.asyncio
    async def test_a_due_journal_that_is_not_the_users_appends_nothing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Somebody else's journal is not found, and a 404 is not a change.

        The journal is real and future-dated, so the only thing refusing this
        retarget is the owner-scoped read — which is the half a test using a
        merely absent id would not reach.
        """
        task_id = await _create(service, async_connection, task_anchors)
        foreign_id = await create_journal(
            journal_repository,
            title="Theirs, later",
            days_offset=14,
            user_id="other-user-456",
        )

        with pytest.raises(TaskAnchorJournalNotFoundError):
            await _retarget(service, async_connection, task_id, foreign_id)

        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated"]

    @pytest.mark.asyncio
    async def test_another_users_task_appends_nothing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )

        with pytest.raises(TaskNotFoundError):
            await service.retarget_due_journal(
                user_id="somebody-else",
                task_id=task_id,
                due_journal_id=later_id,
                transaction=async_connection,
            )

        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated"]


@pytest.mark.integration
class TestTheRetargetAndItsEventAreOneUnitOfWork:
    """A retarget writes three things; a rollback has to take all three.

    The anchor move, the automatic link and the event go together or not at
    all. This is the one write in the domain where a partial survival has a
    visible shape: an event without its link would tell the user their task
    passed through a journal that has no record of it.
    """

    @pytest.mark.asyncio
    async def test_a_rolled_back_retarget_leaves_the_old_journal_link_and_event_alone(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        _, due_id = task_anchors
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )

        with pytest.raises(RuntimeError):
            async with unit_of_work(async_connection):
                await _retarget(service, async_connection, task_id, later_id)
                raise RuntimeError("the caller failed after the task was retargeted")

        assert (await stored_anchors(async_connection, task_id))[1] == due_id
        assert await intermediate_journal_ids(async_connection, task_id) == []
        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated"]

    @pytest.mark.asyncio
    async def test_a_rolled_back_reopen_leaves_the_task_done_and_unannounced(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The task stays completed, so no reopen may be recorded against it."""
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )
        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        with pytest.raises(RuntimeError):
            async with unit_of_work(async_connection):
                await _retarget(
                    service,
                    async_connection,
                    task_id,
                    later_id,
                    acknowledge_reopen=True,
                )
                raise RuntimeError("the caller failed after the task was reopened")

        assert await stored_status(async_connection, task_id) == "done"
        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskCreated", "TaskUpdated"]


@pytest.mark.integration
class TestProvenanceReachesTheRetargetRow:
    """Who moved the date, as the stored JSON records it."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("source", "changed_by"),
        [(Provenance.UI, "ui"), (Provenance.MCP, "mcp")],
    )
    async def test_the_callers_origin_is_stored(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
        source: Provenance,
        changed_by: str,
    ) -> None:
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )

        await _retarget(
            service,
            async_connection,
            task_id,
            later_id,
            source=source,
            changed_by=changed_by,
        )

        (event,) = _retarget_events(
            await task_events(async_connection, task_id=task_id)
        )
        assert event.payload["source"] == source.value
        assert event.payload["changed_by"] == changed_by


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

    @pytest.mark.asyncio
    async def test_a_retarget_publishes_for_the_task_and_nothing_else(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The write that touches a *journal* link table, and still says nothing
        on the journals' behalf.

        Worth asserting separately from the reword rather than assumed from it:
        this is the only task write that inserts a row naming another domain's
        entity, so it is the one where a cascade would be plausible. Both halves
        again, so a service that published nothing cannot pass.
        """
        task_id = await _create(service, async_connection, task_anchors)
        later_id = await create_journal(
            journal_repository, title="Where it matters now", days_offset=14
        )
        before = (
            await async_connection.execute(
                text(
                    "SELECT COUNT(*) FROM outbox_events WHERE event_type NOT LIKE 'Task%'"
                )
            )
        ).scalar_one()

        await _retarget(service, async_connection, task_id, later_id)

        assert len(await task_events(async_connection, task_id=task_id)) == 2
        after = (
            await async_connection.execute(
                text(
                    "SELECT COUNT(*) FROM outbox_events WHERE event_type NOT LIKE 'Task%'"
                )
            )
        ).scalar_one()
        assert after == before

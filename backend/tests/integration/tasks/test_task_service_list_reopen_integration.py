"""Integration tests for reopening a list task directly, against real PostgreSQL.

The specification makes reopening a list task a plain status change: *"a done
or cancelled list task can be set back to not done, without retargeting."*
Cancelled → done is open too (user decision in the Phase 24 plan review). The
unit tests own the matrix; what only real rows can show is what a reopen does
to the columns the entity never carries:

- ``closed_at`` is cleared, so the task leaves the list's Completed group;
- ``position`` is kept, so the task returns to its own place among the open
  tasks instead of jumping to the bottom;
- the status pair reaches the outbox, so the reopen is in the history;
- a list task due in a journal that has passed reopens *overdue*, never lapsed.

Ownership and the archived-list guard are re-proved for the newly opened path,
since both are decided before the transition and a reopen must not slip past
either.
"""

import pytest
from core_shared.models.tasks import (
    TaskListArchivedError,
    TaskNotFoundError,
    TaskStatus,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from tests.integration.tasks.task_seeding import (
    ARCHIVED_AT,
    OTHER_USER_ID,
    USER_ID,
    backdate_closed_at,
    backdate_updated_at,
    create_journal,
    create_list_task,
    seed_task_list,
    stored_closed_at,
    stored_positions,
    stored_status,
    stored_updated_at,
    task_events,
)


async def _list_id(conn: AsyncConnection, *, user_id: str = USER_ID) -> int:
    task_list = await seed_task_list(conn, user_id=user_id)
    assert task_list.id is not None
    return task_list.id


@pytest.mark.integration
class TestReopeningAListTask:
    """Done or cancelled → not done, with no retarget."""

    @pytest.mark.parametrize("closed", [TaskStatus.CANCELLED, TaskStatus.DONE])
    async def test_the_reopen_is_committed_and_closed_at_cleared(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        closed: TaskStatus,
    ) -> None:
        """Read back from the row, not from the returned task."""
        task_id = await create_list_task(
            async_connection,
            task_list_id=await _list_id(async_connection),
            position=3,
            status=closed,
        )
        await backdate_closed_at(async_connection, task_id)

        updated = await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.NOT_DONE,
            transaction=async_connection,
        )

        assert updated.status == TaskStatus.NOT_DONE
        assert await stored_status(async_connection, task_id) == "not_done"
        assert await stored_closed_at(async_connection, task_id) is None
        assert await stored_positions(async_connection, [task_id]) == [3]

    async def test_it_returns_to_its_own_place_among_the_open_tasks(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
    ) -> None:
        """Between the two open tasks it sat between, not at the bottom."""
        list_id = await _list_id(async_connection)
        first = await create_list_task(
            async_connection, task_list_id=list_id, position=0
        )
        reopened = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=1,
            status=TaskStatus.CANCELLED,
        )
        last = await create_list_task(
            async_connection, task_list_id=list_id, position=2
        )

        await service.set_status(
            user_id=USER_ID,
            task_id=reopened,
            status=TaskStatus.NOT_DONE,
            transaction=async_connection,
        )

        open_tasks = await task_repository.find_open_tasks_on_list(list_id, USER_ID)
        assert [task.id for task in open_tasks] == [first, reopened, last]

    async def test_the_status_pair_reaches_the_outbox(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        """One task-updated event carrying cancelled → not done."""
        task_id = await create_list_task(
            async_connection,
            task_list_id=await _list_id(async_connection),
            status=TaskStatus.CANCELLED,
        )

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.NOT_DONE,
            transaction=async_connection,
        )

        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {"status": ["cancelled", "not_done"]}

    async def test_a_task_due_in_a_passed_journal_reopens_overdue_not_lapsed(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A list task never lapses, so the reopen needs no future journal."""
        past_id = await create_journal(journal_repository, days_offset=-3)
        task_id = await create_list_task(
            async_connection,
            task_list_id=await _list_id(async_connection),
            due_journal_id=past_id,
            status=TaskStatus.CANCELLED,
        )

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.NOT_DONE,
            transaction=async_connection,
        )

        model = await read_service.read_model(USER_ID, task_id)
        assert model.task.due_journal_id == past_id
        assert model.lapsed is False
        assert model.overdue is True


@pytest.mark.integration
class TestCancelledToDoneOnAList:
    """Open on a list (user decision): the task stays closed, now as done."""

    async def test_is_committed_and_stays_closed(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        """Still closed — ``closed_at`` is set, re-stamped as a fresh close.

        So the task stays in the list's Completed group, now as done.
        """
        task_id = await create_list_task(
            async_connection,
            task_list_id=await _list_id(async_connection),
            status=TaskStatus.CANCELLED,
        )

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        assert await stored_status(async_connection, task_id) == "done"
        assert await stored_closed_at(async_connection, task_id) is not None


@pytest.mark.integration
class TestTheGuardsStillComeFirst:
    """Ownership and the archived list are decided before the transition."""

    async def test_another_users_list_task_is_not_found_and_not_changed(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        """Indistinguishable from a missing task, and their row is untouched."""
        task_id = await create_list_task(
            async_connection,
            task_list_id=await _list_id(async_connection, user_id=OTHER_USER_ID),
            status=TaskStatus.CANCELLED,
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskNotFoundError):
            await service.set_status(
                user_id=USER_ID,
                task_id=task_id,
                status=TaskStatus.NOT_DONE,
                transaction=async_connection,
            )

        assert await stored_status(async_connection, task_id) == "cancelled"

    async def test_a_task_on_an_archived_list_is_still_read_only(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        """The archived refusal wins; the row and its timestamp are untouched."""
        task_list = await seed_task_list(async_connection, archived_at=ARCHIVED_AT)
        assert task_list.id is not None
        task_id = await create_list_task(
            async_connection, task_list_id=task_list.id, status=TaskStatus.CANCELLED
        )
        backdated = await backdate_updated_at(async_connection, task_id)

        with pytest.raises(TaskListArchivedError):
            await service.set_status(
                user_id=USER_ID,
                task_id=task_id,
                status=TaskStatus.NOT_DONE,
                transaction=async_connection,
            )

        assert await stored_status(async_connection, task_id) == "cancelled"
        assert await stored_updated_at(async_connection, task_id) == backdated
        assert await task_events(async_connection, task_id=task_id) == []

"""Integration tests: moving a task onto or between lists, against real PostgreSQL.

The specification's *Moving tasks*: "A list task can be moved to another list;
it joins the bottom" and "A journal-only task can be added to a list. It keeps
its journals and … no longer lapses." The unit tests pin the lock order and the
refusal order against mocks; these prove what the database is left holding:

- the task lands one past the list's highest position, closed tasks included;
- a journal-only task due in a **past** journal reads as lapsed before the move
  and as overdue — not lapsed — after it, with its journals, status, flag, icon
  and contacts kept;
- one outbox event per move, and none for a same-list no-op or a refusal;
- another user's list or task is never written;
- the locks do what the order promises, over two real connections: an archive
  and a move onto the same list wait for each other, two moves onto one list
  take consecutive positions, a move and a status edit of one task queue, and
  a move and a reorder of its list meet on the task row without deadlocking.
"""

import datetime
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    TaskListArchivedError,
    TaskListChangedConcurrentlyError,
    TaskListNotFoundError,
    TaskNotFoundError,
    TaskStatus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.services.task_list_service import TaskListService
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.concurrency_helpers import overlap
from tests.integration.tasks.task_seeding import (
    ARCHIVED_AT,
    OTHER_USER_ID,
    USER_ID,
    create_contact,
    create_journal,
    create_list_task,
    create_task,
    link_contact,
    linked_contact_ids,
    mark_task,
    seed_task_list,
    service_on,
    stored_anchors,
    stored_marks,
    stored_membership,
    stored_status,
    task_events,
)
from tests.task_event_inventory import task_event_types

pytestmark = pytest.mark.integration


async def _list_id(conn: AsyncConnection, name: str, **kwargs: Any) -> int:
    task_list = await seed_task_list(conn, name, **kwargs)
    assert task_list.id is not None
    return task_list.id


async def _move(
    service: TaskService,
    conn: AsyncConnection,
    task_id: int,
    task_list_id: int,
    *,
    user_id: str = USER_ID,
) -> None:
    await service.move_to_list(
        user_id=user_id,
        task_id=task_id,
        task_list_id=task_list_id,
        transaction=conn,
        source=Provenance.UI,
        changed_by="ui",
    )


class TestAJournalOnlyTaskJoiningAList:
    @pytest.mark.asyncio
    async def test_it_stops_lapsing_and_keeps_everything_it_had(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A past due journal lapses it; on a list the same date is overdue."""
        creating_id = await create_journal(
            journal_repository, title="Planning", days_offset=-5
        )
        due_id = await create_journal(journal_repository, title="Due", days_offset=-3)
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await mark_task(async_connection, task_id, flagged=True, icon="tent")
        contact_id = await create_contact(async_connection)
        await link_contact(async_connection, task_id=task_id, contact_id=contact_id)
        list_id = await _list_id(async_connection, "Packing")
        await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=4,
            status=TaskStatus.DONE,
        )
        assert (await read_service.read_model(USER_ID, task_id)).lapsed is True

        await _move(service, async_connection, task_id, list_id)

        model = await read_service.read_model(USER_ID, task_id)
        assert model.lapsed is False
        assert model.overdue is True
        # One past the closed task's position: closed tasks count.
        assert await stored_membership(async_connection, task_id) == (list_id, 5)
        assert await stored_anchors(async_connection, task_id) == (
            creating_id,
            due_id,
        )
        assert await stored_status(async_connection, task_id) == "not_done"
        assert await stored_marks(async_connection, task_id) == (True, "tent")
        assert await linked_contact_ids(async_connection, task_id) == [contact_id]

    @pytest.mark.asyncio
    async def test_one_membership_event_is_published_from_none(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        list_id = await _list_id(async_connection, "Packing")

        await _move(service, async_connection, task_id, list_id)

        [event] = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskListMembershipChanged"
        assert event.payload == {
            "task_id": task_id,
            "user_id": USER_ID,
            "changed_fields": {"task_list_id": [None, list_id]},
            "source": "ui",
            "changed_by": "ui",
        }


class TestAMoveBetweenLists:
    @pytest.mark.asyncio
    async def test_it_joins_the_bottom_of_the_target_and_keeps_its_date(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
    ) -> None:
        source_id = await _list_id(async_connection, "Groceries")
        target_id = await _list_id(async_connection, "Hardware")
        due = datetime.date.today() + datetime.timedelta(days=10)
        task_id = await create_list_task(
            async_connection, task_list_id=source_id, due_date=due
        )
        await create_list_task(async_connection, task_list_id=target_id, position=2)

        await _move(service, async_connection, task_id, target_id)

        assert await stored_membership(async_connection, task_id) == (target_id, 3)
        moved = await read_service.read_model(USER_ID, task_id)
        assert moved.task.due_date == due
        on_source = await read_service.read_models_on_list(USER_ID, source_id)
        assert task_id not in [model.task.id for model in on_source.models]

    @pytest.mark.asyncio
    async def test_one_event_names_both_lists(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        source_id = await _list_id(async_connection, "Groceries")
        target_id = await _list_id(async_connection, "Hardware")
        task_id = await create_list_task(async_connection, task_list_id=source_id)

        await _move(service, async_connection, task_id, target_id)

        [event] = await task_events(async_connection, task_id=task_id)
        assert event.payload["changed_fields"] == {
            "task_list_id": [source_id, target_id]
        }


class TestNothingIsWritten:
    @pytest.mark.asyncio
    async def test_moving_to_its_own_list_keeps_its_position(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        """``add_to_list`` would send it to the bottom; the no-op must not."""
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(async_connection, task_list_id=list_id)
        await create_list_task(async_connection, task_list_id=list_id, position=1)

        await _move(service, async_connection, task_id, list_id)

        assert await stored_membership(async_connection, task_id) == (list_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []

    @pytest.mark.asyncio
    async def test_an_archived_target_is_refused(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        source_id = await _list_id(async_connection, "Groceries")
        target_id = await _list_id(async_connection, "Old", archived_at=ARCHIVED_AT)
        task_id = await create_list_task(async_connection, task_list_id=source_id)
        before = await stored_membership(async_connection, task_id)

        with pytest.raises(TaskListArchivedError):
            await _move(service, async_connection, task_id, target_id)

        assert await stored_membership(async_connection, task_id) == before
        assert await task_events(async_connection, task_id=task_id) == []

    @pytest.mark.asyncio
    async def test_another_users_list_reads_as_absent(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        source_id = await _list_id(async_connection, "Groceries")
        foreign_id = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        task_id = await create_list_task(async_connection, task_list_id=source_id)
        before = await stored_membership(async_connection, task_id)

        with pytest.raises(TaskListNotFoundError):
            await _move(service, async_connection, task_id, foreign_id)

        assert await stored_membership(async_connection, task_id) == before
        assert await task_events(async_connection, task_id=task_id) == []

    @pytest.mark.asyncio
    async def test_another_users_task_reads_as_absent(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        theirs_id = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        mine_id = await _list_id(async_connection, "Mine")
        task_id = await create_list_task(
            async_connection, task_list_id=theirs_id, user_id=OTHER_USER_ID
        )

        with pytest.raises(TaskNotFoundError):
            await _move(service, async_connection, task_id, mine_id)

        assert await stored_membership(async_connection, task_id) == (theirs_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []


# ---------------------------------------------------------------------------
# Concurrency: two real connections, committed rows.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Committed:
    owner: str
    source_id: int
    target_id: int
    task_id: int
    other_task_id: int


@asynccontextmanager
async def committed_lists(async_engine: AsyncEngine) -> AsyncIterator[Committed]:
    """Two lists and two tasks on the first, committed under a one-off owner.

    Two transactions only overlap on rows both can see, which the savepoint
    fixture's are not. Everything is deleted again afterwards, the task events
    included — they are committed too.
    """
    owner = f"move-race-{uuid.uuid4()}"
    async with async_engine.begin() as setup:
        source_id = await _list_id(setup, "Groceries", user_id=owner)
        target_id = await _list_id(setup, "Hardware", user_id=owner)
        task_id = await create_list_task(setup, task_list_id=source_id, user_id=owner)
        other_task_id = await create_list_task(
            setup, task_list_id=source_id, position=1, user_id=owner
        )
    try:
        yield Committed(owner, source_id, target_id, task_id, other_task_id)
    finally:
        async with async_engine.begin() as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM outbox_events WHERE event_data::jsonb ->> 'user_id'"
                    " = :owner AND event_type = ANY(:types)"
                ),
                {
                    "owner": owner,
                    "types": sorted(
                        task_event_types() | {"TaskListCreated", "TaskListUpdated"}
                    ),
                },
            )
            await cleanup.execute(
                text("DELETE FROM tasks WHERE user_id = :owner"), {"owner": owner}
            )
            await cleanup.execute(
                text("DELETE FROM task_lists WHERE user_id = :owner"), {"owner": owner}
            )


Step = Callable[[AsyncConnection], Any]


def _moving(
    owner: str, task_id: int, task_list_id: int, refused: list[BaseException]
) -> Step:
    async def run(connection: AsyncConnection) -> None:
        service = service_on(connection, SqlUserSettingsRepository(connection))
        try:
            await service.move_to_list(
                user_id=owner,
                task_id=task_id,
                task_list_id=task_list_id,
                transaction=connection,
            )
        except TaskListArchivedError as error:
            refused.append(error)

    return run


def _archiving(owner: str, task_list_id: int) -> Step:
    async def run(connection: AsyncConnection) -> None:
        await TaskListService(
            task_list_repo=SqlTaskListRepository(connection),
            event_publisher=OutboxEventPublisher(connection),
        ).archive_task_list(
            user_id=owner, task_list_id=task_list_id, transaction=connection
        )

    return run


def _moving_then_archiving(owner: str, task_id: int, task_list_id: int) -> Step:
    """One unit of work: the task moves onto a list, and that list is archived."""

    async def run(connection: AsyncConnection) -> None:
        await _moving(owner, task_id, task_list_id, [])(connection)
        await _archiving(owner, task_list_id)(connection)

    return run


def _linking(
    owner: str, task_id: int, contact_id: int, refused: list[BaseException]
) -> Step:
    async def run(connection: AsyncConnection) -> None:
        service = service_on(connection, SqlUserSettingsRepository(connection))
        try:
            await service.link_contact(
                user_id=owner,
                task_id=task_id,
                contact_id=contact_id,
                transaction=connection,
            )
        except TaskListArchivedError as error:
            refused.append(error)

    return run


def _completing(owner: str, task_id: int) -> Step:
    async def run(connection: AsyncConnection) -> None:
        await service_on(connection, SqlUserSettingsRepository(connection)).set_status(
            user_id=owner,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=connection,
        )

    return run


def _reordering(
    owner: str, task_id: int, refused: list[BaseException] | None = None
) -> Step:
    """Move ``task_id`` to the top of its list — the list page's reorder."""

    async def run(connection: AsyncConnection) -> None:
        service = service_on(connection, SqlUserSettingsRepository(connection))
        try:
            await service.reorder_task(
                user_id=owner,
                task_id=task_id,
                after_task_id=None,
                transaction=connection,
            )
        except TaskListChangedConcurrentlyError as error:
            if refused is None:
                raise
            refused.append(error)

    return run


async def _committed_membership(
    async_engine: AsyncEngine, task_id: int
) -> tuple[int | None, int | None]:
    async with async_engine.connect() as check:
        return await stored_membership(check, task_id)


class TestTheLocksHold:
    @pytest.mark.asyncio
    async def test_a_move_during_an_archive_of_the_target_waits_and_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_lists(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _archiving(c.owner, c.target_id),
                _moving(c.owner, c.task_id, c.target_id, refused),
            )

            assert len(refused) == 1
            assert await _committed_membership(async_engine, c.task_id) == (
                c.source_id,
                0,
            )

    @pytest.mark.asyncio
    async def test_an_archive_during_a_move_waits_for_the_move(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_lists(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _moving(c.owner, c.task_id, c.target_id, refused),
                _archiving(c.owner, c.target_id),
            )

            assert refused == []
            assert await _committed_membership(async_engine, c.task_id) == (
                c.target_id,
                0,
            )

    @pytest.mark.asyncio
    async def test_two_moves_onto_one_list_take_consecutive_positions(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_lists(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _moving(c.owner, c.task_id, c.target_id, refused),
                _moving(c.owner, c.other_task_id, c.target_id, refused),
            )

            assert refused == []
            assert await _committed_membership(async_engine, c.task_id) == (
                c.target_id,
                0,
            )
            assert await _committed_membership(async_engine, c.other_task_id) == (
                c.target_id,
                1,
            )

    @pytest.mark.asyncio
    async def test_a_status_edit_during_a_move_waits_and_both_land(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_lists(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _moving(c.owner, c.task_id, c.target_id, refused),
                _completing(c.owner, c.task_id),
            )

            async with async_engine.connect() as check:
                assert await stored_status(check, c.task_id) == "done"
                assert await stored_membership(check, c.task_id) == (c.target_id, 0)

    @pytest.mark.asyncio
    async def test_a_reorder_of_the_source_during_a_move_waits_and_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        """The reorder shares the source list with the move, then waits on the task.

        The move takes the source only ``FOR SHARE``, which the reorder's own
        share lock never waits on, so the two meet on the task row and no cycle
        forms. Once the move commits, the task the reorder named has left the
        list, and the reorder refuses rather than writing it back.
        """
        async with committed_lists(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _moving(c.owner, c.task_id, c.target_id, []),
                _reordering(c.owner, c.task_id, refused),
            )

            assert len(refused) == 1
            assert await _committed_membership(async_engine, c.task_id) == (
                c.target_id,
                0,
            )
            assert await _committed_membership(async_engine, c.other_task_id) == (
                c.source_id,
                1,
            )

    @pytest.mark.asyncio
    async def test_a_move_during_a_reorder_of_the_source_waits_and_lands(
        self, async_engine: AsyncEngine
    ) -> None:
        """The reorder holds every open task on the source; the move queues on one."""
        async with committed_lists(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _reordering(c.owner, c.other_task_id),
                _moving(c.owner, c.task_id, c.target_id, refused),
            )

            assert refused == []
            assert await _committed_membership(async_engine, c.task_id) == (
                c.target_id,
                0,
            )
            (other_list, _) = await _committed_membership(async_engine, c.other_task_id)
            assert other_list == c.source_id

    @pytest.mark.asyncio
    async def test_a_link_racing_a_move_onto_a_list_then_archived_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        """The link waits on the task, then reads the list it is on *now*.

        Without the share lock on the task the link reads it on its old list,
        holds that list, and is written to a task on an archived list.
        """
        async with committed_lists(async_engine) as c:
            async with async_engine.begin() as setup:
                contact_id = await create_contact(setup, user_id=c.owner)
            refused: list[BaseException] = []
            try:
                await overlap(
                    async_engine,
                    _moving_then_archiving(c.owner, c.task_id, c.target_id),
                    _linking(c.owner, c.task_id, contact_id, refused),
                )

                assert len(refused) == 1
                async with async_engine.connect() as check:
                    assert await linked_contact_ids(check, c.task_id) == []
            finally:
                async with async_engine.begin() as cleanup:
                    await cleanup.execute(
                        text("DELETE FROM task_contacts WHERE contact_id = :id"),
                        {"id": contact_id},
                    )
                    await cleanup.execute(
                        text("DELETE FROM contacts WHERE id = :id"), {"id": contact_id}
                    )

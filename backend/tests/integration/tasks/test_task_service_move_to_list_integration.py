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
  a move and a reorder of its list meet on the task row without deadlocking,
  two crossing moves with a reorder of one list between them do not
  deadlock either, and nor does a move whose read went stale before it locked
  the list the task had meanwhile reached, against an edit of that task.
"""

import asyncio
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
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_list_service import TaskListService
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import (
    backend_pid,
    bounded,
    overlap,
    settle,
    wait_until_blocked_on_a_lock,
)
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
    async def test_a_second_move_of_the_same_task_is_refused_once_it_has_moved(
        self, async_engine: AsyncEngine
    ) -> None:
        """The second chose its lists from where the task was; it now is not.

        It holds those lists and may not lock another out of order, so it
        refuses (409, read again and retry) instead of moving the task on.
        """
        async with committed_lists(async_engine) as c:
            async with async_engine.begin() as setup:
                elsewhere_id = await _list_id(setup, "Garden", user_id=c.owner)
            changed: list[BaseException] = []

            async def moving_elsewhere(connection: AsyncConnection) -> None:
                service = service_on(connection, SqlUserSettingsRepository(connection))
                try:
                    await service.move_to_list(
                        user_id=c.owner,
                        task_id=c.task_id,
                        task_list_id=elsewhere_id,
                        transaction=connection,
                    )
                except TaskListChangedConcurrentlyError as error:
                    changed.append(error)

            await overlap(
                async_engine,
                _moving(c.owner, c.task_id, c.target_id, []),
                moving_elsewhere,
            )

            assert len(changed) == 1
            assert await _committed_membership(async_engine, c.task_id) == (
                c.target_id,
                0,
            )

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


class _GatedLists(SqlTaskListRepository):
    """A list repository that pauses at the first list lock until let go.

    The pause is where a move has chosen its lists and is about to lock them:
    under a task-first order it already holds its task there, which is the
    state the crossing-moves cycle needs.
    """

    reached: asyncio.Event
    release: asyncio.Event

    async def _pause(self) -> None:
        if not self.reached.is_set():
            self.reached.set()
            await self.release.wait()

    async def find_by_id_for_share(self, task_list_id: int, user_id: str) -> Any:
        await self._pause()
        return await super().find_by_id_for_share(task_list_id, user_id)

    async def find_by_id_for_update(self, task_list_id: int, user_id: str) -> Any:
        await self._pause()
        return await super().find_by_id_for_update(task_list_id, user_id)


async def _waiting_or_done(
    async_engine: AsyncEngine, pid: int, running: asyncio.Task[None]
) -> None:
    """Return once ``running`` has finished or its backend waits on a lock."""
    waiting = asyncio.ensure_future(wait_until_blocked_on_a_lock(async_engine, pid))
    try:
        await bounded(
            asyncio.wait({waiting, running}, return_when=asyncio.FIRST_COMPLETED)
        )
    finally:
        await settle(waiting)


class TestCrossingMovesAndAReorder:
    @pytest.mark.asyncio
    async def test_they_queue_rather_than_deadlock(
        self, async_engine: AsyncEngine
    ) -> None:
        """Lists A < B; one move A → B, one B → A, and a reorder of B.

        Under a task-first order: the B → A move holds its task; the reorder
        holds B ``FOR SHARE`` and waits for that task; the A → B move holds its
        task and A ``FOR SHARE`` and waits for B; then the B → A move asks for
        A and the cycle closes — PostgreSQL aborts one. Lists first, no move
        holds a task while it waits for a list, so all three land.
        """
        async with committed_lists(async_engine) as c:
            async with async_engine.begin() as setup:
                crossing_id = await create_list_task(
                    setup, task_list_id=c.target_id, user_id=c.owner
                )
                await create_list_task(
                    setup, task_list_id=c.target_id, position=1, user_id=c.owner
                )

            class Gated(_GatedLists):
                reached = asyncio.Event()
                release = asyncio.Event()

            async def crossing(connection: AsyncConnection) -> None:
                async with unit_of_work(connection):
                    await service_on(
                        connection,
                        SqlUserSettingsRepository(connection),
                        task_list_repo=Gated,
                    ).move_to_list(
                        user_id=c.owner,
                        task_id=crossing_id,
                        task_list_id=c.source_id,
                        transaction=connection,
                    )

            async def reordering(connection: AsyncConnection) -> None:
                async with unit_of_work(connection):
                    await _reordering(c.owner, crossing_id)(connection)

            async def moving(connection: AsyncConnection) -> None:
                async with unit_of_work(connection):
                    await _moving(c.owner, c.task_id, c.target_id, [])(connection)

            async with (
                async_engine.connect() as one,
                async_engine.connect() as two,
                async_engine.connect() as three,
            ):
                pids = [await backend_pid(each) for each in (one, two, three)]
                started: list[asyncio.Task[None]] = []
                try:
                    started.append(asyncio.create_task(crossing(one)))
                    await bounded(Gated.reached.wait())
                    started.append(asyncio.create_task(reordering(two)))
                    await _waiting_or_done(async_engine, pids[1], started[1])
                    started.append(asyncio.create_task(moving(three)))
                    await _waiting_or_done(async_engine, pids[2], started[2])
                    Gated.release.set()

                    outcomes = await bounded(
                        asyncio.gather(*started, return_exceptions=True)
                    )
                finally:
                    Gated.release.set()
                    await settle(*started)

            assert outcomes == [None, None, None]
            assert await _committed_membership(async_engine, crossing_id) == (
                c.source_id,
                2,
            )
            assert await _committed_membership(async_engine, c.task_id) == (
                c.target_id,
                2,
            )


class _PausedAfterReading(SqlTaskRepository):
    """A task repository that pauses after its first plain read until let go.

    That read is where a move chooses its lists; pausing there lets another
    move commit first, so the lists it then locks are chosen from a stale read.
    """

    reached: asyncio.Event
    release: asyncio.Event

    async def find_by_id(self, task_id: int, user_id: str) -> Any:
        found = await super().find_by_id(task_id, user_id)
        if not self.reached.is_set():
            self.reached.set()
            await self.release.wait()
        return found


class TestAStaleMoveAndAnEdit:
    @pytest.mark.asyncio
    async def test_the_stale_move_is_refused_and_the_edit_lands(
        self, async_engine: AsyncEngine
    ) -> None:
        """The task reached the stale move's target before it locked it.

        1. The stale move reads the task on the source, and pauses.
        2. Another move takes the task to the target and commits.
        3. An edit locks the task, and pauses before holding its list.
        4. The stale move locks source and target; the task is on the target.
        5. The edit asks for the target ``FOR SHARE``.

        Waiting for the task at 4 would close a cycle with 5. The re-read under
        the list locks sees the task has moved, and refuses without waiting.
        """
        async with committed_lists(async_engine) as c:

            class Stale(_PausedAfterReading):
                reached = asyncio.Event()
                release = asyncio.Event()

            class EditPaused(_GatedLists):
                reached = asyncio.Event()
                release = asyncio.Event()

            async def stale_move(connection: AsyncConnection) -> None:
                async with unit_of_work(connection):
                    await service_on(
                        connection, SqlUserSettingsRepository(connection), repo=Stale
                    ).move_to_list(
                        user_id=c.owner,
                        task_id=c.task_id,
                        task_list_id=c.target_id,
                        transaction=connection,
                    )

            async def editing(connection: AsyncConnection) -> None:
                async with unit_of_work(connection):
                    await service_on(
                        connection,
                        SqlUserSettingsRepository(connection),
                        task_list_repo=EditPaused,
                    ).set_status(
                        user_id=c.owner,
                        task_id=c.task_id,
                        status=TaskStatus.DONE,
                        transaction=connection,
                    )

            async with async_engine.connect() as one, async_engine.connect() as two:
                stale_pid = await backend_pid(one)
                await backend_pid(two)
                started: list[asyncio.Task[None]] = []
                try:
                    started.append(asyncio.create_task(stale_move(one)))
                    await bounded(Stale.reached.wait())
                    async with async_engine.begin() as other:
                        await _moving(c.owner, c.task_id, c.target_id, [])(other)
                    started.append(asyncio.create_task(editing(two)))
                    await bounded(EditPaused.reached.wait())
                    Stale.release.set()
                    await _waiting_or_done(async_engine, stale_pid, started[0])
                    EditPaused.release.set()

                    outcomes = await bounded(
                        asyncio.gather(*started, return_exceptions=True)
                    )
                finally:
                    Stale.release.set()
                    EditPaused.release.set()
                    await settle(*started)

            assert isinstance(outcomes[0], TaskListChangedConcurrentlyError)
            assert outcomes[1] is None
            async with async_engine.connect() as check:
                assert await stored_status(check, c.task_id) == "done"
                assert await stored_membership(check, c.task_id) == (c.target_id, 0)

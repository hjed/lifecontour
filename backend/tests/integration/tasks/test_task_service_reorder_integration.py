"""Integration tests for reordering a list's open tasks against real PostgreSQL.

``TaskService.reorder_task`` (the list page's single move) and
``TaskService.reorder_list_tasks`` (an agent's block arrangement). The unit
tests own the refusals and their order; what only a real database shows:

- the new order is stored, closed tasks keep their slots, nothing reaches the
  outbox and no task's ``updated_at`` moves — reordering is not an edit;
- a refusal — another user's ids, an archived list — moves nothing;
- **the lock order holds against every task write.** A task write locks its
  task and then takes its list ``FOR SHARE``; a reorder takes the list
  ``FOR SHARE`` and then the open tasks. Were the reorder's list lock
  exclusive, the two would deadlock — the interleaving tests below reproduce
  exactly that and fail against it;
- a task created on the list while a reorder runs still lands at the bottom,
  and a task reopened while one runs keeps its own place.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

import pytest
from core_shared.models.tasks import (
    TaskListArchivedError,
    TaskListNotFoundError,
    TaskNotFoundError,
    TaskStatus,
    TaskValidationError,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import (
    backend_pid,
    bounded,
    overlap,
    settle,
    wait_until_blocked_on_a_lock,
)
from tests.integration.tasks.task_seeding import (
    FIXED_PAST_INSTANT,
    OTHER_USER_ID,
    USER_ID,
    backdate_updated_at,
    committed_task_list,
    count,
    create_list_task,
    seed_task_list_id,
    service_on,
    stored_positions,
    stored_updated_at,
)

pytestmark = pytest.mark.integration

_COUNT_OUTBOX = "SELECT COUNT(*) FROM outbox_events"


async def _open_order(conn: AsyncConnection, list_id: int, owner: str) -> list[int]:
    tasks = await SqlTaskRepository(conn).find_open_tasks_on_list(list_id, owner)
    return [task.id for task in tasks if task.id is not None]


async def _seed(
    conn: AsyncConnection, *, archived: bool = False
) -> tuple[int, list[int]]:
    """A list with open tasks at 1, 3, 5 and a done one at 2; ``(list, open)``."""
    list_id = await seed_task_list_id(conn, archived=archived)
    ids = [
        await create_list_task(conn, task_list_id=list_id, position=position)
        for position in (1, 3, 5)
    ]
    await create_list_task(
        conn, task_list_id=list_id, position=2, status=TaskStatus.DONE
    )
    return list_id, ids


class TestReorderTask:
    async def test_the_new_order_is_stored_and_answered(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id, (first, second, third) = await _seed(async_connection)

        answer = await service.reorder_task(
            user_id=USER_ID,
            task_id=third,
            after_task_id=first,
            transaction=async_connection,
        )

        assert [task.id for task, _ in answer] == [first, third, second]
        assert await _open_order(async_connection, list_id, USER_ID) == [
            first,
            third,
            second,
        ]

    async def test_reordering_is_not_an_edit(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        _, ids = await _seed(async_connection)
        for task_id in ids:
            await backdate_updated_at(async_connection, task_id)
        outbox_before = await count(async_connection, _COUNT_OUTBOX, {})

        await service.reorder_task(
            user_id=USER_ID,
            task_id=ids[2],
            after_task_id=None,
            transaction=async_connection,
        )

        for task_id in ids:
            assert await stored_updated_at(async_connection, task_id) == (
                FIXED_PAST_INSTANT
            )
        assert await count(async_connection, _COUNT_OUTBOX, {}) == outbox_before

    async def test_a_move_to_its_own_place_writes_nothing(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        _, ids = await _seed(async_connection)

        await service.reorder_task(
            user_id=USER_ID,
            task_id=ids[1],
            after_task_id=ids[0],
            transaction=async_connection,
        )

        assert await stored_positions(async_connection, ids) == [1, 3, 5]

    async def test_another_users_task_and_anchor_are_not_found(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        _, ids = await _seed(async_connection)
        their_list = await seed_task_list_id(async_connection, user_id=OTHER_USER_ID)
        theirs = await create_list_task(
            async_connection, task_list_id=their_list, user_id=OTHER_USER_ID
        )

        with pytest.raises(TaskNotFoundError):
            await service.reorder_task(
                user_id=USER_ID,
                task_id=theirs,
                after_task_id=None,
                transaction=async_connection,
            )
        with pytest.raises(TaskNotFoundError):
            await service.reorder_task(
                user_id=USER_ID,
                task_id=ids[2],
                after_task_id=theirs,
                transaction=async_connection,
            )

        assert await stored_positions(async_connection, [*ids, theirs]) == [1, 3, 5, 0]

    async def test_an_archived_list_is_refused_and_nothing_moves(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        _, ids = await _seed(async_connection, archived=True)

        with pytest.raises(TaskListArchivedError):
            await service.reorder_task(
                user_id=USER_ID,
                task_id=ids[2],
                after_task_id=None,
                transaction=async_connection,
            )

        assert await stored_positions(async_connection, ids) == [1, 3, 5]


class TestReorderListTasks:
    async def test_a_block_after_an_anchor_is_stored_and_answered(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id, (first, second, third) = await _seed(async_connection)

        answer = await service.reorder_list_tasks(
            user_id=USER_ID,
            task_list_id=list_id,
            task_ids=[third, first],
            after_task_id=second,
            transaction=async_connection,
        )

        assert [task.id for task, _ in answer] == [second, third, first]
        assert await _open_order(async_connection, list_id, USER_ID) == [
            second,
            third,
            first,
        ]

    async def test_arranging_is_not_an_edit(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id, ids = await _seed(async_connection)
        for task_id in ids:
            await backdate_updated_at(async_connection, task_id)
        outbox_before = await count(async_connection, _COUNT_OUTBOX, {})

        await service.reorder_list_tasks(
            user_id=USER_ID,
            task_list_id=list_id,
            task_ids=list(reversed(ids)),
            transaction=async_connection,
        )

        for task_id in ids:
            assert await stored_updated_at(async_connection, task_id) == (
                FIXED_PAST_INSTANT
            )
        assert await count(async_connection, _COUNT_OUTBOX, {}) == outbox_before

    async def test_another_users_list_is_not_found_and_their_task_refused(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id, ids = await _seed(async_connection)
        their_list = await seed_task_list_id(async_connection, user_id=OTHER_USER_ID)
        theirs = await create_list_task(
            async_connection, task_list_id=their_list, user_id=OTHER_USER_ID
        )

        with pytest.raises(TaskListNotFoundError):
            await service.reorder_list_tasks(
                user_id=USER_ID,
                task_list_id=their_list,
                task_ids=[theirs],
                transaction=async_connection,
            )
        with pytest.raises(TaskValidationError, match=str(theirs)):
            await service.reorder_list_tasks(
                user_id=USER_ID,
                task_list_id=list_id,
                task_ids=[ids[2], theirs],
                transaction=async_connection,
            )

        assert await stored_positions(async_connection, [*ids, theirs]) == [1, 3, 5, 0]

    async def test_an_archived_list_is_refused_and_nothing_moves(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id, ids = await _seed(async_connection, archived=True)

        with pytest.raises(TaskListArchivedError):
            await service.reorder_list_tasks(
                user_id=USER_ID,
                task_list_id=list_id,
                task_ids=[ids[2]],
                transaction=async_connection,
            )

        assert await stored_positions(async_connection, ids) == [1, 3, 5]


# ---------------------------------------------------------------------------
# Concurrency: two real connections, committed rows.
# ---------------------------------------------------------------------------

Reorder = Callable[[AsyncConnection, str, int, list[int]], Coroutine[Any, Any, object]]


def _service(connection: AsyncConnection) -> TaskService:
    return service_on(connection, SqlUserSettingsRepository(connection))


async def _reorder_last_to_top(
    connection: AsyncConnection, owner: str, list_id: int, ids: list[int]
) -> object:
    """The list page's move of the bottom task to the top."""
    return await _service(connection).reorder_task(
        user_id=owner, task_id=ids[-1], after_task_id=None, transaction=connection
    )


async def _arrange_last_to_top(
    connection: AsyncConnection, owner: str, list_id: int, ids: list[int]
) -> object:
    """The same move as an agent's one-task block."""
    return await _service(connection).reorder_list_tasks(
        user_id=owner, task_list_id=list_id, task_ids=[ids[-1]], transaction=connection
    )


REORDERS = [_reorder_last_to_top, _arrange_last_to_top]
REORDER_IDS = ["reorder_task", "reorder_list_tasks"]


@asynccontextmanager
async def _committed(
    async_engine: AsyncEngine,
) -> AsyncIterator[tuple[str, int, list[int]]]:
    """A committed list with open tasks at 0, 1 and 2 under a one-off owner.

    Built on :func:`committed_task_list`, whose clean-up deletes everything the
    owner leaves behind — the outbox rows the create and reopen overlaps
    publish included, which later tests asserting an empty outbox would see.
    """
    async with committed_task_list(async_engine) as (owner, list_id):
        async with async_engine.begin() as setup:
            ids = [
                await create_list_task(
                    setup, task_list_id=list_id, position=position, user_id=owner
                )
                for position in (0, 1, 2)
            ]
        yield owner, list_id, ids


@pytest.mark.slow
class TestTheReorderNeverDeadlocksAgainstATaskWrite:
    """A task write locks its task, then shares its list (``_hold_list_writable``).

    The interleaving that deadlocked an exclusive list lock: the edit holds task
    A; the reorder starts, takes its list lock and waits for A; the edit then
    asks for its list share lock. With the reorder's list lock ``FOR SHARE``
    the edit is granted it, commits, and the reorder goes on.
    """

    @pytest.mark.parametrize("reorder", REORDERS, ids=REORDER_IDS)
    async def test_an_edit_holding_a_task_then_sharing_the_list(
        self, reorder: Reorder, async_engine: AsyncEngine
    ) -> None:
        async with _committed(async_engine) as (owner, list_id, ids):
            async with async_engine.connect() as one, async_engine.connect() as two:
                pending: asyncio.Task[Any] | None = None
                try:
                    two_pid = await backend_pid(two)
                    async with unit_of_work(one):
                        repo = SqlTaskRepository(one)
                        held = await repo.find_by_id_for_update(ids[0], owner)
                        assert held is not None
                        pending = asyncio.create_task(reorder(two, owner, list_id, ids))
                        await wait_until_blocked_on_a_lock(async_engine, two_pid)
                        # The edit's second lock, as every task write takes it.
                        shared = await bounded(
                            SqlTaskListRepository(one).find_by_id_for_share(
                                list_id, owner
                            )
                        )
                        assert shared is not None
                        await repo.save(replace(held, text="edited meanwhile"))
                    await bounded(pending)
                finally:
                    await settle(pending)

            async with async_engine.connect() as check:
                assert await _open_order(check, list_id, owner) == [
                    ids[2],
                    ids[0],
                    ids[1],
                ]
                edited = await SqlTaskRepository(check).find_by_id(ids[0], owner)
                assert edited is not None
                assert edited.text == "edited meanwhile"


def _create(owner: str, list_id: int) -> Callable[[AsyncConnection], Any]:
    async def run(connection: AsyncConnection) -> None:
        await _service(connection).create_list_task(
            user_id=owner,
            task_list_id=list_id,
            text="joins the bottom",
            transaction=connection,
        )

    return run


def _run_reorder(
    reorder: Reorder, owner: str, list_id: int, ids: list[int]
) -> Callable[[AsyncConnection], Any]:
    async def run(connection: AsyncConnection) -> None:
        await reorder(connection, owner, list_id, ids)

    return run


@pytest.mark.slow
class TestOverlappingWritesOnTheList:
    @pytest.mark.parametrize("reorder", REORDERS, ids=REORDER_IDS)
    @pytest.mark.parametrize("create_first", [True, False], ids=["create", "reorder"])
    async def test_a_create_and_a_reorder_both_land(
        self, reorder: Reorder, create_first: bool, async_engine: AsyncEngine
    ) -> None:
        """The create's exclusive list lock and the reorder's share lock queue,
        so the new task is at the bottom and the moved one at the top."""
        async with _committed(async_engine) as (owner, list_id, ids):
            create = _create(owner, list_id)
            move = _run_reorder(reorder, owner, list_id, ids)
            first, second = (create, move) if create_first else (move, create)

            await overlap(async_engine, first, second)

            async with async_engine.connect() as check:
                order = await _open_order(check, list_id, owner)
            assert order[:3] == [ids[2], ids[0], ids[1]]
            assert len(order) == 4

    @pytest.mark.parametrize("reorder", REORDERS, ids=REORDER_IDS)
    async def test_a_task_reopened_during_a_reorder_keeps_its_place(
        self, reorder: Reorder, async_engine: AsyncEngine
    ) -> None:
        """The reorder no longer excludes a reopen: the reopened task was not in
        the set it reordered, and keeps the position it held."""
        async with _committed(async_engine) as (owner, list_id, ids):
            async with async_engine.begin() as setup:
                done = await create_list_task(
                    setup,
                    task_list_id=list_id,
                    position=5,
                    status=TaskStatus.DONE,
                    user_id=owner,
                )
            async with async_engine.connect() as one, async_engine.connect() as two:
                async with unit_of_work(one):
                    await reorder(one, owner, list_id, ids)
                    await bounded(
                        _service(two).set_status(
                            user_id=owner,
                            task_id=done,
                            status=TaskStatus.NOT_DONE,
                            transaction=two,
                        )
                    )

            async with async_engine.connect() as check:
                assert await _open_order(check, list_id, owner) == [
                    ids[2],
                    ids[0],
                    ids[1],
                    done,
                ]
                assert await stored_positions(check, [done]) == [5]

"""Integration tests for the task repository's list membership and list reads.

Later phases build list pages, the Completed group, the sidebar's counts and the
move/reorder/remove operations on these methods, so this file holds the
repository to the spec's list rules (*The list page*, *Moving tasks*):

- a task joining a list — from no list, from another list, or rejoining its own
  — lands at the **bottom**, counting closed tasks so a reopened one keeps its
  slot;
- a list's open tasks read in the user's manual order, ``(position, id)``, and
  one can be moved to just after another, or to the top, without an event and
  without touching any task's ``updated_at``;
- a task leaves its list only with both journals, clearing every list column;
- closed tasks read most recently closed first, in pages with a total;
- open tasks are counted per list.

**Owner scoping.** The database lets a task reference another owner's list (the
foreign key is single-column), so every case is proven against a second user,
including a row of theirs seeded straight onto this user's list.

**Concurrency.** A join and a move on one list queue on the list's row lock
(the join takes it exclusively, the move ``FOR SHARE``), which is taken before
any task lock; two moves share it and queue on the open tasks' locks instead. The overlap tests commit real rows under a
one-off owner — two connections cannot share the savepoint fixture — and delete
them afterwards.
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.models.tasks import (
    TaskIcon,
    TaskListChangedConcurrentlyError,
    TaskListNotFoundError,
    TaskNotFoundError,
    TaskPage,
    TaskStatus,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import overlap
from tests.integration.tasks.task_seeding import (
    FIXED_PAST_INSTANT,
    OTHER_USER_ID,
    USER_ID,
    backdate_closed_at,
    backdate_updated_at,
    count,
    create_journal,
    create_list_task,
    create_task,
    seed_task_list,
    stored_updated_at,
)

DUE_DATE = date(2027, 3, 1)
_CHECK_VIOLATION = "23514"
_COUNT_OUTBOX = "SELECT COUNT(*) FROM outbox_events"


@pytest_asyncio.fixture
async def repo(async_connection: AsyncConnection) -> SqlTaskRepository:
    return SqlTaskRepository(async_connection)


async def _list_id(
    conn: AsyncConnection, name: str = "Packing", user_id: str = USER_ID
) -> int:
    task_list = await seed_task_list(conn, name, user_id=user_id)
    assert task_list.id is not None
    return task_list.id


@pytest_asyncio.fixture
async def list_id(async_connection: AsyncConnection) -> int:
    return await _list_id(async_connection)


@pytest_asyncio.fixture
async def journal_ids(journal_repository: SqlJournalRepository) -> tuple[int, int]:
    """A creating journal and a later one to be due in, as ``(creating, due)``."""
    creating_id = await create_journal(journal_repository, title="Where it arose")
    due_id = await create_journal(journal_repository, title="The trip", days_offset=7)
    return creating_id, due_id


async def _position(conn: AsyncConnection, task_id: int) -> int | None:
    position: int | None = (
        await conn.execute(
            text("SELECT position FROM tasks WHERE id = :id"), {"id": task_id}
        )
    ).scalar_one()
    return position


async def _membership(conn: AsyncConnection, task_id: int) -> tuple[object, ...]:
    row = (
        await conn.execute(
            text("SELECT task_list_id, position, due_date FROM tasks WHERE id = :id"),
            {"id": task_id},
        )
    ).one()
    return tuple(row)


async def _open_ids(repo: SqlTaskRepository, task_list_id: int) -> list[int]:
    tasks = await repo.find_open_tasks_on_list(task_list_id, USER_ID)
    return [task.id for task in tasks if task.id is not None]


@pytest.mark.integration
class TestAddToList:
    """Joining a list, or moving to another, lands a task at the bottom."""

    async def test_a_journal_only_task_joins_an_empty_list_at_the_top(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        journal_ids: tuple[int, int],
    ) -> None:
        creating_id, due_id = journal_ids
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        joined = await repo.add_to_list(task_id, list_id, USER_ID)

        assert (joined.task_list_id, joined.position) == (list_id, 0)
        found = await repo.find_by_id(task_id, USER_ID)
        assert found is not None
        assert (found.task_list_id, found.position) == (list_id, 0)
        # It keeps its journals: a journal-only task added to a list keeps both.
        assert (found.creating_journal_id, found.due_journal_id) == journal_ids

    async def test_the_bottom_counts_closed_tasks(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        journal_ids: tuple[int, int],
    ) -> None:
        await create_list_task(async_connection, task_list_id=list_id, position=0)
        await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=5,
            status=TaskStatus.DONE,
        )
        creating_id, due_id = journal_ids
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        joined = await repo.add_to_list(task_id, list_id, USER_ID)

        assert joined.position == 6

    async def test_moving_to_another_list_lands_at_its_bottom_keeping_the_rest(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
    ) -> None:
        target_id = await _list_id(async_connection, "Shopping")
        await create_list_task(async_connection, task_list_id=target_id, position=2)
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=0,
            due_date=DUE_DATE,
            flagged=True,
            icon=TaskIcon.STAR,
        )

        moved = await repo.add_to_list(task_id, target_id, USER_ID)

        assert (moved.task_list_id, moved.position) == (target_id, 3)
        assert (moved.due_date, moved.flagged, moved.icon) == (
            DUE_DATE,
            True,
            TaskIcon.STAR,
        )
        assert moved.status is TaskStatus.NOT_DONE

    async def test_rejoining_its_own_list_moves_a_task_to_the_bottom(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, position=0
        )
        await create_list_task(async_connection, task_list_id=list_id, position=1)

        rejoined = await repo.add_to_list(task_id, list_id, USER_ID)

        assert rejoined.position == 2

    async def test_another_users_tasks_on_the_list_do_not_move_the_bottom(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        journal_ids: tuple[int, int],
    ) -> None:
        await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=9,
            user_id=OTHER_USER_ID,
        )
        creating_id, due_id = journal_ids
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        joined = await repo.add_to_list(task_id, list_id, USER_ID)

        assert joined.position == 0


@pytest.mark.integration
class TestAddToListOwnerScoping:
    """Neither the task nor the list may be someone else's."""

    async def test_another_users_list_is_not_found(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
    ) -> None:
        theirs = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, position=4
        )

        with pytest.raises(TaskListNotFoundError):
            await repo.add_to_list(task_id, theirs, USER_ID)

        assert await _membership(async_connection, task_id) == (list_id, 4, None)

    async def test_another_users_task_is_not_found(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        their_task = await create_list_task(
            async_connection,
            task_list_id=their_list,
            position=0,
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskNotFoundError):
            await repo.add_to_list(their_task, list_id, USER_ID)

        assert await _membership(async_connection, their_task) == (
            their_list,
            0,
            None,
        )

    async def test_an_unknown_list_is_not_found(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        with pytest.raises(TaskListNotFoundError):
            await repo.add_to_list(task_id, 2_000_000_000, USER_ID)

    async def test_an_unknown_task_is_not_found(
        self, repo: SqlTaskRepository, list_id: int
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            await repo.add_to_list(2_000_000_000, list_id, USER_ID)


@pytest.mark.integration
class TestMoveWithinList:
    """Moving a task after another, or to the top, rewrites open positions only."""

    @pytest_asyncio.fixture
    async def tasks(self, async_connection: AsyncConnection, list_id: int) -> list[int]:
        """Four open tasks at positions 1, 3, 5 and 6, around closed ones."""
        ids = [
            await create_list_task(
                async_connection, task_list_id=list_id, position=position
            )
            for position in (1, 3, 5, 6)
        ]
        await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=2,
            status=TaskStatus.DONE,
        )
        return ids

    async def test_a_task_moves_to_the_top(
        self, repo: SqlTaskRepository, list_id: int, tasks: list[int]
    ) -> None:
        first, second, third, fourth = tasks

        reordered = await repo.move_within_list(third, USER_ID, after_task_id=None)

        assert [task.id for task in reordered] == [third, first, second, fourth]
        assert await _open_ids(repo, list_id) == [third, first, second, fourth]

    async def test_a_task_moves_after_another(
        self, repo: SqlTaskRepository, list_id: int, tasks: list[int]
    ) -> None:
        first, second, third, fourth = tasks

        await repo.move_within_list(fourth, USER_ID, after_task_id=first)

        assert await _open_ids(repo, list_id) == [first, fourth, second, third]

    async def test_a_task_moves_to_the_bottom(
        self, repo: SqlTaskRepository, list_id: int, tasks: list[int]
    ) -> None:
        first, second, third, fourth = tasks

        await repo.move_within_list(first, USER_ID, after_task_id=fourth)

        assert await _open_ids(repo, list_id) == [second, third, fourth, first]

    async def test_closed_tasks_keep_their_positions(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        tasks: list[int],
    ) -> None:
        closed_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=4,
            status=TaskStatus.CANCELLED,
        )

        await repo.move_within_list(tasks[3], USER_ID, after_task_id=None)

        assert await _position(async_connection, closed_id) == 4
        positions = [await _position(async_connection, task_id) for task_id in tasks]
        # The open tasks' existing positions, handed out again.
        assert sorted(p for p in positions if p is not None) == [1, 3, 5, 6]

    async def test_reordering_is_not_an_edit(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        tasks: list[int],
    ) -> None:
        for task_id in tasks:
            await backdate_updated_at(async_connection, task_id)
        outbox_before = await count(async_connection, _COUNT_OUTBOX, {})

        await repo.move_within_list(tasks[2], USER_ID, after_task_id=None)

        for task_id in tasks:
            assert await stored_updated_at(async_connection, task_id) == (
                FIXED_PAST_INSTANT
            )
        assert await count(async_connection, _COUNT_OUTBOX, {}) == outbox_before

    async def test_naming_the_current_predecessor_writes_nothing(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        tasks: list[int],
    ) -> None:
        reordered = await repo.move_within_list(
            tasks[1], USER_ID, after_task_id=tasks[0]
        )

        assert [task.id for task in reordered] == tasks
        assert [await _position(async_connection, t) for t in tasks] == [1, 3, 5, 6]

    async def test_a_closed_task_cannot_be_moved(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        tasks: list[int],
    ) -> None:
        closed_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=8,
            status=TaskStatus.DONE,
        )

        with pytest.raises(TaskListChangedConcurrentlyError, match=str(closed_id)):
            await repo.move_within_list(closed_id, USER_ID, after_task_id=None)

    async def test_a_journal_only_task_cannot_be_moved(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        journal_ids: tuple[int, int],
    ) -> None:
        creating_id, due_id = journal_ids
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        with pytest.raises(ValueError, match="not on a list"):
            await repo.move_within_list(task_id, USER_ID, after_task_id=None)

    async def test_an_anchor_on_another_list_is_refused(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        tasks: list[int],
    ) -> None:
        other_list = await _list_id(async_connection, "Shopping")
        elsewhere = await create_list_task(async_connection, task_list_id=other_list)

        with pytest.raises(TaskListChangedConcurrentlyError, match=str(elsewhere)):
            await repo.move_within_list(tasks[0], USER_ID, after_task_id=elsewhere)

    async def test_a_closed_anchor_is_refused(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        tasks: list[int],
    ) -> None:
        closed_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=7,
            status=TaskStatus.DONE,
        )

        with pytest.raises(TaskListChangedConcurrentlyError, match=str(closed_id)):
            await repo.move_within_list(tasks[0], USER_ID, after_task_id=closed_id)

    async def test_a_task_cannot_follow_itself(
        self, repo: SqlTaskRepository, tasks: list[int]
    ) -> None:
        with pytest.raises(ValueError, match="itself"):
            await repo.move_within_list(tasks[0], USER_ID, after_task_id=tasks[0])

    async def test_another_users_task_is_not_found(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        their_task = await create_list_task(
            async_connection, task_list_id=their_list, user_id=OTHER_USER_ID
        )

        with pytest.raises(TaskNotFoundError):
            await repo.move_within_list(their_task, USER_ID, after_task_id=None)

    async def test_another_users_row_on_the_list_is_neither_read_nor_moved(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        tasks: list[int],
    ) -> None:
        intruder = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=0,
            user_id=OTHER_USER_ID,
        )

        reordered = await repo.move_within_list(tasks[3], USER_ID, after_task_id=None)

        assert intruder not in [task.id for task in reordered]
        assert await _position(async_connection, intruder) == 0


@pytest.mark.integration
class TestArrangeOpenTasks:
    """A block of open tasks moved at once: top, after one anchor, before another."""

    @pytest_asyncio.fixture
    async def tasks(self, async_connection: AsyncConnection, list_id: int) -> list[int]:
        """Four open tasks at positions 1, 3, 5 and 6, around a closed one at 2."""
        ids = [
            await create_list_task(
                async_connection, task_list_id=list_id, position=position
            )
            for position in (1, 3, 5, 6)
        ]
        await create_list_task(
            async_connection, task_list_id=list_id, position=2, status=TaskStatus.DONE
        )
        return ids

    async def test_naming_every_task_sets_the_whole_order(
        self, repo: SqlTaskRepository, list_id: int, tasks: list[int]
    ) -> None:
        first, second, third, fourth = tasks

        arranged = await repo.arrange_open_tasks(
            list_id,
            USER_ID,
            task_ids=[fourth, second, first, third],
            after_task_id=None,
            before_task_id=None,
        )

        assert [task.id for task in arranged] == [fourth, second, first, third]
        assert await _open_ids(repo, list_id) == [fourth, second, first, third]

    async def test_a_prefix_goes_first_and_the_rest_keep_their_order(
        self, repo: SqlTaskRepository, list_id: int, tasks: list[int]
    ) -> None:
        first, second, third, fourth = tasks

        await repo.arrange_open_tasks(
            list_id,
            USER_ID,
            task_ids=[third, fourth],
            after_task_id=None,
            before_task_id=None,
        )

        assert await _open_ids(repo, list_id) == [third, fourth, first, second]

    async def test_the_block_lands_after_an_anchor(
        self, repo: SqlTaskRepository, list_id: int, tasks: list[int]
    ) -> None:
        first, second, third, fourth = tasks

        await repo.arrange_open_tasks(
            list_id,
            USER_ID,
            task_ids=[fourth, first],
            after_task_id=second,
            before_task_id=None,
        )

        assert await _open_ids(repo, list_id) == [second, fourth, first, third]

    async def test_the_block_lands_before_an_anchor(
        self, repo: SqlTaskRepository, list_id: int, tasks: list[int]
    ) -> None:
        first, second, third, fourth = tasks

        await repo.arrange_open_tasks(
            list_id,
            USER_ID,
            task_ids=[first],
            after_task_id=None,
            before_task_id=fourth,
        )

        assert await _open_ids(repo, list_id) == [second, third, first, fourth]

    async def test_closed_tasks_keep_their_positions_and_nothing_is_an_edit(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        tasks: list[int],
    ) -> None:
        closed_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=4,
            status=TaskStatus.CANCELLED,
        )
        for task_id in tasks:
            await backdate_updated_at(async_connection, task_id)
        outbox_before = await count(async_connection, _COUNT_OUTBOX, {})

        await repo.arrange_open_tasks(
            list_id,
            USER_ID,
            task_ids=list(reversed(tasks)),
            after_task_id=None,
            before_task_id=None,
        )

        assert await _position(async_connection, closed_id) == 4
        positions = [await _position(async_connection, task_id) for task_id in tasks]
        assert sorted(p for p in positions if p is not None) == [1, 3, 5, 6]
        for task_id in tasks:
            assert await stored_updated_at(async_connection, task_id) == (
                FIXED_PAST_INSTANT
            )
        assert await count(async_connection, _COUNT_OUTBOX, {}) == outbox_before

    async def test_an_arrangement_already_in_effect_writes_nothing(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        tasks: list[int],
    ) -> None:
        arranged = await repo.arrange_open_tasks(
            list_id,
            USER_ID,
            task_ids=tasks[:2],
            after_task_id=None,
            before_task_id=None,
        )

        assert [task.id for task in arranged] == tasks
        assert [await _position(async_connection, t) for t in tasks] == [1, 3, 5, 6]

    @pytest.mark.parametrize("role", ["named", "after", "before"])
    async def test_a_closed_task_named_anywhere_is_a_conflict(
        self,
        role: str,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        tasks: list[int],
    ) -> None:
        closed_id = await create_list_task(
            async_connection, task_list_id=list_id, position=7, status=TaskStatus.DONE
        )
        task_ids = [tasks[0], closed_id] if role == "named" else [tasks[0]]

        with pytest.raises(TaskListChangedConcurrentlyError, match=str(closed_id)):
            await repo.arrange_open_tasks(
                list_id,
                USER_ID,
                task_ids=task_ids,
                after_task_id=closed_id if role == "after" else None,
                before_task_id=closed_id if role == "before" else None,
            )

        assert [await _position(async_connection, t) for t in tasks] == [1, 3, 5, 6]

    async def test_another_users_list_is_not_found(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        their_task = await create_list_task(
            async_connection, task_list_id=their_list, user_id=OTHER_USER_ID
        )

        with pytest.raises(TaskListNotFoundError):
            await repo.arrange_open_tasks(
                their_list,
                USER_ID,
                task_ids=[their_task],
                after_task_id=None,
                before_task_id=None,
            )

    async def test_another_users_row_on_the_list_is_a_conflict_and_not_moved(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        tasks: list[int],
    ) -> None:
        intruder = await create_list_task(
            async_connection, task_list_id=list_id, position=0, user_id=OTHER_USER_ID
        )

        with pytest.raises(TaskListChangedConcurrentlyError, match=str(intruder)):
            await repo.arrange_open_tasks(
                list_id,
                USER_ID,
                task_ids=[tasks[3], intruder],
                after_task_id=None,
                before_task_id=None,
            )

        assert await _position(async_connection, intruder) == 0
        assert [await _position(async_connection, t) for t in tasks] == [1, 3, 5, 6]


@pytest.mark.integration
class TestRemoveFromList:
    """A task leaves its list only with both journals, clearing every list column."""

    async def test_a_task_with_both_journals_leaves_its_list(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
        journal_ids: tuple[int, int],
    ) -> None:
        creating_id, due_id = journal_ids
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=3,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        left = await repo.remove_from_list(task_id, USER_ID)

        assert (left.task_list_id, left.position, left.due_date) == (None, None, None)
        assert await _membership(async_connection, task_id) == (None, None, None)
        assert (left.creating_journal_id, left.due_journal_id) == journal_ids

    async def test_a_task_without_both_journals_is_refused_by_the_table(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, position=2, due_date=DUE_DATE
        )

        with pytest.raises(IntegrityError) as refused:
            async with async_connection.begin_nested():
                await repo.remove_from_list(task_id, USER_ID)

        assert getattr(refused.value.orig, "sqlstate", None) == _CHECK_VIOLATION
        assert "ck_tasks_journal_only_has_both_anchors" in str(refused.value)
        assert await _membership(async_connection, task_id) == (list_id, 2, DUE_DATE)

    async def test_a_journal_only_task_is_not_on_a_list(
        self,
        async_connection: AsyncConnection,
        repo: SqlTaskRepository,
        journal_ids: tuple[int, int],
    ) -> None:
        creating_id, due_id = journal_ids
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        with pytest.raises(ValueError, match="not on a list"):
            await repo.remove_from_list(task_id, USER_ID)

    async def test_another_users_task_is_not_found(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        their_task = await create_list_task(
            async_connection, task_list_id=their_list, user_id=OTHER_USER_ID
        )

        with pytest.raises(TaskNotFoundError):
            await repo.remove_from_list(their_task, USER_ID)

        assert await _membership(async_connection, their_task) == (their_list, 0, None)


@pytest.mark.integration
class TestFindOpenTasksOnList:
    """A list's open tasks, in the user's manual order."""

    async def test_open_tasks_read_in_position_then_id_order(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository, list_id: int
    ) -> None:
        # Positions run against id order, with a tie broken by id.
        last = await create_list_task(
            async_connection, task_list_id=list_id, position=7
        )
        tie_first = await create_list_task(
            async_connection, task_list_id=list_id, position=2
        )
        tie_second = await create_list_task(
            async_connection, task_list_id=list_id, position=2
        )
        top = await create_list_task(async_connection, task_list_id=list_id, position=0)

        assert await _open_ids(repo, list_id) == [top, tie_first, tie_second, last]

    async def test_only_not_done_tasks_on_this_list_are_read(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository, list_id: int
    ) -> None:
        other_list = await _list_id(async_connection, "Shopping")
        open_id = await create_list_task(async_connection, task_list_id=list_id)
        for status in (TaskStatus.DONE, TaskStatus.CANCELLED):
            await create_list_task(
                async_connection, task_list_id=list_id, position=1, status=status
            )
        await create_list_task(async_connection, task_list_id=other_list)

        assert await _open_ids(repo, list_id) == [open_id]

    async def test_an_empty_list_reads_nothing(
        self, repo: SqlTaskRepository, list_id: int
    ) -> None:
        assert await repo.find_open_tasks_on_list(list_id, USER_ID) == []

    async def test_another_users_list_reads_nothing(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        await create_list_task(
            async_connection, task_list_id=their_list, user_id=OTHER_USER_ID
        )

        assert await repo.find_open_tasks_on_list(their_list, USER_ID) == []

    async def test_another_users_row_on_this_list_is_not_read(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository, list_id: int
    ) -> None:
        mine = await create_list_task(async_connection, task_list_id=list_id)
        await create_list_task(
            async_connection, task_list_id=list_id, user_id=OTHER_USER_ID
        )

        assert await _open_ids(repo, list_id) == [mine]

    async def test_my_row_on_another_users_list_is_not_read(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        await create_list_task(async_connection, task_list_id=their_list)

        assert await repo.find_open_tasks_on_list(their_list, USER_ID) == []


@pytest.mark.integration
class TestFindClosedTasksOnList:
    """A list's done and cancelled tasks, most recently closed first, in pages."""

    @pytest_asyncio.fixture
    async def closed(
        self, async_connection: AsyncConnection, list_id: int
    ) -> list[int]:
        """Five closed tasks, most recently closed first, beside an open one."""
        await create_list_task(async_connection, task_list_id=list_id)
        ids = []
        for days_ago, status in enumerate(
            (
                TaskStatus.DONE,
                TaskStatus.CANCELLED,
                TaskStatus.DONE,
                TaskStatus.DONE,
                TaskStatus.CANCELLED,
            )
        ):
            task_id = await create_list_task(
                async_connection, task_list_id=list_id, position=1, status=status
            )
            await backdate_closed_at(
                async_connection,
                task_id,
                FIXED_PAST_INSTANT - timedelta(days=days_ago),
            )
            ids.append(task_id)
        return ids

    async def test_closed_tasks_read_most_recently_closed_first(
        self, repo: SqlTaskRepository, list_id: int, closed: list[int]
    ) -> None:
        page = await repo.find_closed_tasks_on_list(list_id, USER_ID, limit=10)

        assert [task.id for task in page.tasks] == closed
        assert page.total == 5

    async def test_a_tie_in_close_time_is_broken_by_newest_id(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository, list_id: int
    ) -> None:
        older = await create_list_task(
            async_connection, task_list_id=list_id, status=TaskStatus.DONE
        )
        newer = await create_list_task(
            async_connection, task_list_id=list_id, status=TaskStatus.DONE
        )

        page = await repo.find_closed_tasks_on_list(list_id, USER_ID, limit=10)

        assert [task.id for task in page.tasks] == [newer, older]

    async def test_pages_carry_the_full_total(
        self, repo: SqlTaskRepository, list_id: int, closed: list[int]
    ) -> None:
        first = await repo.find_closed_tasks_on_list(list_id, USER_ID, limit=2)
        second = await repo.find_closed_tasks_on_list(
            list_id, USER_ID, limit=2, offset=2
        )
        last = await repo.find_closed_tasks_on_list(list_id, USER_ID, limit=2, offset=4)

        assert [task.id for task in first.tasks] == closed[0:2]
        assert [task.id for task in second.tasks] == closed[2:4]
        assert [task.id for task in last.tasks] == closed[4:]
        assert (first.total, second.total, last.total) == (5, 5, 5)

    async def test_a_page_past_the_end_still_reports_the_total(
        self, repo: SqlTaskRepository, list_id: int, closed: list[int]
    ) -> None:
        page = await repo.find_closed_tasks_on_list(
            list_id, USER_ID, limit=2, offset=10
        )

        assert page == TaskPage(tasks=(), total=5)

    async def test_editing_a_closed_task_does_not_reorder_it(
        self, repo: SqlTaskRepository, list_id: int, closed: list[int]
    ) -> None:
        oldest = await repo.find_by_id(closed[-1], USER_ID)
        assert oldest is not None

        await repo.save(replace(oldest, text="renamed"))

        page = await repo.find_closed_tasks_on_list(list_id, USER_ID, limit=10)
        assert [task.id for task in page.tasks] == closed

    async def test_another_users_list_reads_an_empty_page(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        await create_list_task(
            async_connection,
            task_list_id=their_list,
            status=TaskStatus.DONE,
            user_id=OTHER_USER_ID,
        )

        page = await repo.find_closed_tasks_on_list(their_list, USER_ID, limit=10)

        assert page == TaskPage(tasks=(), total=0)

    async def test_another_users_row_on_this_list_is_not_read(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository, list_id: int
    ) -> None:
        await create_list_task(
            async_connection,
            task_list_id=list_id,
            status=TaskStatus.DONE,
            user_id=OTHER_USER_ID,
        )

        page = await repo.find_closed_tasks_on_list(list_id, USER_ID, limit=10)

        assert page == TaskPage(tasks=(), total=0)

    async def test_my_row_on_another_users_list_is_not_read(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        await create_list_task(
            async_connection, task_list_id=their_list, status=TaskStatus.DONE
        )

        page = await repo.find_closed_tasks_on_list(their_list, USER_ID, limit=10)

        assert page == TaskPage(tasks=(), total=0)


@pytest.mark.integration
class TestCountOpenTasksByList:
    """Open-task counts for several lists in one read."""

    async def test_open_tasks_are_counted_per_list(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository, list_id: int
    ) -> None:
        other_list = await _list_id(async_connection, "Shopping")
        empty_list = await _list_id(async_connection, "Empty")
        for _ in range(3):
            await create_list_task(async_connection, task_list_id=list_id)
        await create_list_task(
            async_connection, task_list_id=list_id, status=TaskStatus.DONE
        )
        await create_list_task(async_connection, task_list_id=other_list)
        await create_list_task(
            async_connection, task_list_id=empty_list, status=TaskStatus.CANCELLED
        )

        counts = await repo.count_open_tasks_by_list(
            [list_id, other_list, empty_list], USER_ID
        )

        assert counts == {list_id: 3, other_list: 1}

    async def test_other_users_tasks_are_not_counted(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository, list_id: int
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        await create_list_task(
            async_connection, task_list_id=their_list, user_id=OTHER_USER_ID
        )
        await create_list_task(
            async_connection, task_list_id=list_id, user_id=OTHER_USER_ID
        )

        assert await repo.count_open_tasks_by_list([list_id, their_list], USER_ID) == {}

    async def test_my_rows_on_another_users_list_are_not_counted(
        self, async_connection: AsyncConnection, repo: SqlTaskRepository
    ) -> None:
        their_list = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        await create_list_task(async_connection, task_list_id=their_list)

        assert await repo.count_open_tasks_by_list([their_list], USER_ID) == {}

    async def test_no_lists_count_nothing(self, repo: SqlTaskRepository) -> None:
        assert await repo.count_open_tasks_by_list([], USER_ID) == {}


# --- Concurrency -------------------------------------------------------------


@pytest_asyncio.fixture
async def racing_owner(async_engine: AsyncEngine) -> AsyncIterator[str]:
    """A one-off owner whose committed rows are deleted after the test."""
    owner = f"race-{uuid4()}"
    yield owner
    async with async_engine.connect() as cleanup:
        await cleanup.execute(
            text("DELETE FROM tasks WHERE user_id = :owner"), {"owner": owner}
        )
        await cleanup.execute(
            text("DELETE FROM task_lists WHERE user_id = :owner"), {"owner": owner}
        )
        await cleanup.commit()


async def _committed_list(
    async_engine: AsyncEngine, owner: str, positions: tuple[int, ...]
) -> tuple[int, list[int]]:
    """Commit a list and open tasks at ``positions``; return their ids."""
    async with async_engine.connect() as conn:
        list_id = await _list_id(conn, "Racing", user_id=owner)
        ids = [
            await create_list_task(
                conn, task_list_id=list_id, position=position, user_id=owner
            )
            for position in positions
        ]
        await conn.commit()
    return list_id, ids


async def _committed_open_order(
    async_engine: AsyncEngine, list_id: int, owner: str
) -> list[tuple[int, int | None]]:
    async with async_engine.connect() as conn:
        tasks = await SqlTaskRepository(conn).find_open_tasks_on_list(list_id, owner)
    return [(task.id or 0, task.position) for task in tasks]


@pytest.mark.integration
@pytest.mark.slow
class TestConcurrentMembershipWrites:
    """Joins and moves on one list queue on its locks and never collide."""

    async def test_overlapping_joins_take_distinct_positions(
        self, async_engine: AsyncEngine, racing_owner: str
    ) -> None:
        list_id, _ = await _committed_list(async_engine, racing_owner, ())
        _, (first_id, second_id) = await _committed_list(
            async_engine, racing_owner, (0, 0)
        )

        async def first(conn: AsyncConnection) -> None:
            await SqlTaskRepository(conn).add_to_list(first_id, list_id, racing_owner)

        async def second(conn: AsyncConnection) -> None:
            async with unit_of_work(conn):
                await SqlTaskRepository(conn).add_to_list(
                    second_id, list_id, racing_owner
                )

        await overlap(async_engine, first, second)

        assert await _committed_open_order(async_engine, list_id, racing_owner) == [
            (first_id, 0),
            (second_id, 1),
        ]

    async def test_a_join_waits_for_an_overlapping_move(
        self, async_engine: AsyncEngine, racing_owner: str
    ) -> None:
        list_id, (top, bottom) = await _committed_list(
            async_engine, racing_owner, (0, 1)
        )
        _, (joiner,) = await _committed_list(async_engine, racing_owner, (0,))

        async def move(conn: AsyncConnection) -> None:
            await SqlTaskRepository(conn).move_within_list(
                bottom, racing_owner, after_task_id=None
            )

        async def join(conn: AsyncConnection) -> None:
            async with unit_of_work(conn):
                await SqlTaskRepository(conn).add_to_list(joiner, list_id, racing_owner)

        await overlap(async_engine, move, join)

        assert await _committed_open_order(async_engine, list_id, racing_owner) == [
            (bottom, 0),
            (top, 1),
            (joiner, 2),
        ]

    async def test_overlapping_moves_both_land(
        self, async_engine: AsyncEngine, racing_owner: str
    ) -> None:
        list_id, (a, b, c) = await _committed_list(
            async_engine, racing_owner, (0, 1, 2)
        )

        async def move_c_to_top(conn: AsyncConnection) -> None:
            await SqlTaskRepository(conn).move_within_list(
                c, racing_owner, after_task_id=None
            )

        async def move_a_to_bottom(conn: AsyncConnection) -> None:
            async with unit_of_work(conn):
                await SqlTaskRepository(conn).move_within_list(
                    a, racing_owner, after_task_id=b
                )

        await overlap(async_engine, move_c_to_top, move_a_to_bottom)

        # c, a, b after the first; a follows b after the second.
        order = await _committed_open_order(async_engine, list_id, racing_owner)
        assert [task_id for task_id, _ in order] == [c, b, a]

    async def test_a_move_waits_for_an_edit_holding_a_sibling(
        self, async_engine: AsyncEngine, racing_owner: str
    ) -> None:
        list_id, (a, b) = await _committed_list(async_engine, racing_owner, (0, 1))

        async def edit_a(conn: AsyncConnection) -> None:
            repo = SqlTaskRepository(conn)
            held = await repo.find_by_id_for_update(a, racing_owner)
            assert held is not None
            await repo.save(replace(held, text="edited while moving"))

        async def move_b(conn: AsyncConnection) -> None:
            async with unit_of_work(conn):
                await SqlTaskRepository(conn).move_within_list(
                    b, racing_owner, after_task_id=None
                )

        await overlap(async_engine, edit_a, move_b)

        order = await _committed_open_order(async_engine, list_id, racing_owner)
        assert [task_id for task_id, _ in order] == [b, a]
        async with async_engine.connect() as conn:
            edited = await SqlTaskRepository(conn).find_by_id(a, racing_owner)
        assert edited is not None
        assert edited.text == "edited while moving"

    async def test_a_neighbour_closed_while_the_move_waits_is_a_conflict(
        self, async_engine: AsyncEngine, racing_owner: str
    ) -> None:
        """A plain status edit never takes the list's lock, so the neighbour a
        move names can close between the request and the lock. The move waits on
        the neighbour's row, sees it closed, and refuses as a conflict rather than
        failing as a caller's bug — and moves nothing."""
        list_id, (a, b) = await _committed_list(async_engine, racing_owner, (0, 1))

        async def close_a(conn: AsyncConnection) -> None:
            repo = SqlTaskRepository(conn)
            held = await repo.find_by_id_for_update(a, racing_owner)
            assert held is not None
            await repo.save(replace(held, status=TaskStatus.DONE))

        async def move_b_after_a(conn: AsyncConnection) -> None:
            with pytest.raises(TaskListChangedConcurrentlyError, match=str(a)):
                async with unit_of_work(conn):
                    await SqlTaskRepository(conn).move_within_list(
                        b, racing_owner, after_task_id=a
                    )

        await overlap(async_engine, close_a, move_b_after_a)

        assert await _committed_open_order(async_engine, list_id, racing_owner) == [
            (b, 1)
        ]

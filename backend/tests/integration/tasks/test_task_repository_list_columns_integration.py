"""Integration tests for ``SqlTaskRepository`` and the list columns of 0146.

A task may now live on a list, with a position, a due date, a flag and an icon,
and with either journal anchor missing. This file holds the repository to three
promises about those columns:

- **reads are lossless** — every shape a list task may take reads back as the
  entity, through both the plain and the locking read;
- **``save`` drops nothing it writes** — the flag, icon and due date persist, and
  a text or status edit leaves a task's list and position alone. List
  membership is not ``save``'s to write: it belongs to the membership
  operations, as ``TaskList.position`` does, so inserting a task on a list is
  refused rather than silently stored as a journal-only task;
- **owner scoping** holds for list tasks exactly as for journal-only ones.

List tasks are seeded as rows (``create_list_task``): nothing in the product can
create one yet. The CHECKs themselves are proven in
``test_task_list_columns_constraints.py``.
"""

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
import pytest_asyncio
from core_shared.models.tasks import Task, TaskIcon, TaskNotFoundError, TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from tests.integration.tasks.task_seeding import (
    COUNT_TASKS,
    FIXED_PAST_INSTANT,
    OTHER_USER_ID,
    USER_ID,
    backdate_closed_at,
    count,
    create_journal,
    create_list_task,
    create_task,
    seed_task_list,
    stored_closed_at,
)

DUE_DATE = date(2027, 3, 1)


@pytest_asyncio.fixture
async def task_repository(async_connection: AsyncConnection) -> SqlTaskRepository:
    return SqlTaskRepository(async_connection)


@pytest_asyncio.fixture
async def list_id(async_connection: AsyncConnection) -> int:
    return await _seed_list_id(async_connection)


@pytest_asyncio.fixture
async def journal_ids(journal_repository: SqlJournalRepository) -> tuple[int, int]:
    """A creating journal and a later one to be due in, as ``(creating, due)``."""
    creating_id = await create_journal(journal_repository, title="Where it arose")
    due_id = await create_journal(journal_repository, title="The trip", days_offset=7)
    return creating_id, due_id


async def _seed_list_id(conn: AsyncConnection, name: str = "Packing") -> int:
    task_list = await seed_task_list(conn, name)
    assert task_list.id is not None
    return task_list.id


async def _read(
    task_repository: SqlTaskRepository, task_id: int, user_id: str = USER_ID
) -> Task:
    found = await task_repository.find_by_id(task_id, user_id)
    assert found is not None
    return found


@pytest.mark.integration
class TestListTaskReads:
    """Each list-task shape reads back as the entity."""

    async def test_a_list_task_with_no_journal_reads_back(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        found = await _read(task_repository, task_id)

        assert found.task_list_id == list_id
        assert found.position == 0
        assert found.creating_journal_id is None
        assert found.due_journal_id is None
        assert found.due_date is None
        assert found.flagged is False
        assert found.icon is None

    async def test_a_list_task_with_a_due_date_reads_back(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, position=2, due_date=DUE_DATE
        )

        found = await _read(task_repository, task_id)

        assert found.position == 2
        assert found.due_date == DUE_DATE
        assert found.due_journal_id is None

    async def test_a_list_task_with_a_due_journal_reads_back(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
        journal_ids: tuple[int, int],
    ) -> None:
        _, due_id = journal_ids
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=due_id
        )

        found = await _read(task_repository, task_id)

        assert found.due_journal_id == due_id
        assert found.creating_journal_id is None
        assert found.due_date is None

    async def test_a_list_task_with_only_a_creating_journal_reads_back(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
        journal_ids: tuple[int, int],
    ) -> None:
        creating_id, _ = journal_ids
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, creating_journal_id=creating_id
        )

        found = await _read(task_repository, task_id)

        assert found.creating_journal_id == creating_id
        assert found.due_journal_id is None

    async def test_a_flagged_list_task_with_an_icon_reads_back(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, flagged=True, icon=TaskIcon.STAR
        )

        found = await _read(task_repository, task_id)

        assert found.flagged is True
        assert found.icon is TaskIcon.STAR

    async def test_the_locking_read_maps_the_list_columns(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=4,
            due_date=DUE_DATE,
            flagged=True,
            icon=TaskIcon.HEART,
        )

        found = await task_repository.find_by_id_for_update(task_id, USER_ID)

        assert found is not None
        assert found.task_list_id == list_id
        assert found.position == 4
        assert found.due_date == DUE_DATE
        assert found.flagged is True
        assert found.icon is TaskIcon.HEART

    async def test_a_journal_only_task_reads_back_on_no_list(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        journal_ids: tuple[int, int],
    ) -> None:
        creating_id, due_id = journal_ids
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        found = await _read(task_repository, task_id)

        assert found.task_list_id is None
        assert found.position is None
        assert found.due_date is None
        assert found.flagged is False
        assert found.icon is None


@pytest.mark.integration
class TestSaveWithListColumns:
    """``save`` writes the scalars and never touches membership."""

    async def test_a_status_edit_leaves_a_list_tasks_columns_alone(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=3,
            due_date=DUE_DATE,
            flagged=True,
            icon=TaskIcon.STAR,
        )
        task = await _read(task_repository, task_id)

        await task_repository.save(replace(task, status=TaskStatus.DONE))

        found = await _read(task_repository, task_id)
        assert found.status is TaskStatus.DONE
        assert found.task_list_id == list_id
        assert found.position == 3
        assert found.due_date == DUE_DATE
        assert found.flagged is True
        assert found.icon is TaskIcon.STAR

    async def test_flag_icon_and_due_date_are_written(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(async_connection, task_list_id=list_id)
        task = await _read(task_repository, task_id)

        saved = await task_repository.save(
            replace(task, flagged=True, icon=TaskIcon.STAR, due_date=DUE_DATE)
        )

        found = await _read(task_repository, task_id)
        assert (found.flagged, found.icon, found.due_date) == (
            True,
            TaskIcon.STAR,
            DUE_DATE,
        )
        assert (saved.flagged, saved.icon, saved.due_date) == (
            True,
            TaskIcon.STAR,
            DUE_DATE,
        )

    async def test_flag_icon_and_due_date_are_cleared(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            due_date=DUE_DATE,
            flagged=True,
            icon=TaskIcon.STAR,
        )
        task = await _read(task_repository, task_id)

        await task_repository.save(
            replace(task, flagged=False, icon=None, due_date=None)
        )

        found = await _read(task_repository, task_id)
        assert (found.flagged, found.icon, found.due_date) == (False, None, None)

    async def test_save_never_writes_list_membership(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        """Position belongs to reordering, as ``TaskList.position`` does.

        A save carrying a stale position must not undo a reorder that landed
        between this caller's read and its write.
        """
        other_list_id = await _seed_list_id(async_connection, name="Shopping")
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, position=1
        )
        task = await _read(task_repository, task_id)

        await task_repository.save(
            replace(task, task_list_id=other_list_id, position=9, text="renamed")
        )

        found = await _read(task_repository, task_id)
        assert found.text == "renamed"
        assert found.task_list_id == list_id
        assert found.position == 1

    async def test_a_journal_only_task_keeps_its_flag_and_icon_on_insert_and_update(
        self,
        task_repository: SqlTaskRepository,
        journal_ids: tuple[int, int],
    ) -> None:
        creating_id, due_id = journal_ids

        inserted = await task_repository.save(
            Task(
                user_id=USER_ID,
                text="bring the permit",
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                flagged=True,
                icon=TaskIcon.BOOKMARK,
            )
        )
        assert inserted.id is not None
        found = await _read(task_repository, inserted.id)
        assert (found.flagged, found.icon) == (True, TaskIcon.BOOKMARK)

        await task_repository.save(replace(found, icon=TaskIcon.STAR, flagged=False))

        updated = await _read(task_repository, inserted.id)
        assert (updated.flagged, updated.icon) == (False, TaskIcon.STAR)

    async def test_inserting_a_task_on_a_list_is_refused(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        """Not stored as a journal-only task, and nothing is written at all."""
        before = await count(async_connection, COUNT_TASKS, {"user_id": USER_ID})

        with pytest.raises(ValueError, match="list"):
            await task_repository.save(
                Task(user_id=USER_ID, text="pack the tent", task_list_id=list_id)
            )

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == (
            before
        )


@pytest.mark.integration
class TestListTaskOwnerScoping:
    """Another user's list task is neither readable nor writable."""

    async def test_another_user_cannot_read_a_list_task(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        assert await task_repository.find_by_id(task_id, OTHER_USER_ID) is None
        assert (
            await task_repository.find_by_id_for_update(task_id, OTHER_USER_ID) is None
        )

    async def test_another_user_cannot_update_a_list_task(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(async_connection, task_list_id=list_id)
        task = await _read(task_repository, task_id)

        with pytest.raises(TaskNotFoundError):
            await task_repository.save(
                replace(task, user_id=OTHER_USER_ID, flagged=True)
            )

        found = await _read(task_repository, task_id)
        assert found.flagged is False


@pytest.mark.integration
class TestSaveMaintainsClosedAt:
    """``save`` records when a task was closed, which orders a list's Completed.

    ``now()`` is the transaction's timestamp and the fixture shares one
    transaction, so every case that must tell a fresh stamp from a kept one
    backdates ``closed_at`` first.
    """

    async def test_inserting_a_done_task_stamps_closed_at(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        journal_ids: tuple[int, int],
    ) -> None:
        creating_id, due_id = journal_ids

        saved = await task_repository.save(
            Task(
                user_id=USER_ID,
                text="returned the book",
                status=TaskStatus.DONE,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
            )
        )

        assert saved.id is not None
        assert await stored_closed_at(async_connection, saved.id) is not None

    async def test_inserting_a_not_done_task_leaves_closed_at_empty(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        journal_ids: tuple[int, int],
    ) -> None:
        creating_id, due_id = journal_ids

        saved = await task_repository.save(
            Task(
                user_id=USER_ID,
                text="return the book",
                creating_journal_id=creating_id,
                due_journal_id=due_id,
            )
        )

        assert saved.id is not None
        assert await stored_closed_at(async_connection, saved.id) is None

    async def test_closing_a_task_stamps_closed_at(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(async_connection, task_list_id=list_id)
        task = await _read(task_repository, task_id)

        await task_repository.save(replace(task, status=TaskStatus.DONE))

        assert await stored_closed_at(async_connection, task_id) is not None

    async def test_reopening_a_task_clears_closed_at(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, status=TaskStatus.DONE
        )
        task = await _read(task_repository, task_id)

        await task_repository.save(replace(task, status=TaskStatus.NOT_DONE))

        assert await stored_closed_at(async_connection, task_id) is None

    async def test_cancelling_a_done_task_is_a_fresh_close(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, status=TaskStatus.DONE
        )
        await backdate_closed_at(async_connection, task_id)
        task = await _read(task_repository, task_id)

        await task_repository.save(replace(task, status=TaskStatus.CANCELLED))

        restamped = await stored_closed_at(async_connection, task_id)
        assert restamped is not None
        assert restamped != FIXED_PAST_INSTANT

    @pytest.mark.parametrize(
        "edit",
        [
            pytest.param({"text": "packed the head torch"}, id="text"),
            pytest.param({"flagged": True}, id="flag"),
            pytest.param({"icon": TaskIcon.STAR}, id="icon"),
            pytest.param({"due_date": DUE_DATE}, id="due-date"),
        ],
    )
    async def test_editing_a_closed_task_keeps_its_close_time(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
        edit: dict[str, Any],
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, status=TaskStatus.DONE
        )
        await backdate_closed_at(async_connection, task_id)
        task = await _read(task_repository, task_id)

        await task_repository.save(replace(task, **edit))

        assert await stored_closed_at(async_connection, task_id) == FIXED_PAST_INSTANT

"""Integration tests for ``SqlTaskRepository`` and the recurrence columns of 0150.

Nothing in the application sets a recurrence yet, so this file holds the
repository to the promises later phases build on:

- **reads are lossless** — each mode, and each interval unit, reads back as its
  value object, through both the plain and the locking read;
- **``save`` drops nothing it writes** — an insert stores the setting and the
  task a copy came from, and an update changes or clears the setting and leaves
  it alone on any other edit;
- **the "recurrence of" link is written once** — an update never rewrites it,
  as the copy's past does not change;
- **owner scoping** holds for a recurring task as for any other.

The CHECKs themselves are proven in ``test_task_recurrence_constraints.py``.
"""

from dataclasses import replace

import pytest
import pytest_asyncio
from core_shared.models.tasks import (
    IntervalRecurrence,
    NoDateRecurrence,
    RecurrenceInterval,
    RecurrenceIntervalUnit,
    SeriesRecurrence,
    Task,
    TaskNotFoundError,
    TaskRecurrence,
    TaskStatus,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_journal,
    create_list_task,
    seed_series,
    seed_task_list_id,
)

pytestmark = pytest.mark.integration

_EVERY_TWO_WEEKS = IntervalRecurrence(
    interval=RecurrenceInterval(count=2, unit=RecurrenceIntervalUnit.WEEK)
)


@pytest_asyncio.fixture
async def task_repository(async_connection: AsyncConnection) -> SqlTaskRepository:
    return SqlTaskRepository(async_connection)


@pytest_asyncio.fixture
async def list_id(async_connection: AsyncConnection) -> int:
    return await seed_task_list_id(async_connection)


@pytest_asyncio.fixture
async def series_recurrence(async_connection: AsyncConnection) -> SeriesRecurrence:
    return SeriesRecurrence(series_id=await seed_series(async_connection))


async def _read(task_repository: SqlTaskRepository, task_id: int) -> Task:
    found = await task_repository.find_by_id(task_id, USER_ID)
    assert found is not None
    return found


async def _recurrences(series_recurrence: SeriesRecurrence) -> list[TaskRecurrence]:
    """Every mode, and every interval unit."""
    return [
        NoDateRecurrence(),
        *(
            IntervalRecurrence(interval=RecurrenceInterval(count=3, unit=unit))
            for unit in RecurrenceIntervalUnit
        ),
        series_recurrence,
    ]


class TestRecurrenceReads:
    """A seeded setting reads back as its value object."""

    async def test_every_mode_reads_back_through_both_reads(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
        series_recurrence: SeriesRecurrence,
    ) -> None:
        for recurrence in await _recurrences(series_recurrence):
            task_id = await create_list_task(
                async_connection, task_list_id=list_id, recurrence=recurrence
            )

            locked = await task_repository.find_by_id_for_update(task_id, USER_ID)

            assert (await _read(task_repository, task_id)).recurrence == recurrence
            assert locked is not None
            assert locked.recurrence == recurrence

    async def test_a_copy_reads_back_its_original(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        original_id = await create_list_task(async_connection, task_list_id=list_id)
        copy_id = await create_list_task(
            async_connection, task_list_id=list_id, recurrence_of_task_id=original_id
        )

        assert (
            await _read(task_repository, copy_id)
        ).recurrence_of_task_id == original_id


class TestRecurrenceInsert:
    """An insert stores the setting and the task a copy came from."""

    async def test_every_mode_is_stored_on_insert(
        self,
        task_repository: SqlTaskRepository,
        list_id: int,
        series_recurrence: SeriesRecurrence,
    ) -> None:
        for recurrence in await _recurrences(series_recurrence):
            saved = await task_repository.save(
                Task(
                    user_id=USER_ID,
                    text="water the plants",
                    task_list_id=list_id,
                    recurrence=recurrence,
                )
            )
            assert saved.id is not None

            assert (await _read(task_repository, saved.id)).recurrence == recurrence

    async def test_a_list_copy_stores_its_original(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        original_id = await create_list_task(
            async_connection, task_list_id=list_id, recurrence=_EVERY_TWO_WEEKS
        )

        saved = await task_repository.save(
            Task(
                user_id=USER_ID,
                text="water the plants",
                task_list_id=list_id,
                recurrence=_EVERY_TWO_WEEKS,
                recurrence_of_task_id=original_id,
            )
        )

        assert saved.recurrence_of_task_id == original_id

    async def test_a_journal_only_task_stores_its_original(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        list_id: int,
    ) -> None:
        """The link is a past, not a setting, so the journal insert keeps it too."""
        journal_id = await create_journal(journal_repository, days_offset=7)
        original_id = await create_list_task(async_connection, task_list_id=list_id)

        saved = await task_repository.save(
            Task(
                user_id=USER_ID,
                text="return the book",
                creating_journal_id=journal_id,
                due_journal_id=journal_id,
                recurrence_of_task_id=original_id,
            )
        )
        assert saved.id is not None

        assert (
            await _read(task_repository, saved.id)
        ).recurrence_of_task_id == original_id


class TestRecurrenceUpdate:
    """An update changes, clears or keeps the setting; never the link."""

    async def test_an_update_changes_the_mode(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
        series_recurrence: SeriesRecurrence,
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, recurrence=_EVERY_TWO_WEEKS
        )
        task = await _read(task_repository, task_id)

        await task_repository.save(replace(task, recurrence=series_recurrence))

        assert (await _read(task_repository, task_id)).recurrence == series_recurrence

    async def test_an_update_clears_the_setting(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
        series_recurrence: SeriesRecurrence,
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, recurrence=series_recurrence
        )
        task = await _read(task_repository, task_id)

        await task_repository.save(replace(task, recurrence=None))

        assert (await _read(task_repository, task_id)).recurrence is None

    async def test_a_status_edit_keeps_the_setting(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        """A completed task keeps its setting, which undoing a completion needs."""
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, recurrence=_EVERY_TWO_WEEKS
        )
        task = await _read(task_repository, task_id)

        await task_repository.save(replace(task, status=TaskStatus.DONE))

        assert (await _read(task_repository, task_id)).recurrence == _EVERY_TWO_WEEKS

    async def test_an_update_never_rewrites_the_original(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        original_id = await create_list_task(async_connection, task_list_id=list_id)
        other_id = await create_list_task(async_connection, task_list_id=list_id)
        copy_id = await create_list_task(
            async_connection, task_list_id=list_id, recurrence_of_task_id=original_id
        )
        copy = await _read(task_repository, copy_id)

        await task_repository.save(
            replace(copy, recurrence_of_task_id=other_id, text="renamed")
        )

        found = await _read(task_repository, copy_id)
        assert found.text == "renamed"
        assert found.recurrence_of_task_id == original_id


class TestRecurrenceOwnerScoping:
    """Another user cannot write a recurrence onto someone else's task."""

    async def test_another_users_update_writes_no_recurrence(
        self,
        async_connection: AsyncConnection,
        task_repository: SqlTaskRepository,
        list_id: int,
    ) -> None:
        task_id = await create_list_task(async_connection, task_list_id=list_id)
        task = await _read(task_repository, task_id)

        with pytest.raises(TaskNotFoundError):
            await task_repository.save(
                replace(task, user_id=OTHER_USER_ID, recurrence=_EVERY_TWO_WEEKS)
            )

        assert (await _read(task_repository, task_id)).recurrence is None

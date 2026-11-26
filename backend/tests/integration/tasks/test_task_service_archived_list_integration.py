"""Integration tests: an archived list freezes its tasks, against real PostgreSQL.

"Until unarchived the list and its tasks are read-only: every list and task
write is refused." The unit tests pin where each write consults the list; these
prove what the database is left holding:

- a refused write leaves the task's row and links as they were, and writes no
  outbox event — the delete included, which refuses *after* its statement and
  relies on the unit of work to put the row back;
- unarchiving restores every write, and a task on an active list is written as
  ever;
- the merges of journals and contacts still re-point an archived list's task
  links — they are the journal's and the contact's operations, which the
  specification says work "as today", not edits of the task;
- the share lock on the list does what the guard needs it to: an archive in
  flight makes a task write wait and then refuse, and a task write in flight
  makes an archive wait for it. Without the lock neither would wait, and the
  overlap helper would time out waiting for the block.

Every list task here is seeded as a row with ``create_list_task`` on a list
seeded with ``seed_task_list``. Creating a task on an archived list is refused
too; that is tested in ``test_task_service_create_on_list_integration.py``,
because the table below compares an existing task's state, which a create does
not have.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    TaskListArchivedError,
    TaskStatus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_contact_repository import (
    SqlTaskContactRepository,
)
from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_contact_merge_service import (
    TaskContactMergeService,
)
from app.core.tasks.services.task_list_service import TaskListService
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.concurrency_helpers import overlap
from tests.integration.tasks.task_seeding import (
    USER_ID,
    ArchivedListTask,
    create_journal,
    create_list_task,
    intermediate_journal_ids,
    linked_contact_ids,
    seed_archived_list_task,
    seed_task_list,
    service_on,
    stored_status,
    task_events,
    task_exists,
    task_state,
)
from tests.journal_service_factory import build_task_journal_merge_service

pytestmark = pytest.mark.integration

NEW_TEXT = "pack the spare head torch"

Seeded = ArchivedListTask


@pytest_asyncio.fixture
async def seeded(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    task_anchors: tuple[int, int],
) -> ArchivedListTask:
    return await seed_archived_list_task(
        async_connection, journal_repository, task_anchors
    )


Write = Callable[[TaskService, Seeded, AsyncConnection], Awaitable[object]]


async def _set_status(service: TaskService, s: Seeded, tx: AsyncConnection) -> object:
    return await service.set_status(
        user_id=USER_ID, task_id=s.task_id, status=TaskStatus.DONE, transaction=tx
    )


async def _update_text(service: TaskService, s: Seeded, tx: AsyncConnection) -> object:
    return await service.update_task(
        user_id=USER_ID, task_id=s.task_id, text=NEW_TEXT, transaction=tx
    )


async def _delete(service: TaskService, s: Seeded, tx: AsyncConnection) -> object:
    await service.delete_task(user_id=USER_ID, task_id=s.task_id, transaction=tx)
    return None


async def _retarget(service: TaskService, s: Seeded, tx: AsyncConnection) -> object:
    return await service.retarget_due_journal(
        user_id=USER_ID,
        task_id=s.task_id,
        due_journal_id=s.later_journal_id,
        transaction=tx,
    )


async def _move(service: TaskService, s: Seeded, tx: AsyncConnection) -> object:
    """Off the archived list onto an active one, so the task's own list refuses."""
    return await service.move_to_list(
        user_id=USER_ID,
        task_id=s.task_id,
        task_list_id=s.active_list_id,
        transaction=tx,
    )


async def _link(service: TaskService, s: Seeded, tx: AsyncConnection) -> object:
    return await service.link_contact(
        user_id=USER_ID,
        task_id=s.task_id,
        contact_id=s.unlinked_contact_id,
        transaction=tx,
    )


async def _unlink(service: TaskService, s: Seeded, tx: AsyncConnection) -> object:
    return await service.unlink_contact(
        user_id=USER_ID, task_id=s.task_id, contact_id=s.contact_id, transaction=tx
    )


async def _attach(service: TaskService, s: Seeded, tx: AsyncConnection) -> object:
    return await service.attach_intermediate_journal(
        user_id=USER_ID,
        task_id=s.task_id,
        journal_id=s.unlinked_journal_id,
        transaction=tx,
    )


async def _detach(service: TaskService, s: Seeded, tx: AsyncConnection) -> object:
    return await service.detach_intermediate_journal(
        user_id=USER_ID,
        task_id=s.task_id,
        journal_id=s.intermediate_journal_id,
        transaction=tx,
    )


WRITES: list[tuple[str, Write]] = [
    ("set_status", _set_status),
    ("update_text", _update_text),
    ("delete", _delete),
    ("retarget", _retarget),
    ("move_to_list", _move),
    ("link_contact", _link),
    ("unlink_contact", _unlink),
    ("attach_intermediate_journal", _attach),
    ("detach_intermediate_journal", _detach),
]
WRITE_IDS = [name for name, _ in WRITES]
WRITE_CALLS = [write for _, write in WRITES]


async def _snapshot(conn: AsyncConnection, s: Seeded) -> tuple[object, ...]:
    return await task_state(conn, s.task_id)


async def _unarchive(conn: AsyncConnection, s: Seeded) -> None:
    await TaskListService(
        task_list_repo=SqlTaskListRepository(conn),
        task_repo=SqlTaskRepository(conn),
        event_publisher=OutboxEventPublisher(conn),
    ).unarchive_task_list(
        user_id=USER_ID, task_list_id=s.task_list_id, transaction=conn
    )


class TestAnArchivedListFreezesItsTasks:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("write", WRITE_CALLS, ids=WRITE_IDS)
    async def test_the_write_is_refused_and_leaves_everything_as_it_was(
        self,
        write: Write,
        service: TaskService,
        seeded: Seeded,
        async_connection: AsyncConnection,
    ) -> None:
        before = await _snapshot(async_connection, seeded)

        with pytest.raises(TaskListArchivedError):
            await write(service, seeded, async_connection)

        assert await _snapshot(async_connection, seeded) == before
        assert await task_events(async_connection, task_id=seeded.task_id) == []

    @pytest.mark.asyncio
    async def test_a_refused_delete_is_rolled_back(
        self,
        service: TaskService,
        seeded: Seeded,
        async_connection: AsyncConnection,
    ) -> None:
        """The delete's statement runs before the refusal — it is its own read —
        so this is the case where the unit of work's rollback is the guard."""
        with pytest.raises(TaskListArchivedError):
            await _delete(service, seeded, async_connection)

        assert await task_exists(async_connection, seeded.task_id)
        assert await intermediate_journal_ids(async_connection, seeded.task_id) == [
            seeded.intermediate_journal_id
        ]
        assert await linked_contact_ids(async_connection, seeded.task_id) == [
            seeded.contact_id
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("write", WRITE_CALLS, ids=WRITE_IDS)
    async def test_unarchiving_restores_the_write(
        self,
        write: Write,
        service: TaskService,
        seeded: Seeded,
        async_connection: AsyncConnection,
    ) -> None:
        await _unarchive(async_connection, seeded)
        before = await _snapshot(async_connection, seeded)

        await write(service, seeded, async_connection)

        assert await _snapshot(async_connection, seeded) != before
        assert await task_events(async_connection, task_id=seeded.task_id) != []


class TestAnActiveListIsWrittenAsEver:
    @pytest.mark.asyncio
    async def test_a_status_change_on_an_active_list(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
    ) -> None:
        task_list = await seed_task_list(async_connection, "Groceries")
        assert task_list.id is not None
        task_id = await create_list_task(async_connection, task_list_id=task_list.id)

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        assert await stored_status(async_connection, task_id) == TaskStatus.DONE.value


class TestOtherDomainsStillMoveTheLinks:
    """A merge is the journal's or the contact's operation, which the
    specification keeps "as today"; refusing it would block a merge over a list
    the user is not touching."""

    @pytest.mark.asyncio
    async def test_a_journal_merge_repoints_an_archived_lists_task(
        self,
        seeded: Seeded,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ) -> None:
        survivor_id = await create_journal(journal_repository, title="Survivor")

        await build_task_journal_merge_service(async_connection).repoint_journal_links(
            source_journal_id=seeded.intermediate_journal_id,
            target_journal_id=survivor_id,
            transaction=async_connection,
        )

        assert await intermediate_journal_ids(async_connection, seeded.task_id) == [
            survivor_id
        ]

    @pytest.mark.asyncio
    async def test_a_contact_merge_repoints_an_archived_lists_task(
        self,
        seeded: Seeded,
        async_connection: AsyncConnection,
    ) -> None:
        await TaskContactMergeService(
            task_contact_repo=SqlTaskContactRepository(async_connection),
            event_publisher=OutboxEventPublisher(async_connection),
        ).repoint_contact_links(
            source_contact_id=seeded.contact_id,
            survivor_contact_id=seeded.unlinked_contact_id,
            transaction=async_connection,
            source=Provenance.UI,
        )

        assert await linked_contact_ids(async_connection, seeded.task_id) == [
            seeded.unlinked_contact_id
        ]


# ---------------------------------------------------------------------------
# Concurrency: two real connections, committed rows.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def committed_list_task(
    async_engine: AsyncEngine,
) -> AsyncIterator[tuple[str, int, int]]:
    """A list task on an active list, committed for real under a one-off owner.

    Two transactions can only overlap on rows both can see, which the savepoint
    fixture's rows are not. Everything is deleted again afterwards, events
    included: they are committed too, and nothing else would sweep them.

    Yields:
        ``(owner, task_list_id, task_id)``.
    """
    owner = f"archive-race-{uuid.uuid4()}"
    async with async_engine.begin() as setup:
        task_list = await seed_task_list(setup, "Packing", user_id=owner)
        assert task_list.id is not None
        task_id = await create_list_task(
            setup, task_list_id=task_list.id, user_id=owner
        )
    try:
        yield owner, task_list.id, task_id
    finally:
        async with async_engine.begin() as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM outbox_events WHERE "
                    "(event_type LIKE 'TaskList%' AND aggregate_id = :list_id) OR "
                    "(event_type NOT LIKE 'TaskList%' AND event_type LIKE 'Task%' "
                    "AND aggregate_id = :task_id)"
                ),
                {"list_id": task_list.id, "task_id": task_id},
            )
            await cleanup.execute(
                text("DELETE FROM tasks WHERE user_id = :user_id"), {"user_id": owner}
            )
            await cleanup.execute(
                text("DELETE FROM task_lists WHERE user_id = :user_id"),
                {"user_id": owner},
            )


def _archive(owner: str, task_list_id: int) -> Callable[[AsyncConnection], Any]:
    async def run(connection: AsyncConnection) -> None:
        await TaskListService(
            task_list_repo=SqlTaskListRepository(connection),
            task_repo=SqlTaskRepository(connection),
            event_publisher=OutboxEventPublisher(connection),
        ).archive_task_list(
            user_id=owner, task_list_id=task_list_id, transaction=connection
        )

    return run


def _complete(
    owner: str, task_id: int, outcome: list[BaseException]
) -> Callable[[AsyncConnection], Any]:
    """Mark the task done, recording a refusal rather than raising it.

    ``overlap`` runs the second writer inside its own task; capturing the error
    keeps the assertion about *which* error in the test body.
    """

    async def run(connection: AsyncConnection) -> None:
        service = service_on(connection, SqlUserSettingsRepository(connection))
        try:
            await service.set_status(
                user_id=owner,
                task_id=task_id,
                status=TaskStatus.DONE,
                transaction=connection,
            )
        except TaskListArchivedError as error:
            outcome.append(error)

    return run


async def _committed_status(async_engine: AsyncEngine, task_id: int) -> str:
    async with async_engine.connect() as check:
        return await stored_status(check, task_id)


class TestTheShareLockHoldsTheListAgainstAnArchive:
    @pytest.mark.asyncio
    async def test_a_task_write_during_an_archive_waits_and_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        """Without the lock the write reads the list before the archive
        commits, finds it active, and completes a task on an archived list."""
        async with committed_list_task(async_engine) as (owner, list_id, task_id):
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _archive(owner, list_id),
                _complete(owner, task_id, refused),
            )

            assert len(refused) == 1
            assert isinstance(refused[0], TaskListArchivedError)
            assert (
                await _committed_status(async_engine, task_id)
                == TaskStatus.NOT_DONE.value
            )

    @pytest.mark.asyncio
    async def test_an_archive_during_a_task_write_waits_for_it(
        self, async_engine: AsyncEngine
    ) -> None:
        """Without the lock the archive commits while the write is still open,
        and the write then commits onto a list that is already archived."""
        async with committed_list_task(async_engine) as (owner, list_id, task_id):
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _complete(owner, task_id, refused),
                _archive(owner, list_id),
            )

            assert refused == []
            assert (
                await _committed_status(async_engine, task_id) == TaskStatus.DONE.value
            )
            async with async_engine.connect() as check:
                archived_at = (
                    await check.execute(
                        text("SELECT archived_at FROM task_lists WHERE id = :id"),
                        {"id": list_id},
                    )
                ).scalar_one()
            assert archived_at is not None

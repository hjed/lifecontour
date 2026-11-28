"""Integration tests: taking a task off its list, against real PostgreSQL.

The specification's *Moving tasks*: "A task can be removed from its list only
if it has both a creating and a due journal. It becomes a journal-only task; if
its due journal is already past it is immediately lapsed." The unit tests pin
the lock order and the refusal order against mocks; these prove what the
database is left holding:

- the task leaves with its journals, status, flag, icon and contacts, and its
  position goes;
- a task whose due journal has passed reads as **lapsed** straight after, one
  due in the future does not, and nor does a done one;
- refused shapes (undated, due on a date, one journal) write nothing;
- one outbox event per removal, and none for a no-op or a refusal;
- another user's task is never written;
- over real connections the locks queue rather than deadlock: two removals from
  one list, a removal and an edit of its task, a removal racing a move of its
  task, a removal and a reorder of its list, a removal and an archive either
  way round, a removal and a delete of its list either way round (a removal
  that waited for the delete answers the no-op, the task kept journal-only), a
  removal and a delete of its journal, and a removal against a move and a
  journal delete that would close a cycle with a task-first order.
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
    Task,
    TaskIcon,
    TaskListArchivedError,
    TaskListChangedConcurrentlyError,
    TaskListRemovalNeedsJournalsError,
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
    seed_task_list,
    service_on,
    stored_anchors,
    stored_marks,
    stored_membership,
    stored_status,
    task_events,
)
from tests.journal_service_factory import build_journal_service
from tests.task_event_inventory import task_event_types, task_list_event_types
from tests.task_list_service_factory import build_task_list_service

pytestmark = pytest.mark.integration


async def _list_id(conn: AsyncConnection, name: str, **kwargs: Any) -> int:
    task_list = await seed_task_list(conn, name, **kwargs)
    assert task_list.id is not None
    return task_list.id


async def _remove(
    service: TaskService,
    conn: AsyncConnection,
    task_id: int,
    *,
    user_id: str = USER_ID,
) -> None:
    await service.remove_from_list(
        user_id=user_id,
        task_id=task_id,
        transaction=conn,
        source=Provenance.UI,
        changed_by="ui",
    )


async def _anchored_list_task(
    conn: AsyncConnection,
    journal_repository: SqlJournalRepository,
    *,
    due_offset: int,
    status: TaskStatus = TaskStatus.NOT_DONE,
) -> tuple[int, int, int, int]:
    """A task on a list holding both journals; ``(list, task, creating, due)``."""
    creating_id = await create_journal(
        journal_repository, title="Planning", days_offset=-10
    )
    due_id = await create_journal(
        journal_repository, title="Due", days_offset=due_offset
    )
    list_id = await _list_id(conn, "Packing")
    task_id = await create_list_task(
        conn,
        task_list_id=list_id,
        creating_journal_id=creating_id,
        due_journal_id=due_id,
        status=status,
        flagged=True,
        icon=TaskIcon.TENT,
    )
    return list_id, task_id, creating_id, due_id


class TestARemoval:
    @pytest.mark.asyncio
    async def test_it_leaves_its_list_and_keeps_everything_else(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id, task_id, creating_id, due_id = await _anchored_list_task(
            async_connection, journal_repository, due_offset=5
        )
        contact_id = await create_contact(async_connection)
        await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        await _remove(service, async_connection, task_id)

        assert await stored_membership(async_connection, task_id) == (None, None)
        assert await stored_anchors(async_connection, task_id) == (
            creating_id,
            due_id,
        )
        assert await stored_status(async_connection, task_id) == "not_done"
        assert await stored_marks(async_connection, task_id) == (True, "tent")
        assert await linked_contact_ids(async_connection, task_id) == [contact_id]
        on_list = await read_service.read_models_on_list(USER_ID, list_id)
        assert task_id not in [model.task.id for model in on_list.models]

    @pytest.mark.asyncio
    async def test_a_passed_due_journal_leaves_it_lapsed(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Overdue on its list; lapsed the moment it leaves."""
        _, task_id, _, _ = await _anchored_list_task(
            async_connection, journal_repository, due_offset=-3
        )
        before = await read_service.read_model(USER_ID, task_id)
        assert (before.lapsed, before.overdue) == (False, True)

        await _remove(service, async_connection, task_id)

        after = await read_service.read_model(USER_ID, task_id)
        assert after.lapsed is True
        assert str(after.lapse_reason) == "date_passed"
        assert after.overdue is False
        assert after.task_list is None

    @pytest.mark.asyncio
    async def test_a_future_due_journal_leaves_it_not_lapsed(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        _, task_id, _, _ = await _anchored_list_task(
            async_connection, journal_repository, due_offset=5
        )

        await _remove(service, async_connection, task_id)

        assert (await read_service.read_model(USER_ID, task_id)).lapsed is False

    @pytest.mark.asyncio
    async def test_a_done_task_past_its_journal_is_not_lapsed(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Nothing lapses a closed task."""
        _, task_id, _, _ = await _anchored_list_task(
            async_connection, journal_repository, due_offset=-3, status=TaskStatus.DONE
        )

        await _remove(service, async_connection, task_id)

        model = await read_service.read_model(USER_ID, task_id)
        assert model.lapsed is False
        assert model.task.status is TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_one_membership_event_is_published_to_none(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id, task_id, _, _ = await _anchored_list_task(
            async_connection, journal_repository, due_offset=5
        )

        await _remove(service, async_connection, task_id)

        [event] = await task_events(async_connection, task_id=task_id)
        assert event.event_type == "TaskListMembershipChanged"
        assert event.payload == {
            "task_id": task_id,
            "user_id": USER_ID,
            "changed_fields": {"task_list_id": [list_id, None]},
            "source": "ui",
            "changed_by": "ui",
        }


class TestNothingIsWritten:
    @pytest.mark.asyncio
    async def test_an_undated_task_is_refused(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        with pytest.raises(TaskListRemovalNeedsJournalsError):
            await _remove(service, async_connection, task_id)

        assert await stored_membership(async_connection, task_id) == (list_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []

    @pytest.mark.asyncio
    async def test_a_task_due_on_a_date_is_refused(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, _ = task_anchors
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            creating_journal_id=creating_id,
            due_date=datetime.date(2099, 1, 1),
        )

        with pytest.raises(TaskListRemovalNeedsJournalsError):
            await _remove(service, async_connection, task_id)

        assert await stored_membership(async_connection, task_id) == (list_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []

    @pytest.mark.asyncio
    async def test_a_task_with_only_a_due_journal_is_refused(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        _, due_id = task_anchors
        list_id = await _list_id(async_connection, "Groceries")
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=due_id
        )

        with pytest.raises(TaskListRemovalNeedsJournalsError):
            await _remove(service, async_connection, task_id)

        assert await stored_membership(async_connection, task_id) == (list_id, 0)

    @pytest.mark.asyncio
    async def test_a_journal_only_task_is_left_alone(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        await _remove(service, async_connection, task_id)

        assert await stored_membership(async_connection, task_id) == (None, None)
        assert await task_events(async_connection, task_id=task_id) == []

    @pytest.mark.asyncio
    async def test_an_archived_list_is_refused(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        list_id = await _list_id(async_connection, "Old", archived_at=ARCHIVED_AT)
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        with pytest.raises(TaskListArchivedError):
            await _remove(service, async_connection, task_id)

        assert await stored_membership(async_connection, task_id) == (list_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []

    @pytest.mark.asyncio
    async def test_another_users_task_reads_as_absent(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        creating_id = await create_journal(
            journal_repository, title="Theirs", days_offset=-2, user_id=OTHER_USER_ID
        )
        due_id = await create_journal(
            journal_repository, title="Theirs", days_offset=3, user_id=OTHER_USER_ID
        )
        list_id = await _list_id(async_connection, "Theirs", user_id=OTHER_USER_ID)
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskNotFoundError):
            await _remove(service, async_connection, task_id)

        assert await stored_membership(async_connection, task_id) == (list_id, 0)
        assert await task_events(async_connection, task_id=task_id) == []


# ---------------------------------------------------------------------------
# Concurrency: real connections, committed rows.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Committed:
    owner: str
    list_id: int
    other_list_id: int
    task_id: int
    other_task_id: int
    creating_id: int
    due_id: int


@asynccontextmanager
async def committed_rows(async_engine: AsyncEngine) -> AsyncIterator[Committed]:
    """Two lists; two tasks holding both journals on the first, committed.

    Two transactions only overlap on rows both can see, which the savepoint
    fixture's are not, so these are committed under a one-off owner and deleted
    again afterwards — their events included.
    """
    owner = f"remove-race-{uuid.uuid4()}"
    async with async_engine.begin() as setup:
        journals = SqlJournalRepository(setup)
        creating_id = await create_journal(
            journals, title="Planning", days_offset=-5, user_id=owner
        )
        due_id = await create_journal(
            journals, title="Due", days_offset=5, user_id=owner
        )
        list_id = await _list_id(setup, "Groceries", user_id=owner)
        other_list_id = await _list_id(setup, "Hardware", user_id=owner)
        task_id, other_task_id = [
            await create_list_task(
                setup,
                task_list_id=list_id,
                position=position,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                user_id=owner,
            )
            for position in (0, 1)
        ]
    try:
        yield Committed(
            owner, list_id, other_list_id, task_id, other_task_id, creating_id, due_id
        )
    finally:
        async with async_engine.begin() as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM outbox_events WHERE event_data::jsonb ->> 'user_id'"
                    " = :owner AND event_type = ANY(:types)"
                ),
                {
                    "owner": owner,
                    "types": sorted(task_event_types() | task_list_event_types()),
                },
            )
            await cleanup.execute(
                text(
                    "DELETE FROM outbox_events WHERE event_type LIKE 'Journal%'"
                    " AND aggregate_id = ANY(:ids)"
                ),
                {"ids": [creating_id, due_id]},
            )
            for table in ("tasks", "task_lists", "journals"):
                await cleanup.execute(
                    text(f"DELETE FROM {table} WHERE user_id = :owner"),  # noqa: S608
                    {"owner": owner},
                )


Step = Callable[[AsyncConnection], Any]


def _removing(
    owner: str,
    task_id: int,
    refused: list[BaseException],
    answered: list[Task] | None = None,
) -> Step:
    async def run(connection: AsyncConnection) -> None:
        service = service_on(connection, SqlUserSettingsRepository(connection))
        try:
            task = await service.remove_from_list(
                user_id=owner, task_id=task_id, transaction=connection
            )
            if answered is not None:
                answered.append(task)
        except (
            TaskListArchivedError,
            TaskListChangedConcurrentlyError,
            TaskListRemovalNeedsJournalsError,
        ) as error:
            refused.append(error)

    return run


def _moving(owner: str, task_id: int, task_list_id: int) -> Step:
    async def run(connection: AsyncConnection) -> None:
        await service_on(
            connection, SqlUserSettingsRepository(connection)
        ).move_to_list(
            user_id=owner,
            task_id=task_id,
            task_list_id=task_list_id,
            transaction=connection,
        )

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


def _reordering(owner: str, task_id: int, refused: list[BaseException]) -> Step:
    async def run(connection: AsyncConnection) -> None:
        try:
            await service_on(
                connection, SqlUserSettingsRepository(connection)
            ).reorder_task(
                user_id=owner,
                task_id=task_id,
                after_task_id=None,
                transaction=connection,
            )
        except TaskListChangedConcurrentlyError as error:
            refused.append(error)

    return run


def _archiving(owner: str, task_list_id: int) -> Step:
    async def run(connection: AsyncConnection) -> None:
        await _list_service(connection).archive_task_list(
            user_id=owner, task_list_id=task_list_id, transaction=connection
        )

    return run


def _deleting_list(owner: str, task_list_id: int) -> Step:
    async def run(connection: AsyncConnection) -> None:
        await _list_service(connection).delete_task_list(
            user_id=owner, task_list_id=task_list_id, transaction=connection
        )

    return run


def _list_service(connection: AsyncConnection) -> TaskListService:
    return build_task_list_service(connection)


def _deleting_journal(journal_id: int) -> Step:
    async def run(connection: AsyncConnection) -> None:
        await build_journal_service(connection).delete_journal(journal_id, connection)

    return run


async def _list_exists(async_engine: AsyncEngine, task_list_id: int) -> bool:
    async with async_engine.connect() as check:
        found = await check.execute(
            text("SELECT 1 FROM task_lists WHERE id = :id"), {"id": task_list_id}
        )
        return found.first() is not None


async def _event_types(async_engine: AsyncEngine, task_id: int) -> list[str]:
    async with async_engine.connect() as check:
        return [event.event_type for event in await task_events(check, task_id=task_id)]


async def _committed_membership(
    async_engine: AsyncEngine, task_id: int
) -> tuple[int | None, int | None]:
    async with async_engine.connect() as check:
        return await stored_membership(check, task_id)


@pytest.mark.slow
class TestTheLocksHold:
    @pytest.mark.asyncio
    async def test_two_removals_from_one_list_both_land(
        self, async_engine: AsyncEngine
    ) -> None:
        """Both units of work stay open together: each holds the list
        ``FOR SHARE`` and its own task, and neither waits for the other.

        The repository used to take the list ``FOR NO KEY UPDATE`` here — an
        upgrade of the share lock the service holds — so the second removal
        would wait on the first's exclusive lock (and two at once would
        deadlock). ``bounded`` fails the test if it waits at all.
        """
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []
            async with (
                async_engine.connect() as one,
                async_engine.connect() as two,
            ):
                async with unit_of_work(one), unit_of_work(two):
                    await _removing(c.owner, c.task_id, refused)(one)
                    await bounded(_removing(c.owner, c.other_task_id, refused)(two))

            assert refused == []
            assert await _committed_membership(async_engine, c.task_id) == (None, None)
            assert await _committed_membership(async_engine, c.other_task_id) == (
                None,
                None,
            )

    @pytest.mark.asyncio
    async def test_a_second_removal_of_the_same_task_waits_and_is_a_no_op(
        self, async_engine: AsyncEngine
    ) -> None:
        """A retried request racing the first answers as a later one would."""
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _removing(c.owner, c.task_id, refused),
                _removing(c.owner, c.task_id, refused),
            )

            assert refused == []
            assert await _committed_membership(async_engine, c.task_id) == (None, None)
            async with async_engine.connect() as check:
                events = await task_events(check, task_id=c.task_id)
            assert [event.event_type for event in events] == [
                "TaskListMembershipChanged"
            ]

    @pytest.mark.asyncio
    async def test_a_status_edit_during_a_removal_waits_and_both_land(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _removing(c.owner, c.task_id, refused),
                _completing(c.owner, c.task_id),
            )

            assert refused == []
            async with async_engine.connect() as check:
                assert await stored_status(check, c.task_id) == "done"
                assert await stored_membership(check, c.task_id) == (None, None)

    @pytest.mark.asyncio
    async def test_a_removal_during_a_status_edit_waits_and_both_land(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _completing(c.owner, c.task_id),
                _removing(c.owner, c.task_id, refused),
            )

            assert refused == []
            async with async_engine.connect() as check:
                assert await stored_status(check, c.task_id) == "done"
                assert await stored_membership(check, c.task_id) == (None, None)

    @pytest.mark.asyncio
    async def test_a_removal_during_a_move_of_its_task_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        """The removal chose the list the task was on; once the move commits it
        is on another, so the removal refuses (read again and retry)."""
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _moving(c.owner, c.task_id, c.other_list_id),
                _removing(c.owner, c.task_id, refused),
            )

            assert [type(error) for error in refused] == [
                TaskListChangedConcurrentlyError
            ]
            assert await _committed_membership(async_engine, c.task_id) == (
                c.other_list_id,
                0,
            )

    @pytest.mark.asyncio
    async def test_a_move_during_a_removal_waits_and_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        """The move takes the task's list only ``FOR SHARE``, so the two meet on
        the task row; the move chose its lists from where the task was, finds
        it journal-only once the removal commits, and refuses (read again and
        retry) rather than locking another list out of order."""
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []
            changed: list[BaseException] = []

            async def moving(connection: AsyncConnection) -> None:
                try:
                    await _moving(c.owner, c.task_id, c.other_list_id)(connection)
                except TaskListChangedConcurrentlyError as error:
                    changed.append(error)

            await overlap(async_engine, _removing(c.owner, c.task_id, refused), moving)

            assert refused == []
            assert len(changed) == 1
            assert await _committed_membership(async_engine, c.task_id) == (None, None)

    @pytest.mark.asyncio
    async def test_a_reorder_during_a_removal_waits_and_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        """Both share the list and meet on the task row; the task the reorder
        named has left the list by the time it gets it."""
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _removing(c.owner, c.task_id, []),
                _reordering(c.owner, c.task_id, refused),
            )

            assert len(refused) == 1
            assert await _committed_membership(async_engine, c.task_id) == (None, None)

    @pytest.mark.asyncio
    async def test_a_removal_during_a_reorder_waits_and_lands(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _reordering(c.owner, c.other_task_id, []),
                _removing(c.owner, c.task_id, refused),
            )

            assert refused == []
            assert await _committed_membership(async_engine, c.task_id) == (None, None)
            assert await _committed_membership(async_engine, c.other_task_id) == (
                c.list_id,
                0,
            )

    @pytest.mark.asyncio
    async def test_a_removal_during_an_archive_waits_and_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _archiving(c.owner, c.list_id),
                _removing(c.owner, c.task_id, refused),
            )

            assert [type(error) for error in refused] == [TaskListArchivedError]
            assert await _committed_membership(async_engine, c.task_id) == (
                c.list_id,
                0,
            )

    @pytest.mark.asyncio
    async def test_an_archive_during_a_removal_waits_for_it(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _removing(c.owner, c.task_id, refused),
                _archiving(c.owner, c.list_id),
            )

            assert refused == []
            assert await _committed_membership(async_engine, c.task_id) == (None, None)

    @pytest.mark.asyncio
    async def test_a_removal_during_a_delete_of_its_list_answers_the_no_op(
        self, async_engine: AsyncEngine
    ) -> None:
        """The removal read the task on its list, then waited for the list's
        share lock behind the delete. The delete keeps a task holding both
        journals as a journal-only task, so the removal finds the list gone and
        the task already off every list: the same no-op a later removal answers,
        not a 404 for a task that still exists."""
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []
            answered: list[Task] = []

            await overlap(
                async_engine,
                _deleting_list(c.owner, c.list_id),
                _removing(c.owner, c.task_id, refused, answered),
            )

            assert refused == []
            assert [(task.id, task.task_list_id) for task in answered] == [
                (c.task_id, None)
            ]
            assert await _committed_membership(async_engine, c.task_id) == (None, None)
            # The delete's own event for the task it kept; the removal adds none.
            assert await _event_types(async_engine, c.task_id) == [
                "TaskListMembershipChanged"
            ]

    @pytest.mark.asyncio
    async def test_a_list_delete_during_a_removal_waits_for_it(
        self, async_engine: AsyncEngine
    ) -> None:
        """The delete locks the list's tasks after its share lock; the removal
        holds one of them, so the delete waits, then skips the task the removal
        took off and keeps the other as journal-only."""
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _removing(c.owner, c.task_id, refused),
                _deleting_list(c.owner, c.list_id),
            )

            assert refused == []
            assert await _committed_membership(async_engine, c.task_id) == (None, None)
            assert await _committed_membership(async_engine, c.other_task_id) == (
                None,
                None,
            )
            assert await _list_exists(async_engine, c.list_id) is False

    @pytest.mark.asyncio
    async def test_a_removal_during_a_delete_of_its_due_journal_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        """The delete detaches the due journal under the task's row lock; the
        removal waits for it and judges the row it left — undated."""
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _deleting_journal(c.due_id),
                _removing(c.owner, c.task_id, refused),
            )

            assert [type(error) for error in refused] == [
                TaskListRemovalNeedsJournalsError
            ]
            assert await _committed_membership(async_engine, c.task_id) == (
                c.list_id,
                0,
            )

    @pytest.mark.asyncio
    async def test_a_delete_of_its_due_journal_during_a_removal_waits_for_it(
        self, async_engine: AsyncEngine
    ) -> None:
        """Once removed the task is journal-only, and a journal-only task due
        in a journal blocks that journal's deletion."""
        async with committed_rows(async_engine) as c:
            refused: list[BaseException] = []
            outcome: list[BaseException] = []

            async def deleting(connection: AsyncConnection) -> None:
                try:
                    await _deleting_journal(c.due_id)(connection)
                except Exception as error:  # noqa: BLE001 - the outcome is asserted
                    outcome.append(error)

            # Only the one task leaves, so the other keeps the journal deletable
            # as a list task's link; the removed one now blocks it.
            await overlap(
                async_engine,
                _removing(c.owner, c.task_id, refused),
                deleting,
            )

            assert refused == []
            assert [type(error).__name__ for error in outcome] == [
                "JournalHasAnchoredTasksError"
            ]
            async with async_engine.connect() as check:
                assert await stored_anchors(check, c.task_id) == (
                    c.creating_id,
                    c.due_id,
                )


class _GatedLists(SqlTaskListRepository):
    """A list repository that pauses at its first list lock until let go.

    The pause is where a removal has read its task and is about to lock its
    list. Under a task-first order it would already hold the task there, which
    is the state the cycle below needs.
    """

    reached: asyncio.Event
    release: asyncio.Event

    async def find_by_id_for_share(self, task_list_id: int, user_id: str) -> Any:
        if not self.reached.is_set():
            self.reached.set()
            await self.release.wait()
        return await super().find_by_id_for_share(task_list_id, user_id)


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


class TestARemovalAMoveAndAJournalDelete:
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_they_queue_rather_than_deadlock(
        self, async_engine: AsyncEngine
    ) -> None:
        """Task A (lower id, on another list) and task T (on list L) share a
        creating journal D, which is deleted; A moves onto L; T is removed.

        Under a task-first removal: the removal holds T; the delete holds D and
        A (tasks in id order) and waits for T; the move holds L exclusively and
        waits for A; then the removal asks for L ``FOR SHARE`` and the cycle
        closes. List first, the removal holds nothing while it waits, so all
        three finish — the removal refused, because the delete took its
        creating journal.
        """
        async with committed_rows(async_engine) as c:
            async with async_engine.begin() as setup:
                doomed_id = await create_journal(
                    SqlJournalRepository(setup),
                    title="Doomed",
                    days_offset=-2,
                    user_id=c.owner,
                )
                # Created first so its id is the lower of the two the delete locks.
                moving_id = await create_list_task(
                    setup,
                    task_list_id=c.other_list_id,
                    creating_journal_id=doomed_id,
                    due_journal_id=c.due_id,
                    user_id=c.owner,
                )
                removing_id = await create_list_task(
                    setup,
                    task_list_id=c.list_id,
                    position=2,
                    creating_journal_id=doomed_id,
                    due_journal_id=c.due_id,
                    user_id=c.owner,
                )
            assert moving_id < removing_id

            class Gated(_GatedLists):
                reached = asyncio.Event()
                release = asyncio.Event()

            refused: list[BaseException] = []

            async def removing(connection: AsyncConnection) -> None:
                async with unit_of_work(connection):
                    try:
                        await service_on(
                            connection,
                            SqlUserSettingsRepository(connection),
                            task_list_repo=Gated,
                        ).remove_from_list(
                            user_id=c.owner,
                            task_id=removing_id,
                            transaction=connection,
                        )
                    except TaskListRemovalNeedsJournalsError as error:
                        refused.append(error)

            async def deleting(connection: AsyncConnection) -> None:
                async with unit_of_work(connection):
                    await _deleting_journal(doomed_id)(connection)

            async def moving(connection: AsyncConnection) -> None:
                async with unit_of_work(connection):
                    await _moving(c.owner, moving_id, c.list_id)(connection)

            try:
                async with (
                    async_engine.connect() as one,
                    async_engine.connect() as two,
                    async_engine.connect() as three,
                ):
                    pids = [await backend_pid(each) for each in (one, two, three)]
                    started: list[asyncio.Task[None]] = []
                    try:
                        started.append(asyncio.create_task(removing(one)))
                        await bounded(Gated.reached.wait())
                        started.append(asyncio.create_task(deleting(two)))
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
                assert [type(error) for error in refused] == [
                    TaskListRemovalNeedsJournalsError
                ]
                assert await _committed_membership(async_engine, removing_id) == (
                    c.list_id,
                    2,
                )
                (moved_to, _) = await _committed_membership(async_engine, moving_id)
                assert moved_to == c.list_id
            finally:
                async with async_engine.begin() as cleanup:
                    await cleanup.execute(
                        text(
                            "DELETE FROM outbox_events WHERE event_type LIKE"
                            " 'Journal%' AND aggregate_id = :id"
                        ),
                        {"id": doomed_id},
                    )

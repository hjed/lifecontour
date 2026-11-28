"""Integration tests for ``TaskService.create_list_task`` against real PostgreSQL.

The unit tests own the rules and their order. What only a real database shows:

- the row lands on the list at the bottom, with its due date, its contacts and
  no journal, and one ``TaskCreated`` carrying the list and the date is in the
  outbox **in the same transaction**;
- a refusal — an archived list, another user's list — leaves no row and no event;
- the due date is judged on the timezone stored in ``user_settings``;
- the list's update lock holds an archive off: a create that starts while an
  archive is in flight waits for it and is then refused;
- the new task reads back through the read service, and a journal it is later
  linked to lists it under *mentioned*;
- a task created due in a journal is stored with that journal and no other
  date, reads back due there and not overdue, lights the journal's tasks-due
  badge, stays out of the upcoming window (journal-only for now), and is
  refused for another user's journal or one that is not in the future;
- a journal delete racing the create is safe in both orders: the create waits
  on the delete and is told the journal is gone, or the delete waits on the
  create and detaches the new task, which becomes undated.

The archived refusal lives here rather than in the archived-list suite: that
suite compares an *existing* task's state before and after each write, which a
create does not have.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from core_shared.models.tasks import (
    TaskAnchorJournalNotFoundError,
    TaskDomainError,
    TaskDueDateInPastError,
    TaskDueJournalNotFutureError,
    TaskListArchivedError,
    TaskListNotFoundError,
    TaskStatus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from tests.integration.concurrency_helpers import overlap
from tests.integration.tasks.task_seeding import (
    COUNT_TASKS,
    OTHER_USER_ID,
    USER_ID,
    committed_task_list,
    count,
    create_contact,
    create_journal,
    create_list_task,
    intermediate_journal_ids,
    link_intermediate_journal,
    linked_contact_ids,
    seed_task_list_id,
    service_on,
    task_events,
)
from tests.journal_service_factory import build_journal_service
from tests.task_list_service_factory import build_task_list_service

pytestmark = pytest.mark.integration

# 06:00 on 6 August in Sydney (+10); the 5th is still running in UTC.
SYDNEY_MORNING = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
UTC_TODAY = date(2026, 8, 5)
SYDNEY_TODAY = date(2026, 8, 6)

# 19:00 in Sydney on the 6th: tomorrow in UTC, but already today in Sydney.
STARTS_SYDNEY_TODAY = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
# The 8th everywhere: in the future in every zone at ``SYDNEY_MORNING``.
STARTS_IN_TWO_DAYS = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)


async def _stored(conn: AsyncConnection, task_id: int) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT task_list_id, position, due_date, creating_journal_id, "
                "due_journal_id, status FROM tasks WHERE id = :id"
            ),
            {"id": task_id},
        )
    ).one()


class TestCreatingOnAList:
    async def test_the_task_lands_at_the_bottom_with_its_date_and_contacts(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        await create_list_task(async_connection, task_list_id=list_id, position=0)
        await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=1,
            status=TaskStatus.DONE,
        )
        contact_id = await create_contact(async_connection)

        created = await service.create_list_task(
            user_id=USER_ID,
            task_list_id=list_id,
            text="pack the tent",
            due_date=SYDNEY_TODAY,
            contact_ids=[contact_id],
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )

        assert created.id is not None
        row = await _stored(async_connection, created.id)
        assert (row.task_list_id, row.position, row.due_date) == (
            list_id,
            2,
            SYDNEY_TODAY,
        )
        assert (row.creating_journal_id, row.due_journal_id) == (None, None)
        assert row.status == TaskStatus.NOT_DONE.value
        assert await linked_contact_ids(async_connection, created.id) == [contact_id]

    async def test_one_created_event_carries_the_list_and_the_date(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        created = await service.create_list_task(
            user_id=USER_ID,
            task_list_id=list_id,
            text="pack the tent",
            due_date=SYDNEY_TODAY,
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )

        assert created.id is not None
        [event] = await task_events(async_connection, task_id=created.id)
        assert event.event_type == "TaskCreated"
        assert event.payload["task_list_id"] == list_id
        assert event.payload["due_date"] == "2026-08-06"
        assert event.payload["creating_journal_id"] is None
        assert event.payload["due_journal_id"] is None

    async def test_reads_back_on_its_list_and_not_overdue(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        created = await service.create_list_task(
            user_id=USER_ID,
            task_list_id=list_id,
            text="pack the tent",
            due_date=SYDNEY_TODAY,
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )
        assert created.id is not None

        model = await read_service.read_model(USER_ID, created.id, now=SYDNEY_MORNING)

        assert model.task_list is not None
        assert model.task_list.id == list_id
        assert model.creating_journal is None
        assert model.due_journal is None
        assert model.overdue is False
        assert model.lapse_reason is None

    async def test_a_journal_it_is_later_linked_to_lists_it_as_mentioned(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A task with no anchor reaches a journal page only as a mention."""
        list_id = await seed_task_list_id(async_connection)
        journal_id = await create_journal(journal_repository, title="Tuesday")
        created = await service.create_list_task(
            user_id=USER_ID,
            task_list_id=list_id,
            text="pack the tent",
            transaction=async_connection,
        )
        assert created.id is not None
        await link_intermediate_journal(
            async_connection, task_id=created.id, journal_id=journal_id
        )

        groups = await read_service.read_models_for_journal(USER_ID, journal_id)

        assert [model.task.id for model in groups.mentioned] == [created.id]
        assert groups.due == ()
        assert groups.created == ()


class TestRefusals:
    async def test_an_archived_list_is_refused_and_nothing_is_written(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection, archived=True)

        with pytest.raises(TaskListArchivedError):
            await service.create_list_task(
                user_id=USER_ID,
                task_list_id=list_id,
                text="pack the tent",
                transaction=async_connection,
            )

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await task_events(async_connection) == []

    async def test_another_users_list_is_not_found_and_nothing_is_written(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        foreign_list_id = await seed_task_list_id(
            async_connection, user_id=OTHER_USER_ID
        )

        with pytest.raises(TaskListNotFoundError):
            await service.create_list_task(
                user_id=USER_ID,
                task_list_id=foreign_list_id,
                text="pack the tent",
                transaction=async_connection,
            )

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await task_events(async_connection) == []


class TestTheDueDateIsJudgedInTheUsersTimezone:
    async def test_utc_today_is_already_yesterday_in_sydney(
        self,
        service: TaskService,
        user_settings_repository: SqlUserSettingsRepository,
        async_connection: AsyncConnection,
    ) -> None:
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        list_id = await seed_task_list_id(async_connection)

        with pytest.raises(TaskDueDateInPastError) as raised:
            await service.create_list_task(
                user_id=USER_ID,
                task_list_id=list_id,
                text="pack the tent",
                due_date=UTC_TODAY,
                transaction=async_connection,
                now=SYDNEY_MORNING,
            )

        assert raised.value.today == SYDNEY_TODAY
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_without_a_stored_timezone_utc_today_is_accepted(
        self, service: TaskService, async_connection: AsyncConnection
    ) -> None:
        user_id = f"no-settings-{uuid.uuid4()}"
        list_id = await seed_task_list_id(async_connection, user_id=user_id)

        created = await service.create_list_task(
            user_id=user_id,
            task_list_id=list_id,
            text="pack the tent",
            due_date=UTC_TODAY,
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )

        assert created.due_date == UTC_TODAY


class TestCreatingDueInAJournal:
    async def test_stored_with_the_journal_and_no_other_date(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        await create_list_task(async_connection, task_list_id=list_id, position=0)
        journal_id = await create_journal(
            journal_repository, title="Beach weekend", start=STARTS_IN_TWO_DAYS
        )

        created = await service.create_list_task(
            user_id=USER_ID,
            task_list_id=list_id,
            text="pack the tent",
            due_journal_id=journal_id,
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )

        assert created.id is not None
        row = await _stored(async_connection, created.id)
        assert (row.task_list_id, row.position) == (list_id, 1)
        assert (row.due_journal_id, row.creating_journal_id, row.due_date) == (
            journal_id,
            None,
            None,
        )
        [event] = await task_events(async_connection, task_id=created.id)
        assert event.event_type == "TaskCreated"
        assert event.payload["task_list_id"] == list_id
        assert event.payload["due_journal_id"] == journal_id
        assert event.payload["creating_journal_id"] is None
        assert event.payload["due_date"] is None

    async def test_reads_back_due_there_on_its_list_and_neither_lapsed_nor_overdue(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        journal_id = await create_journal(
            journal_repository, title="Beach weekend", start=STARTS_IN_TWO_DAYS
        )
        created = await service.create_list_task(
            user_id=USER_ID,
            task_list_id=list_id,
            text="pack the tent",
            due_journal_id=journal_id,
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )
        assert created.id is not None

        model = await read_service.read_model(USER_ID, created.id, now=SYDNEY_MORNING)
        groups = await read_service.read_models_for_journal(
            USER_ID, journal_id, now=SYDNEY_MORNING
        )

        assert model.task_list is not None
        assert model.task_list.id == list_id
        assert model.due_journal is not None
        assert model.due_journal.id == journal_id
        assert model.creating_journal is None
        assert model.lapse_reason is None
        assert model.overdue is False
        assert [m.task.id for m in groups.due] == [created.id]
        assert groups.created == ()
        assert groups.mentioned == ()

    async def test_lights_the_journals_tasks_due_badge(
        self,
        service: TaskService,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        journal_id = await create_journal(
            journal_repository, title="Beach weekend", start=STARTS_IN_TWO_DAYS
        )
        await service.create_list_task(
            user_id=USER_ID,
            task_list_id=list_id,
            text="pack the tent",
            due_journal_id=journal_id,
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )
        journal = await journal_repository.find_by_id(journal_id)
        assert journal is not None

        counts = await read_service.due_task_counts(
            USER_ID, [journal], now=SYDNEY_MORNING
        )

        assert counts == {journal_id: 1}

    async def test_stays_out_of_the_upcoming_window(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Upcoming is journal-only until ITER21-004 teaches it list tasks."""
        list_id = await seed_task_list_id(async_connection)
        journal_id = await create_journal(
            journal_repository, title="Beach weekend", start=STARTS_IN_TWO_DAYS
        )
        await service.create_list_task(
            user_id=USER_ID,
            task_list_id=list_id,
            text="pack the tent",
            due_journal_id=journal_id,
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )

        upcoming = await task_repository.find_upcoming_tasks(
            USER_ID,
            window_start=SYDNEY_MORNING - timedelta(days=1),
            window_end=SYDNEY_MORNING + timedelta(days=30),
        )

        assert upcoming == []

    async def test_another_users_journal_is_not_found_and_nothing_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        foreign_journal_id = await create_journal(
            journal_repository,
            title="Not yours",
            start=STARTS_IN_TWO_DAYS,
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as raised:
            await service.create_list_task(
                user_id=USER_ID,
                task_list_id=list_id,
                text="pack the tent",
                due_journal_id=foreign_journal_id,
                transaction=async_connection,
                now=SYDNEY_MORNING,
            )

        assert raised.value.anchor == "due"
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await task_events(async_connection) == []

    async def test_a_journal_today_in_sydney_is_not_the_future(
        self,
        service: TaskService,
        user_settings_repository: SqlUserSettingsRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        list_id = await seed_task_list_id(async_connection)
        journal_id = await create_journal(
            journal_repository, title="Tonight", start=STARTS_SYDNEY_TODAY
        )

        with pytest.raises(TaskDueJournalNotFutureError) as raised:
            await service.create_list_task(
                user_id=USER_ID,
                task_list_id=list_id,
                text="pack the tent",
                due_journal_id=journal_id,
                transaction=async_connection,
                now=SYDNEY_MORNING,
            )

        assert (raised.value.journal_date, raised.value.today) == (
            SYDNEY_TODAY,
            SYDNEY_TODAY,
        )
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await task_events(async_connection) == []

    async def test_without_a_stored_timezone_the_same_journal_is_the_future(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        user_id = f"no-settings-{uuid.uuid4()}"
        list_id = await seed_task_list_id(async_connection, user_id=user_id)
        journal_id = await create_journal(
            journal_repository,
            title="Tonight",
            start=STARTS_SYDNEY_TODAY,
            user_id=user_id,
        )

        created = await service.create_list_task(
            user_id=user_id,
            task_list_id=list_id,
            text="pack the tent",
            due_journal_id=journal_id,
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )

        assert created.due_journal_id == journal_id


# ---------------------------------------------------------------------------
# Concurrency: two real connections, committed rows.
# ---------------------------------------------------------------------------


def _archive(owner: str, task_list_id: int) -> Callable[[AsyncConnection], Any]:
    async def run(connection: AsyncConnection) -> None:
        await build_task_list_service(connection).archive_task_list(
            user_id=owner, task_list_id=task_list_id, transaction=connection
        )

    return run


def _create(
    owner: str, task_list_id: int, outcome: list[BaseException]
) -> Callable[[AsyncConnection], Any]:
    """Create a task on the list, recording a refusal rather than raising it."""

    async def run(connection: AsyncConnection) -> None:
        service = service_on(connection, SqlUserSettingsRepository(connection))
        try:
            await service.create_list_task(
                user_id=owner,
                task_list_id=task_list_id,
                text="pack the tent",
                transaction=connection,
            )
        except TaskListArchivedError as error:
            outcome.append(error)

    return run


class TestTheListLockHoldsAnArchiveOff:
    @pytest.mark.asyncio
    async def test_a_create_during_an_archive_waits_and_is_refused(
        self, async_engine: AsyncEngine
    ) -> None:
        """Without the lock the create reads the list as active before the
        archive commits, and puts a task on a list that is already archived."""
        async with committed_task_list(async_engine) as (owner, list_id):
            refused: list[BaseException] = []

            await overlap(
                async_engine, _archive(owner, list_id), _create(owner, list_id, refused)
            )

            assert len(refused) == 1
            assert isinstance(refused[0], TaskListArchivedError)
            async with async_engine.connect() as check:
                assert await count(check, COUNT_TASKS, {"user_id": owner}) == 0

    @pytest.mark.asyncio
    async def test_an_archive_during_a_create_waits_for_it(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_task_list(async_engine) as (owner, list_id):
            refused: list[BaseException] = []

            await overlap(
                async_engine, _create(owner, list_id, refused), _archive(owner, list_id)
            )

            assert refused == []
            async with async_engine.connect() as check:
                assert await count(check, COUNT_TASKS, {"user_id": owner}) == 1


# ---------------------------------------------------------------------------
# A journal delete racing a create due in that journal.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _committed_list_and_journal(
    async_engine: AsyncEngine,
) -> AsyncIterator[tuple[str, int, int]]:
    """A committed list and a future journal under a one-off owner, deleted after."""
    async with committed_task_list(async_engine) as (owner, list_id):
        async with async_engine.begin() as setup:
            journal_id = await create_journal(
                SqlJournalRepository(setup),
                title="Beach weekend",
                days_offset=3,
                user_id=owner,
            )
        try:
            yield owner, list_id, journal_id
        finally:
            async with async_engine.begin() as cleanup:
                await cleanup.execute(
                    text("DELETE FROM tasks WHERE user_id = :owner"), {"owner": owner}
                )
                await cleanup.execute(
                    text("DELETE FROM journals WHERE user_id = :owner"),
                    {"owner": owner},
                )


def _delete_journal(journal_id: int) -> Callable[[AsyncConnection], Any]:
    async def run(connection: AsyncConnection) -> None:
        await build_journal_service(connection).delete_journal(journal_id, connection)

    return run


def _create_due_in(
    owner: str, task_list_id: int, journal_id: int, outcome: list[BaseException]
) -> Callable[[AsyncConnection], Any]:
    """Create a task due in the journal, recording a refusal rather than raising it."""

    async def run(connection: AsyncConnection) -> None:
        service = service_on(connection, SqlUserSettingsRepository(connection))
        try:
            await service.create_list_task(
                user_id=owner,
                task_list_id=task_list_id,
                text="pack the tent",
                due_journal_id=journal_id,
                transaction=connection,
            )
        except TaskAnchorJournalNotFoundError as error:
            outcome.append(error)

    return run


@pytest.mark.slow
class TestAJournalDeleteRacingTheCreate:
    @pytest.mark.asyncio
    async def test_a_create_during_the_delete_waits_and_is_told_the_journal_is_gone(
        self, async_engine: AsyncEngine
    ) -> None:
        async with _committed_list_and_journal(async_engine) as (
            owner,
            list_id,
            journal_id,
        ):
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _delete_journal(journal_id),
                _create_due_in(owner, list_id, journal_id, refused),
            )

            assert len(refused) == 1
            assert isinstance(refused[0], TaskAnchorJournalNotFoundError)
            assert refused[0].anchor == "due"
            async with async_engine.connect() as check:
                assert await count(check, COUNT_TASKS, {"user_id": owner}) == 0

    @pytest.mark.asyncio
    async def test_a_delete_during_the_create_waits_and_leaves_the_task_undated(
        self, async_engine: AsyncEngine
    ) -> None:
        async with _committed_list_and_journal(async_engine) as (
            owner,
            list_id,
            journal_id,
        ):
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _create_due_in(owner, list_id, journal_id, refused),
                _delete_journal(journal_id),
            )

            assert refused == []
            async with async_engine.connect() as check:
                row = (
                    await check.execute(
                        text(
                            "SELECT id, task_list_id, due_journal_id FROM tasks "
                            "WHERE user_id = :owner"
                        ),
                        {"owner": owner},
                    )
                ).one()
                assert (row.task_list_id, row.due_journal_id) == (list_id, None)
                removed = await task_events(check, task_id=row.id)
                assert [event.event_type for event in removed] == [
                    "TaskCreated",
                    "TaskJournalLinksRemoved",
                ]


# ---------------------------------------------------------------------------
# A journal delete racing a retarget of the list task due in it.
# ---------------------------------------------------------------------------


def _retarget_onto(
    owner: str, task_id: int, journal_id: int, outcome: list[BaseException]
) -> Callable[[AsyncConnection], Any]:
    """Retarget the task, recording any domain refusal rather than raising it."""

    async def run(connection: AsyncConnection) -> None:
        service = service_on(connection, SqlUserSettingsRepository(connection))
        try:
            await service.retarget_due_journal(
                user_id=owner,
                task_id=task_id,
                due_journal_id=journal_id,
                transaction=connection,
            )
        except TaskDomainError as error:
            outcome.append(error)

    return run


@pytest.mark.slow
class TestAJournalDeleteRacingARetarget:
    @pytest.mark.asyncio
    async def test_a_retarget_during_the_delete_waits_and_lands_on_the_new_journal(
        self, async_engine: AsyncEngine
    ) -> None:
        """The delete detaches the task while the retarget waits on its journal.

        The retarget peeked the journal before the delete committed, so it
        reads the task again under its lock and finds it undated. A list task
        can be given a due journal, so it simply gains the new one — with
        nothing left to retain, since the journal it was leaving is gone.
        """
        async with _committed_list_and_journal(async_engine) as (
            owner,
            list_id,
            journal_id,
        ):
            async with async_engine.begin() as setup:
                later_id = await create_journal(
                    SqlJournalRepository(setup),
                    title="Later trip",
                    days_offset=9,
                    user_id=owner,
                )
                task_id = await create_list_task(
                    setup,
                    task_list_id=list_id,
                    due_journal_id=journal_id,
                    user_id=owner,
                )
            refused: list[BaseException] = []

            await overlap(
                async_engine,
                _delete_journal(journal_id),
                _retarget_onto(owner, task_id, later_id, refused),
            )

            assert refused == []
            async with async_engine.connect() as check:
                row = (
                    await check.execute(
                        text("SELECT due_journal_id FROM tasks WHERE id = :id"),
                        {"id": task_id},
                    )
                ).one()
                assert row.due_journal_id == later_id
                assert await intermediate_journal_ids(check, task_id) == []
                events = await task_events(check, task_id=task_id)
                assert [event.event_type for event in events] == [
                    "TaskJournalLinksRemoved",
                    "TaskUpdated",
                ]
                assert events[1].payload["changed_fields"] == {
                    "due_journal_id": [None, later_id]
                }

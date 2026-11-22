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
  linked to lists it under *mentioned*.

The archived refusal lives here rather than in the archived-list suite: that
suite compares an *existing* task's state before and after each write, which a
create does not have.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from core_shared.models.tasks import (
    TaskDueDateInPastError,
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
from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.services.task_list_service import TaskListService
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
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
    link_intermediate_journal,
    linked_contact_ids,
    seed_task_list_id,
    service_on,
    task_events,
)

pytestmark = pytest.mark.integration

# 06:00 on 6 August in Sydney (+10); the 5th is still running in UTC.
SYDNEY_MORNING = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
UTC_TODAY = date(2026, 8, 5)
SYDNEY_TODAY = date(2026, 8, 6)


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


# ---------------------------------------------------------------------------
# Concurrency: two real connections, committed rows.
# ---------------------------------------------------------------------------


def _archive(owner: str, task_list_id: int) -> Callable[[AsyncConnection], Any]:
    async def run(connection: AsyncConnection) -> None:
        await TaskListService(
            task_list_repo=SqlTaskListRepository(connection),
            event_publisher=OutboxEventPublisher(connection),
        ).archive_task_list(
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

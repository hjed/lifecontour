"""Integration tests for creating and reading task lists, against real PostgreSQL.

``TaskListService`` owns the one write this phase adds — create — and holds it to
two promises: the list and its ``TaskListCreated`` event are written together,
and a refused create writes neither. ``TaskListReadService`` owns the reads and
holds them to owner scoping: another user's list is reported exactly as a
missing one, and never listed.

Owner scoping is asserted against a second owner's real rows, for the reason the
repository tests give: an absent id cannot catch a missing ``user_id`` filter.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    TaskIcon,
    TaskListArchiveFilter,
    TaskListNotFoundError,
    TaskListValidationError,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.services.task_list_read_service import TaskListReadService
from app.core.tasks.services.task_list_service import TaskListService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    count,
    make_task_container,
    seed_task_list,
    task_list_events,
)

pytestmark = pytest.mark.integration

ARCHIVED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
_COUNT_LISTS = "SELECT COUNT(*) FROM task_lists WHERE user_id = :user_id"


def make_service(conn: AsyncConnection) -> TaskListService:
    return TaskListService(
        task_list_repo=SqlTaskListRepository(conn),
        event_publisher=OutboxEventPublisher(conn),
    )


def make_read_service(conn: AsyncConnection) -> TaskListReadService:
    return TaskListReadService(task_list_repo=SqlTaskListRepository(conn))


class TestCreateTaskList:
    @pytest.mark.asyncio
    async def test_creates_the_list_at_the_bottom_of_the_owners_lists(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_task_list(async_connection, "First")
        await seed_task_list(async_connection, "Archived", archived_at=ARCHIVED_AT)

        created = await make_service(async_connection).create_task_list(
            user_id=USER_ID,
            name="Packing",
            icon=TaskIcon.LUGGAGE,
            transaction=async_connection,
        )

        assert created.id is not None
        assert created.position == 2
        stored = await make_read_service(async_connection).get_task_list(
            user_id=USER_ID, task_list_id=created.id
        )
        assert stored == created
        assert (stored.name, stored.icon, stored.archived_at) == (
            "Packing",
            TaskIcon.LUGGAGE,
            None,
        )

    @pytest.mark.asyncio
    async def test_publishes_exactly_one_created_event_with_the_persisted_list(
        self, async_connection: AsyncConnection
    ) -> None:
        created = await make_service(async_connection).create_task_list(
            user_id=USER_ID,
            name="Packing",
            icon=TaskIcon.LUGGAGE,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        (event,) = await task_list_events(async_connection)
        assert event.event_type == "TaskListCreated"
        assert event.aggregate_id == created.id
        assert event.payload == {
            "task_list_id": created.id,
            "user_id": USER_ID,
            "name": "Packing",
            "icon": "luggage",
            "source": "ui",
            "changed_by": "ui",
        }

    @pytest.mark.asyncio
    async def test_a_list_without_an_icon_is_created_and_announced_with_none(
        self, async_connection: AsyncConnection
    ) -> None:
        created = await make_service(async_connection).create_task_list(
            user_id=USER_ID, name="Errands", icon=None, transaction=async_connection
        )

        assert created.icon is None
        (event,) = await task_list_events(async_connection)
        assert event.payload["icon"] is None
        assert event.payload["source"] == Provenance.SYSTEM.value

    @pytest.mark.asyncio
    async def test_a_refused_create_writes_no_list_and_no_event(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(TaskListValidationError) as refused:
            await make_service(async_connection).create_task_list(
                user_id=USER_ID, name="   ", icon=None, transaction=async_connection
            )

        assert refused.value.field == "name"
        assert await count(async_connection, _COUNT_LISTS, {"user_id": USER_ID}) == 0
        assert await task_list_events(async_connection) == []


class TestGetTaskList:
    @pytest.mark.asyncio
    async def test_reads_back_an_owned_list(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Groceries", icon=TaskIcon.SHOPPING_CART
        )
        assert seeded.id is not None

        found = await make_read_service(async_connection).get_task_list(
            user_id=USER_ID, task_list_id=seeded.id
        )

        assert found == seeded

    @pytest.mark.asyncio
    async def test_a_missing_list_is_not_found(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(TaskListNotFoundError) as missing:
            await make_read_service(async_connection).get_task_list(
                user_id=USER_ID, task_list_id=999_999
            )

        assert missing.value.task_list_id == 999_999

    @pytest.mark.asyncio
    async def test_another_users_list_is_reported_exactly_as_a_missing_one(
        self, async_connection: AsyncConnection
    ) -> None:
        foreign = await seed_task_list(
            async_connection, "Theirs", user_id=OTHER_USER_ID
        )
        assert foreign.id is not None

        with pytest.raises(TaskListNotFoundError) as refused:
            await make_read_service(async_connection).get_task_list(
                user_id=USER_ID, task_list_id=foreign.id
            )

        # The same words a missing id gets: nothing says the list exists.
        assert str(refused.value) == f"Task list with ID {foreign.id} not found"


class TestListTaskLists:
    @pytest.mark.asyncio
    async def test_each_filter_returns_its_lists_in_the_repository_order(
        self, async_connection: AsyncConnection
    ) -> None:
        first = await seed_task_list(async_connection, "First")
        archived = await seed_task_list(
            async_connection, "Archived", archived_at=ARCHIVED_AT
        )
        second = await seed_task_list(async_connection, "Second")
        service = make_read_service(async_connection)

        async def names(archived_filter: TaskListArchiveFilter) -> list[str]:
            lists = await service.list_task_lists(
                user_id=USER_ID, archived=archived_filter
            )
            return [task_list.name for task_list in lists]

        assert await names(TaskListArchiveFilter.ACTIVE) == [first.name, second.name]
        assert await names(TaskListArchiveFilter.ARCHIVED) == [archived.name]
        assert await names(TaskListArchiveFilter.ALL) == [
            first.name,
            archived.name,
            second.name,
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("archived_filter", list(TaskListArchiveFilter))
    async def test_another_users_lists_are_never_returned(
        self,
        async_connection: AsyncConnection,
        archived_filter: TaskListArchiveFilter,
    ) -> None:
        await seed_task_list(async_connection, "Theirs", user_id=OTHER_USER_ID)
        await seed_task_list(
            async_connection,
            "Theirs archived",
            user_id=OTHER_USER_ID,
            archived_at=ARCHIVED_AT,
        )

        lists = await make_read_service(async_connection).list_task_lists(
            user_id=USER_ID, archived=archived_filter
        )

        assert lists == []


class TestWiring:
    @pytest.mark.asyncio
    async def test_the_container_provides_both_services(
        self, async_connection: AsyncConnection
    ) -> None:
        container = make_task_container(async_connection)
        try:
            async with container() as request_container:
                service = await request_container.get(TaskListService)
                read_service = await request_container.get(TaskListReadService)

            assert isinstance(service, TaskListService)
            assert isinstance(read_service, TaskListReadService)
        finally:
            await container.close()

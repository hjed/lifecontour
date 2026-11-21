"""End-to-end backend integration test for task-list history projection.

Exercises the full async chain a real list write travels:

    TaskListService.create_task_list() / update_task_list() /
    archive_task_list() / unarchive_task_list()
        -> OutboxEventPublisher (outbox_events row, same unit of work)
        -> OutboxRelay           (-> pms:domain-events stream)
        -> HistoryProjectionConsumer (-> field_history rows)

and asserts the rows are filed under ``("task_list", list_id)`` with the field
names the list history read answers — ``__created__``, ``name``, ``icon`` and
``archived_at`` — and with provenance, owner and event identity intact. Writes
that change nothing, and reorders, publish nothing and so must project nothing.

Rows are read with ``get_entity_history``, except in
:class:`TestTheListHistoryReadAnswersWithTheProjectedRows`, which reads them
back through ``TaskListHistoryService`` and the ``"task_list"`` aggregation
strategy — proving the read matches the rows the projection really writes.
"""

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskIcon, TaskListNotFoundError
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry
from app.core.history.services.task_list_history_service import (
    TaskListHistoryService,
)
from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.services.task_list_patch import TaskListPatch
from app.core.tasks.services.task_list_service import TaskListService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.infrastructure.events.projection_harness import (
    relay_and_project,
    replay_stream_through_projection,
)
from tests.integration.tasks.task_seeding import OTHER_USER_ID, USER_ID

LIST_ENTITY_TYPE = "task_list"
LIST_NAME = "Groceries"


def _list_service(conn: AsyncConnection) -> TaskListService:
    """The real service over the real adapter and publisher on one connection."""
    return TaskListService(
        task_list_repo=SqlTaskListRepository(conn),
        event_publisher=OutboxEventPublisher(conn),
    )


async def _list_history(conn: AsyncConnection, list_id: int) -> list[FieldHistoryEntry]:
    """Every history row filed under the list."""
    return await SqlFieldHistoryRepository(conn).get_entity_history(
        LIST_ENTITY_TYPE, list_id
    )


def _values(
    entries: list[FieldHistoryEntry],
) -> set[tuple[str, str | None, str | None]]:
    return {(e.field_name, e.old_value, e.new_value) for e in entries}


async def _create(
    service: TaskListService,
    conn: AsyncConnection,
    *,
    user_id: str = USER_ID,
    name: str = LIST_NAME,
    icon: TaskIcon | None = None,
) -> int:
    created = await service.create_task_list(
        user_id=user_id,
        name=name,
        icon=icon,
        transaction=conn,
        source=Provenance.UI,
        changed_by="ui",
    )
    assert created.id is not None
    return created.id


@pytest.mark.integration
class TestTaskListLifecycleProjection:
    @pytest.mark.asyncio
    async def test_a_create_opens_the_lists_own_history(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """The marker carries the name, the provenance and the owner — and is
        filed under ``task_list`` alone: nothing lands under ``task`` or
        ``journal`` for that id."""
        service = _list_service(async_connection)
        created = await service.create_task_list(
            user_id=USER_ID,
            name=LIST_NAME,
            icon=TaskIcon.STAR,
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="assistant",
        )
        assert created.id is not None

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-list-create"
        )

        entries = await _list_history(async_connection, created.id)
        assert _values(entries) == {("__created__", None, LIST_NAME)}
        entry = entries[0]
        assert entry.entity_type == LIST_ENTITY_TYPE
        assert entry.entity_id == created.id
        assert entry.source == Provenance.MCP
        assert entry.changed_by == "assistant"
        assert entry.user_id == USER_ID
        assert entry.event_id is not None

        history = SqlFieldHistoryRepository(async_connection)
        assert await history.get_entity_history("task", created.id) == []
        assert await history.get_entity_history("journal", created.id) == []

    @pytest.mark.asyncio
    async def test_a_rename_is_projected_as_a_name_line(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        service = _list_service(async_connection)
        list_id = await _create(service, async_connection)

        await service.update_task_list(
            user_id=USER_ID,
            task_list_id=list_id,
            patch=TaskListPatch(name="Shopping"),
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="assistant",
        )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-list-rename"
        )

        entries = await _list_history(async_connection, list_id)
        assert _values(entries) == {
            ("__created__", None, LIST_NAME),
            ("name", LIST_NAME, "Shopping"),
        }
        rename = next(e for e in entries if e.field_name == "name")
        assert rename.source == Provenance.MCP
        assert rename.changed_by == "assistant"
        assert rename.user_id == USER_ID

    @pytest.mark.asyncio
    async def test_setting_replacing_and_clearing_the_icon_are_three_lines(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        service = _list_service(async_connection)
        list_id = await _create(service, async_connection)

        for icon in (TaskIcon.STAR, TaskIcon.BOOKMARK, None):
            await service.update_task_list(
                user_id=USER_ID,
                task_list_id=list_id,
                patch=TaskListPatch(icon=icon),
                transaction=async_connection,
            )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-list-icon"
        )

        entries = await _list_history(async_connection, list_id)
        assert _values(entries) == {
            ("__created__", None, LIST_NAME),
            ("icon", None, TaskIcon.STAR.value),
            ("icon", TaskIcon.STAR.value, TaskIcon.BOOKMARK.value),
            ("icon", TaskIcon.BOOKMARK.value, None),
        }

    @pytest.mark.asyncio
    async def test_an_archive_and_an_unarchive_read_as_a_pair(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """``archived_at`` from nothing is the archive, back to nothing the
        unarchive, and the instant is the one the list stored."""
        service = _list_service(async_connection)
        list_id = await _create(service, async_connection)

        archived = await service.archive_task_list(
            user_id=USER_ID, task_list_id=list_id, transaction=async_connection
        )
        assert archived.archived_at is not None
        archived_at = archived.archived_at.isoformat()
        await service.unarchive_task_list(
            user_id=USER_ID, task_list_id=list_id, transaction=async_connection
        )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-list-archive"
        )

        entries = await _list_history(async_connection, list_id)
        assert _values(entries) == {
            ("__created__", None, LIST_NAME),
            ("archived_at", None, archived_at),
            ("archived_at", archived_at, None),
        }


@pytest.mark.integration
class TestOnlyMeaningfulListChangesAreProjected:
    @pytest.mark.asyncio
    async def test_no_op_writes_and_reorders_project_nothing(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A patch naming the current name, a repeat archive, a repeat unarchive
        and a move all publish nothing, so the history holds only the create,
        the one archive and the one unarchive."""
        service = _list_service(async_connection)
        list_id = await _create(service, async_connection)
        await _create(service, async_connection, name="Second")

        await service.update_task_list(
            user_id=USER_ID,
            task_list_id=list_id,
            patch=TaskListPatch(name=LIST_NAME),
            transaction=async_connection,
        )
        await service.move_task_list(
            user_id=USER_ID, task_list_id=list_id, index=1, transaction=async_connection
        )
        for _ in range(2):
            await service.archive_task_list(
                user_id=USER_ID, task_list_id=list_id, transaction=async_connection
            )
        for _ in range(2):
            await service.unarchive_task_list(
                user_id=USER_ID, task_list_id=list_id, transaction=async_connection
            )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-list-noop"
        )

        entries = await _list_history(async_connection, list_id)
        assert sorted(e.field_name for e in entries) == [
            "__created__",
            "archived_at",
            "archived_at",
        ]


@pytest.mark.integration
class TestTaskListProjectionIsIdempotent:
    @pytest.mark.asyncio
    async def test_redelivering_the_whole_stream_writes_no_second_row(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Every list event type is driven, then the stream is replayed: the
        ``event_id`` dedup index is the only thing standing between a consumer
        restart and a duplicated line."""
        service = _list_service(async_connection)
        list_id = await _create(service, async_connection)
        await service.update_task_list(
            user_id=USER_ID,
            task_list_id=list_id,
            patch=TaskListPatch(name="Shopping", icon=TaskIcon.STAR),
            transaction=async_connection,
        )
        await service.archive_task_list(
            user_id=USER_ID, task_list_id=list_id, transaction=async_connection
        )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-list-replay"
        )
        before = await _list_history(async_connection, list_id)
        assert len(before) == 4

        await replay_stream_through_projection(
            stream_client, test_stream_name, async_connection, redis_client
        )

        after = await _list_history(async_connection, list_id)
        assert sorted(e.id for e in after if e.id is not None) == sorted(
            e.id for e in before if e.id is not None
        )
        assert len(after) == 4


@pytest.mark.integration
class TestTaskListRowsCarryTheirOwner:
    @pytest.mark.asyncio
    async def test_each_users_list_rows_are_owned_by_that_user(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Lists are hard-deleted (Phase 29), so the owner rides on the rows,
        taken from the payload — each user's rows name that user and no other."""
        service = _list_service(async_connection)
        mine = await _create(service, async_connection)
        theirs = await _create(
            service, async_connection, user_id=OTHER_USER_ID, name="Theirs"
        )
        await service.archive_task_list(
            user_id=OTHER_USER_ID, task_list_id=theirs, transaction=async_connection
        )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-list-owner"
        )

        my_entries = await _list_history(async_connection, mine)
        their_entries = await _list_history(async_connection, theirs)
        assert {e.user_id for e in my_entries} == {USER_ID}
        assert len(their_entries) == 2
        assert {e.user_id for e in their_entries} == {OTHER_USER_ID}


@pytest.mark.integration
class TestTheListHistoryReadAnswersWithTheProjectedRows:
    @pytest.mark.asyncio
    async def test_real_writes_read_back_newest_first_for_the_owner_only(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        service = _list_service(async_connection)
        list_id = await _create(service, async_connection)
        await service.update_task_list(
            user_id=USER_ID,
            task_list_id=list_id,
            patch=TaskListPatch(name="Shopping"),
            transaction=async_connection,
        )
        await service.archive_task_list(
            user_id=USER_ID, task_list_id=list_id, transaction=async_connection
        )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-list-read"
        )
        reader = TaskListHistoryService(
            history_repo=SqlFieldHistoryRepository(async_connection),
            task_list_repo=SqlTaskListRepository(async_connection),
        )

        entries = await reader.get_task_list_history(
            task_list_id=list_id, user_id=USER_ID
        )

        assert [e.field_name for e in entries] == ["archived_at", "name", "__created__"]
        assert (
            await reader.get_task_list_history_count(
                task_list_id=list_id, user_id=USER_ID
            )
            == 3
        )
        with pytest.raises(TaskListNotFoundError):
            await reader.get_task_list_history(
                task_list_id=list_id, user_id=OTHER_USER_ID
            )

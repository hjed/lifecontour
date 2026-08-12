"""End-to-end backend integration test for task history projection.

Exercises the full async chain a real task mutation travels:

    TaskService.create_task() / update_task() / link_contact() / delete_task()
        -> OutboxEventPublisher (outbox_events row, same unit of work)
        -> OutboxRelay.relay_batch()  (-> pms:domain-events stream)
        -> HistoryProjectionConsumer  (-> field_history rows)

and asserts the rows are readable under the task, with the right field names,
values, provenance and timestamps. ITER18-003 Phase 6 covers the three lifecycle
event types; the retarget and journal-link types are Phase 7 and are asserted
here to be *filtered out* rather than dead-lettered.

Rows are read with ``get_entity_history`` rather than ``get_history_for_aggregate``
because there is no ``"task"`` aggregation strategy yet — Phase 8 registers one
along with the read surface that needs it.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskStatus
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.infrastructure.events.projection_harness import (
    GROUP_NAME,
    relay_and_project,
    replay_stream_through_projection,
)
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_contact,
    create_journal,
    task_events,
)

TASK_TEXT = "Book the venue"
TASK_ENTITY_TYPE = "task"


def _task_service(conn: AsyncConnection) -> TaskService:
    """The real service over real adapters on the test's single connection.

    The publisher is the real ``OutboxEventPublisher`` on that same connection:
    the point of these tests is that the write and its event share a unit of
    work, and a double would prove nothing about whether they do.
    """
    return TaskService(
        task_repo=SqlTaskRepository(conn),
        journal_repo=SqlJournalRepository(conn),
        contact_repo=SqlContactRepository(conn),
        date_resolver=JournalDateResolver(
            user_settings_repo=SqlUserSettingsRepository(conn)
        ),
        event_publisher=OutboxEventPublisher(conn),
    )


async def _anchors(conn: AsyncConnection) -> tuple[int, int]:
    """A journal to create the task in, and a future one for it to be due in."""
    journal_repo = SqlJournalRepository(conn)
    creating_journal_id = await create_journal(journal_repo, title="Today")
    due_journal_id = await create_journal(
        journal_repo, title="Next week", days_offset=7
    )
    return creating_journal_id, due_journal_id


async def _task_history(conn: AsyncConnection, task_id: int) -> list[FieldHistoryEntry]:
    """Every history row filed under the task, most recent first."""
    return await SqlFieldHistoryRepository(conn).get_entity_history(
        TASK_ENTITY_TYPE, task_id
    )


def _values(
    entries: list[FieldHistoryEntry],
) -> set[tuple[str, str | None, str | None]]:
    return {(e.field_name, e.old_value, e.new_value) for e in entries}


@pytest.mark.integration
class TestTaskLifecycleProjection:
    @pytest.mark.asyncio
    async def test_a_create_is_projected_with_its_text_and_its_people(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """The marker opens the history and the contacts are named beside it.

        The second half is what Phase 5's ``contact_ids`` payload exists for: a
        task created with somebody has to show that addition, or the unlink that
        may follow reads as a removal with nothing before it.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)
        contact_id = await create_contact(async_connection, first_name="Sarah")

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
            contact_ids=[contact_id],
            source=Provenance.UI,
            changed_by="ui",
        )
        assert task.id is not None

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-create"
        )

        entries = await _task_history(async_connection, task.id)
        assert _values(entries) == {
            ("__created__", None, TASK_TEXT),
            (f"contact:{contact_id}", None, str(contact_id)),
        }
        for entry in entries:
            assert entry.entity_type == TASK_ENTITY_TYPE
            assert entry.entity_id == task.id
            assert entry.source == Provenance.UI
            assert entry.changed_by == "ui"

    @pytest.mark.asyncio
    async def test_a_row_is_stamped_with_the_event_time_not_the_projection_time(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """History reflects when the change happened.

        The projection runs behind the write by however long the relay and the
        consumer take, and after an outage that can be hours. Stamping rows at
        projection time would file a change under the wrong day.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )
        assert task.id is not None
        published = await task_events(async_connection)
        assert [event.event_type for event in published] == ["TaskCreated"]

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-time"
        )

        entries = await _task_history(async_connection, task.id)
        assert len(entries) == 1
        assert entries[0].created_at is not None
        # The outbox column is a ``timestamp`` without time zone, so the instant
        # comes back naive; it is UTC, because that is what the event stamped.
        # Comparing in UTC rather than on wall-clock components is the point of
        # the assertion — a session-timezone mistake anywhere along the chain
        # moves the row by the server's offset without changing how it reads.
        assert datetime.fromisoformat(str(entries[0].created_at)) == published[
            0
        ].occurred_at.replace(tzinfo=UTC)
        assert entries[0].event_id == published[0].event_id

    @pytest.mark.asyncio
    async def test_a_reword_and_a_completion_are_projected_as_two_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """One ``PATCH`` carrying both is one event, and the user reads two lines."""
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        await service.update_task(
            user_id=USER_ID,
            task_id=task.id,
            transaction=async_connection,
            text="Book the other venue",
            status=TaskStatus.DONE,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-update"
        )

        entries = await _task_history(async_connection, task.id)
        assert _values(entries) == {
            ("__created__", None, TASK_TEXT),
            ("text", TASK_TEXT, "Book the other venue"),
            ("status", TaskStatus.NOT_DONE.value, TaskStatus.DONE.value),
        }
        changed = {e.field_name: e for e in entries}
        assert changed["text"].source == Provenance.MCP
        assert changed["text"].changed_by == "mcp"

    @pytest.mark.asyncio
    async def test_a_link_and_an_unlink_project_the_pair_opposite_ways_round(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Two rows under one field name, distinguished by their event.

        Contact membership is a *field* of the task (Phase 5), so both writes
        arrive as ``TaskUpdated`` and land on the same ``contact:{id}`` key. The
        dedup index includes ``event_id``, which is why the second does not read
        as a redelivery of the first.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)
        contact_id = await create_contact(async_connection, first_name="Sarah")

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        assert await service.link_contact(
            user_id=USER_ID,
            task_id=task.id,
            contact_id=contact_id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )
        assert await service.unlink_contact(
            user_id=USER_ID,
            task_id=task.id,
            contact_id=contact_id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-contacts"
        )

        entries = await _task_history(async_connection, task.id)
        field = f"contact:{contact_id}"
        assert _values(entries) == {
            ("__created__", None, TASK_TEXT),
            (field, None, str(contact_id)),
            (field, str(contact_id), None),
        }
        assert len({e.event_id for e in entries if e.field_name == field}) == 2

    @pytest.mark.asyncio
    async def test_a_deleted_task_keeps_the_history_it_made(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Tasks are hard-deleted; their history is not.

        Nothing in the projection joins back to the ``tasks`` row, so the delete
        marker lands beside the rows the task made while it existed. Phase 8's
        task-scoped read depends on exactly this.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        await service.delete_task(
            user_id=USER_ID,
            task_id=task.id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-delete"
        )

        entries = await _task_history(async_connection, task.id)
        assert _values(entries) == {
            ("__created__", None, TASK_TEXT),
            ("__deleted__", None, None),
        }


@pytest.mark.integration
class TestTaskProjectionIsIdempotent:
    @pytest.mark.asyncio
    async def test_redelivering_the_whole_stream_writes_no_second_row(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Redis Streams are at-least-once, so this is the ordinary case.

        A consumer restart or an ``XAUTOCLAIM`` hands the projection events it has
        already processed. The ``(event_id, entity_type, entity_id, field_name)``
        index is the only thing standing between that and a history that grows a
        duplicate line every time the consumer is bounced.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)
        contact_id = await create_contact(async_connection, first_name="Sarah")

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
            contact_ids=[contact_id],
            source=Provenance.UI,
            changed_by="ui",
        )
        assert task.id is not None
        await service.update_task(
            user_id=USER_ID,
            task_id=task.id,
            transaction=async_connection,
            status=TaskStatus.DONE,
            source=Provenance.UI,
            changed_by="ui",
        )
        await service.unlink_contact(
            user_id=USER_ID,
            task_id=task.id,
            contact_id=contact_id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-idempotent"
        )
        first_pass = await _task_history(async_connection, task.id)
        assert len(first_pass) == 4

        await replay_stream_through_projection(
            stream_client, test_stream_name, async_connection, redis_client
        )

        second_pass = await _task_history(async_connection, task.id)
        assert [e.id for e in second_pass] == [e.id for e in first_pass]
        assert _values(second_pass) == _values(first_pass)


@pytest.mark.integration
class TestTaskEventsDeferredToPhase7:
    @pytest.mark.asyncio
    async def test_a_retarget_is_filtered_out_rather_than_dead_lettered(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """The two events a retarget publishes have no handler until Phase 7.

        Unsubscribed types are skip-acknowledged by the consumer, so they neither
        project a row nor sit pending until they dead-letter. This test should
        start failing on its first assertion when Phase 7 lands, which is the
        point: the gap is asserted rather than assumed.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)
        new_due_journal_id = await create_journal(
            SqlJournalRepository(async_connection),
            title="The week after",
            days_offset=14,
        )

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=task.id,
            due_journal_id=new_due_journal_id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )
        published = {event.event_type for event in await task_events(async_connection)}
        assert published == {
            "TaskCreated",
            "TaskDueJournalRetargeted",
            "TaskJournalLinked",
        }

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-retarget"
        )

        entries = await _task_history(async_connection, task.id)
        assert _values(entries) == {("__created__", None, TASK_TEXT)}

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

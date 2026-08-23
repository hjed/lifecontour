"""Integration tests for the task history backfill.

Two holes were left behind by Phases 6 and 7, and this is the mechanism that
closes both:

**(a) Historic task events were skip-acknowledged, not replayed.** A deployed
``history-projection`` group has been *reading* task events since Phase 1 and
acknowledging them as non-matching, because nothing in its pattern list matched
them. Phase 6 widened the list for three types and Phase 7 for the other three,
but a consumer group only ever sees each message once: widening the patterns
projects events published *after* the deploy and nothing before it. Every task
that already exists therefore has no history at all.

**(b) Rows already projected carry no owner**, because the column did not exist
when they were written, and a task-scoped read cannot authorise them.

**The setup is the whole point.** Phase 6's own tests could not have caught (a):
a fresh stream and a fresh group have nothing already acknowledged, so a
backfill that did nothing would pass. These tests therefore build the deployed
state explicitly — a real ``history-projection`` group that consumes and
**acknowledges** the task events with the task patterns removed from its
subscription, exactly as the deployed consumer did — and only then run the
backfill. A test written against a fresh group would be asserting nothing.
"""

from typing import Any

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskStatus
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.services.task_history_backfill import TaskHistoryBackfill
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.events.outbox_relay import OutboxRelay
from tests.integration.infrastructure.events.projection_harness import (
    GROUP_NAME,
    patched_projection_engine,
    relay_and_project,
)
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_contact,
    create_journal,
)

TASK_TEXT = "Book the venue"


def _task_service(conn: AsyncConnection) -> TaskService:
    """The real service over real adapters on the test's single connection."""
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
    journal_repo = SqlJournalRepository(conn)
    creating_id = await create_journal(journal_repo, title="Today")
    due_id = await create_journal(journal_repo, title="Next week", days_offset=7)
    return creating_id, due_id


async def _relay_then_skip_acknowledge_task_events(
    stream_client: StreamClient,
    stream_name: str,
    conn: AsyncConnection,
) -> None:
    """Reproduce the deployed state this backfill exists to repair.

    Relays the outbox and runs a **real** ``history-projection`` consumer over
    the stream with the task patterns removed from its subscription — which is
    precisely what the deployed consumer did before Phases 6 and 7 widened them.
    The group reads each task event, finds no match, and **acknowledges** it, so
    it will never be redelivered. Non-task events on the same batch are
    projected normally, which is what makes the "nothing else was touched"
    assertions below non-vacuous.
    """
    relay = OutboxRelay(
        stream_client=stream_client, stream_name=stream_name, batch_size=100
    )
    await relay.relay_batch(conn)

    consumer = HistoryProjectionConsumer(
        stream_client=stream_client,
        stream_name=stream_name,
        consumer_name="deployed-before-phase-6",
        batch_size=100,
        block_ms=100,
    )
    consumer._event_type_patterns = [
        pattern
        for pattern in consumer._event_type_patterns
        if not pattern.startswith("Task")
    ]
    await stream_client.ensure_consumer_group(stream_name, GROUP_NAME)

    with patched_projection_engine(conn):
        await consumer._process_batch()


async def _task_rows(conn: AsyncConnection, task_id: int) -> list[Any]:
    return await SqlFieldHistoryRepository(conn).get_entity_history("task", task_id)


async def _pending_count(redis_client: Redis, stream_name: str) -> int:
    """How many messages the group still owes an acknowledgement for.

    Zero is what makes the deployed state real: an acknowledged message is not
    redelivered, so widening the consumer's patterns can never recover it.
    """
    info = await redis_client.xpending(stream_name, GROUP_NAME)
    return int(info["pending"])


@pytest.mark.integration
class TestTheBackfillRepairsAlreadyAcknowledgedEvents:
    """The case a fresh stream and a fresh group cannot express."""

    @pytest.mark.asyncio
    async def test_a_tasks_whole_history_appears_after_the_events_were_acked(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        service = _task_service(async_connection)
        creating_id, due_id = await _anchors(async_connection)
        contact_id = await create_contact(async_connection, first_name="Sarah")

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
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
            source=Provenance.MCP,
            changed_by="mcp",
        )

        await _relay_then_skip_acknowledge_task_events(
            stream_client, test_stream_name, async_connection
        )

        # The state the deploy actually left behind: nothing pending, and no
        # history whatsoever for a task that has demonstrably changed twice.
        assert await _pending_count(redis_client, test_stream_name) == 0
        assert await _task_rows(async_connection, task.id) == []

        result = await TaskHistoryBackfill().run(async_connection)

        rows = await _task_rows(async_connection, task.id)
        assert {(r.field_name, r.old_value, r.new_value) for r in rows} == {
            ("__created__", None, TASK_TEXT),
            (f"contact:{contact_id}", None, str(contact_id)),
            ("status", "not_done", "done"),
        }
        assert result.rows_written == 3

    @pytest.mark.asyncio
    async def test_the_repaired_rows_carry_their_provenance_and_their_owner(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """A backfilled row is indistinguishable from a live-projected one.

        It goes through the same ``HistoryService``, so the provenance, the
        actor and the event-time timestamp come from the retained event rather
        than from the moment the repair ran — which is the reason the repair is
        application code and not SQL.
        """
        service = _task_service(async_connection)
        creating_id, due_id = await _anchors(async_connection)

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text=TASK_TEXT,
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="mcp",
        )
        assert task.id is not None

        await _relay_then_skip_acknowledge_task_events(
            stream_client, test_stream_name, async_connection
        )
        await TaskHistoryBackfill().run(async_connection)

        row = (await _task_rows(async_connection, task.id))[0]
        assert row.source == Provenance.MCP
        assert row.changed_by == "mcp"
        assert row.user_id == USER_ID
        assert row.event_id is not None

    @pytest.mark.asyncio
    async def test_a_deleted_tasks_history_is_recoverable_too(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The task row is gone, and the repair still knows whose it was.

        This is why the owner comes off the retained event payload rather than a
        join to ``tasks``: for a task deleted before this phase shipped, there is
        nothing to join to and ``outbox_events`` is the only surviving record.
        """
        service = _task_service(async_connection)
        creating_id, due_id = await _anchors(async_connection)

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None
        await service.delete_task(
            user_id=USER_ID, task_id=task.id, transaction=async_connection
        )

        await _relay_then_skip_acknowledge_task_events(
            stream_client, test_stream_name, async_connection
        )
        await TaskHistoryBackfill().run(async_connection)

        rows = await _task_rows(async_connection, task.id)
        assert {r.field_name for r in rows} == {"__created__", "__deleted__"}
        assert {r.user_id for r in rows} == {USER_ID}


@pytest.mark.integration
class TestTheBackfillIsSafeToRunRepeatedly:
    @pytest.mark.asyncio
    async def test_a_second_run_writes_nothing(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """It runs on every application start, so this is the ordinary case."""
        service = _task_service(async_connection)
        creating_id, due_id = await _anchors(async_connection)
        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        await _relay_then_skip_acknowledge_task_events(
            stream_client, test_stream_name, async_connection
        )
        first = await TaskHistoryBackfill().run(async_connection)
        second = await TaskHistoryBackfill().run(async_connection)

        assert first.rows_written == 1
        assert second.events_examined == 0
        assert second.rows_written == 0
        assert len(await _task_rows(async_connection, task.id)) == 1

    @pytest.mark.asyncio
    async def test_it_leaves_rows_the_live_projection_already_wrote_alone(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The repair overlaps live projection rather than racing it.

        Both write ``ON CONFLICT (event_id, entity_type, entity_id, field_name)
        DO NOTHING``, so whichever gets there first wins and the other is a
        no-op — which is what makes running this at startup, beside a consumer
        that is already going, safe.
        """
        service = _task_service(async_connection)
        creating_id, due_id = await _anchors(async_connection)
        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "live-projection"
        )
        before = await _task_rows(async_connection, task.id)
        assert len(before) == 1

        result = await TaskHistoryBackfill().run(async_connection)

        after = await _task_rows(async_connection, task.id)
        assert [r.id for r in after] == [r.id for r in before]
        assert result.rows_written == 0


@pytest.mark.integration
class TestTheOwnerFill:
    @pytest.mark.asyncio
    async def test_it_fills_the_owner_on_rows_projected_before_the_column_existed(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The Phase 6/7 deploy window: rows projected correctly, but unowned.

        Those rows cannot be repaired by re-projection — the anti-join skips
        them, because they exist — so this is the half of the repair that is a
        set-based update rather than a replay.
        """
        service = _task_service(async_connection)
        creating_id, due_id = await _anchors(async_connection)
        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "live-projection"
        )
        # Return the rows to the state a pre-0107 deploy left them in.
        await async_connection.execute(
            text(
                "UPDATE field_history SET user_id = NULL "
                "WHERE entity_type = 'task' AND entity_id = :task_id"
            ),
            {"task_id": task.id},
        )
        assert (await _task_rows(async_connection, task.id))[0].user_id is None

        result = await TaskHistoryBackfill().run(async_connection)

        assert result.owners_filled == 1
        assert (await _task_rows(async_connection, task.id))[0].user_id == USER_ID

    @pytest.mark.asyncio
    async def test_it_touches_nothing_outside_the_task_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The control that keeps every assertion above honest.

        A journal rides the same stream and the same batch. Its history must be
        projected — proving the machinery ran at all — and its rows must still
        carry no owner, proving the repair is as narrow as it claims. Without the
        journal, a backfill that did nothing whatsoever would satisfy the second
        half of this test.
        """
        journal_repo = SqlJournalRepository(async_connection)
        service = _task_service(async_connection)
        creating_id, due_id = await _anchors(async_connection)
        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        journal = await journal_repo.find_by_id(creating_id)
        assert journal is not None
        await OutboxEventPublisher(async_connection).publish(
            _journal_updated_event(creating_id)
        )

        await _relay_then_skip_acknowledge_task_events(
            stream_client, test_stream_name, async_connection
        )

        journal_rows = await SqlFieldHistoryRepository(
            async_connection
        ).get_entity_history("journal", creating_id)
        assert journal_rows, "the control journal event must have been projected"
        journal_row_ids = {r.id for r in journal_rows}

        await TaskHistoryBackfill().run(async_connection)

        after = await SqlFieldHistoryRepository(async_connection).get_entity_history(
            "journal", creating_id
        )
        assert {r.id for r in after} == journal_row_ids
        assert {r.user_id for r in after} == {None}


def _journal_updated_event(journal_id: int) -> Any:
    """A minimal ``JournalUpdated``, used only as a positive control."""
    from app.core.journal.models.events import JournalUpdated

    return JournalUpdated(
        journal_id=journal_id,
        changed_fields={"title": ("Today", "Today, revised")},
        source=Provenance.UI,
        changed_by="ui",
    )

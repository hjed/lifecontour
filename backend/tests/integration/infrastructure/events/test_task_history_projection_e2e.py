"""End-to-end backend integration test for task history projection.

Exercises the full async chain a real task mutation travels:

    TaskService.create_task() / update_task() / link_contact() / delete_task()
        -> OutboxEventPublisher (outbox_events row, same unit of work)
        -> OutboxRelay.relay_batch()  (-> pms:domain-events stream)
        -> HistoryProjectionConsumer  (-> field_history rows)

and asserts the rows are readable under the task, with the right field names,
values, provenance and timestamps. Every type the domain publishes is exercised
here: the three lifecycle types, the due-anchor move, and the
intermediate-journal pair.

Rows are read with ``get_entity_history`` rather than ``get_history_for_aggregate``.
The ``"task"`` aggregation strategy now exists (Phase 8), and one test below
reads through it deliberately to pin that the two agree; the rest keep the
narrower read so a failure points at the projection rather than at the strategy.
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
from app.core.journal.models.events import JournalUpdated
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
from tests.task_event_inventory import task_event_types

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

        The lifecycle is driven through **every** type the domain publishes —
        create, update, retarget (which publishes two), attach, detach, delete —
        so a handler added later without a distinct ``event_id`` or field name
        fails here rather than in production.
        """
        service = _task_service(async_connection)
        journal_repo = SqlJournalRepository(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)
        contact_id = await create_contact(async_connection, first_name="Sarah")
        new_due_journal_id = await create_journal(
            journal_repo, title="The week after", days_offset=14
        )
        mentioned_journal_id = await create_journal(
            journal_repo, title="Mentioned", days_offset=3
        )

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
        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=task.id,
            due_journal_id=new_due_journal_id,
            transaction=async_connection,
            acknowledge_reopen=True,
            source=Provenance.UI,
            changed_by="ui",
        )
        assert await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task.id,
            journal_id=mentioned_journal_id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )
        assert await service.detach_intermediate_journal(
            user_id=USER_ID,
            task_id=task.id,
            journal_id=mentioned_journal_id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )
        await service.delete_task(
            user_id=USER_ID,
            task_id=task.id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )
        # A subset of the module's types rather than all of them: a task's anchors
        # are also re-pointed by the *journal* domain, and no TaskService call can
        # publish that. Requiring equality here would fail this idempotency test,
        # with a message about idempotency, on the day that type is added.
        published = {e.event_type for e in await task_events(async_connection)}
        assert published <= task_event_types()
        assert len(published) == 6, (
            f"the lifecycle above should drive six types, drove {sorted(published)}"
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-idempotent"
        )
        first_pass = await _task_history(async_connection, task.id)
        # created + the contact it named, the status move, the contact unlink,
        # the anchor move and its reopen, the retained link, the manual attach
        # and its detach, and the delete marker.
        assert len(first_pass) == 10

        await replay_stream_through_projection(
            stream_client, test_stream_name, async_connection, redis_client
        )

        second_pass = await _task_history(async_connection, task.id)
        assert [e.id for e in second_pass] == [e.id for e in first_pass]
        assert _values(second_pass) == _values(first_pass)


@pytest.mark.integration
class TestTaskRetargetAndJournalLinkProjection:
    """The anchor move and the intermediate links a task gains and loses.

    These three types were published for several phases before anything read
    them, and the gap was asserted here rather than assumed — a test written to
    fail the moment a handler and its subscription arrived. This is that test
    inverted: the same write paths, now checked for the rows they produce rather
    than for their silence.
    """

    @pytest.mark.asyncio
    async def test_a_retarget_projects_the_move_and_the_journal_it_retained(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """One user action, two events, two rows that read as one story.

        A retarget moves the due anchor and keeps the journal it is leaving as an
        intermediate link — the model's one automatic link — and publishes an
        event for each. The pair has to survive as *two distinguishable rows*: the
        move under ``due_journal_id`` naming both journals, and the retained link
        under a key naming the journal, so the trail says which journal, in which
        role, and when.
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
        assert _values(entries) == {
            ("__created__", None, TASK_TEXT),
            ("due_journal_id", str(due_journal_id), str(new_due_journal_id)),
            (f"journal:{due_journal_id}", None, str(due_journal_id)),
        }

        # The two rows agree about who acted. A retarget is something the *user*
        # did, and the retained link is a consequence of their action rather than
        # a background job — stamping it `system` would tell a person reading
        # their own history that half of what they did was not theirs.
        retarget_rows = [e for e in entries if e.field_name != "__created__"]
        assert len(retarget_rows) == 2
        for entry in retarget_rows:
            assert entry.source == Provenance.UI
            assert entry.changed_by == "ui"

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_a_reopening_retarget_also_projects_the_status_move(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Retargeting is the only way a done task reopens, so history says so.

        The event adds the status pair *only* when the task actually moved, which
        is why an ordinary deferral (the test above) writes no status line and
        this one does.
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
        await service.set_status(
            user_id=USER_ID,
            task_id=task.id,
            status=TaskStatus.DONE,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=task.id,
            due_journal_id=new_due_journal_id,
            transaction=async_connection,
            acknowledge_reopen=True,
            source=Provenance.UI,
            changed_by="ui",
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-reopen"
        )

        entries = await _task_history(async_connection, task.id)
        assert _values(entries) == {
            ("__created__", None, TASK_TEXT),
            ("status", "not_done", "done"),
            ("status", "done", "not_done"),
            ("due_journal_id", str(due_journal_id), str(new_due_journal_id)),
            (f"journal:{due_journal_id}", None, str(due_journal_id)),
        }
        # ``_values`` is a set, so it cannot see a row written twice. The count is
        # what says each of those lines appears once in the user's history.
        assert len(entries) == 5

    @pytest.mark.asyncio
    async def test_leaving_an_already_linked_journal_writes_no_second_row(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """The A→B→A→C sequence, against a real database.

        Adding an intermediate link is idempotent and nothing here ever removes
        one, so a task that leaves A, comes back and leaves it again finds A still
        linked. The service publishes a link event only when a row was actually
        written, so the second departure adds no history. Without that, a user's
        trail would claim they linked the same journal twice.
        """
        service = _task_service(async_connection)
        journal_repo = SqlJournalRepository(async_connection)
        creating_journal_id, journal_a = await _anchors(async_connection)
        journal_b = await create_journal(journal_repo, title="B", days_offset=14)
        journal_c = await create_journal(journal_repo, title="C", days_offset=21)

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=journal_a,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        for destination in (journal_b, journal_a, journal_c):
            await service.retarget_due_journal(
                user_id=USER_ID,
                task_id=task.id,
                due_journal_id=destination,
                transaction=async_connection,
                source=Provenance.UI,
                changed_by="ui",
            )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-abac"
        )

        entries = await _task_history(async_connection, task.id)
        link_rows = [e for e in entries if e.field_name == f"journal:{journal_a}"]
        assert len(link_rows) == 1
        assert _values(entries) == {
            ("__created__", None, TASK_TEXT),
            ("due_journal_id", str(journal_a), str(journal_b)),
            ("due_journal_id", str(journal_b), str(journal_a)),
            ("due_journal_id", str(journal_a), str(journal_c)),
            (f"journal:{journal_a}", None, str(journal_a)),
            (f"journal:{journal_b}", None, str(journal_b)),
        }

    @pytest.mark.asyncio
    async def test_two_deferrals_read_back_as_a_trail(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Each move's "from" is the previous move's "to".

        The point of projecting the pair rather than the current anchor: the rows
        chain, so a reader can follow a task's deadline through every journal it
        passed rather than seeing only where it ended up. Ordered by the time the
        change happened, which is the event's own timestamp rather than the
        projection's.
        """
        service = _task_service(async_connection)
        journal_repo = SqlJournalRepository(async_connection)
        creating_journal_id, journal_a = await _anchors(async_connection)
        journal_b = await create_journal(journal_repo, title="B", days_offset=14)
        journal_c = await create_journal(journal_repo, title="C", days_offset=21)

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=journal_a,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        for destination in (journal_b, journal_c):
            await service.retarget_due_journal(
                user_id=USER_ID,
                task_id=task.id,
                due_journal_id=destination,
                transaction=async_connection,
                source=Provenance.UI,
                changed_by="ui",
            )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-trail"
        )

        entries = await _task_history(async_connection, task.id)
        # get_entity_history is most-recent-first; read the trail forwards.
        moves = [e for e in reversed(entries) if e.field_name == "due_journal_id"]
        assert [(e.old_value, e.new_value) for e in moves] == [
            (str(journal_a), str(journal_b)),
            (str(journal_b), str(journal_c)),
        ]

    @pytest.mark.asyncio
    async def test_a_manual_attach_and_detach_project_the_pair_opposite_ways_round(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Two rows under one field name, distinguished by their event.

        The same shape a task's contacts already produce, and for the same
        reason: the key names the journal so a second link cannot collide with the
        first, and the dedup index includes ``event_id`` so the removal is not
        read as a redelivery of the addition.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)
        mentioned_journal_id = await create_journal(
            SqlJournalRepository(async_connection), title="Mentioned", days_offset=3
        )

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        assert await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task.id,
            journal_id=mentioned_journal_id,
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="mcp",
        )
        assert await service.detach_intermediate_journal(
            user_id=USER_ID,
            task_id=task.id,
            journal_id=mentioned_journal_id,
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-attach"
        )

        entries = await _task_history(async_connection, task.id)
        field = f"journal:{mentioned_journal_id}"
        assert _values(entries) == {
            ("__created__", None, TASK_TEXT),
            (field, None, str(mentioned_journal_id)),
            (field, str(mentioned_journal_id), None),
        }
        assert len(entries) == 3
        assert len({e.event_id for e in entries if e.field_name == field}) == 2

    @pytest.mark.asyncio
    async def test_a_derived_link_and_a_manual_one_share_a_field_name(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """``origin`` distinguishes the two events and not their history rows.

        A retarget-derived link carries ``origin="retarget"`` and a manual attach
        ``origin="manual"``, but ``field_history`` has no column for it and the
        field name must not carry it: the unlink that later removes either one has
        no origin to spell, so a key that named it would break the pair. Asserted
        against the database rather than left to the handler's docstring.
        """
        service = _task_service(async_connection)
        journal_repo = SqlJournalRepository(async_connection)
        creating_journal_id, journal_a = await _anchors(async_connection)
        journal_b = await create_journal(journal_repo, title="B", days_offset=14)
        manual_journal_id = await create_journal(
            journal_repo, title="Mentioned", days_offset=3
        )

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=journal_a,
            text=TASK_TEXT,
            transaction=async_connection,
        )
        assert task.id is not None

        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=task.id,
            due_journal_id=journal_b,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )
        assert await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task.id,
            journal_id=manual_journal_id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-origin"
        )

        entries = await _task_history(async_connection, task.id)
        link_fields = {
            e.field_name for e in entries if e.field_name.startswith("journal:")
        }
        assert link_fields == {
            f"journal:{journal_a}",
            f"journal:{manual_journal_id}",
        }


@pytest.mark.integration
class TestProjectedRowsCarryTheirOwner:
    """The live path and the backfill have to agree about ownership.

    ``field_history.user_id`` is what lets a **hard-deleted** task's history
    stay both readable and owner-scoped, and there are two writers of it: this
    consumer, and ``TaskHistoryBackfill`` repairing what the consumer never saw.
    A row that reaches the table by one route and not the other would make a
    task's history readable or unreadable depending on when it happened to be
    written, so the live route is asserted here and the repair route in
    ``test_task_history_backfill_integration.py``.
    """

    @pytest.mark.asyncio
    async def test_every_row_a_task_write_projects_names_its_owner(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
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
            source=Provenance.MCP,
            changed_by="mcp",
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-owner"
        )

        entries = await _task_history(async_connection, task.id)
        assert len(entries) == 3
        assert {entry.user_id for entry in entries} == {USER_ID}

    @pytest.mark.asyncio
    async def test_the_owner_is_the_task_owner_rather_than_whoever_acted(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """``user_id`` and ``changed_by`` answer different questions.

        An assistant editing your task writes ``changed_by="mcp"`` on a row that
        is still **yours**. Conflating the two would file an MCP-made change
        under a user called "mcp" and lose it from your history.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="mcp",
        )
        assert task.id is not None

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-actor"
        )

        entry = (await _task_history(async_connection, task.id))[0]
        assert entry.changed_by == "mcp"
        assert entry.user_id == USER_ID

    @pytest.mark.asyncio
    async def test_a_journal_row_written_by_the_same_consumer_carries_no_owner(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The narrowing, asserted where both halves are written by one consumer.

        A journal event travels the identical path and must still land unowned:
        journal history authorises by loading the journal, so stamping its rows
        would imply a check nothing performs. Without this, "only task rows are
        stamped" is a claim about code rather than about the table.
        """
        journal_repo = SqlJournalRepository(async_connection)
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

        # Only the event matters here — the projection reads the payload, not
        # the journal row — so the title is not actually changed.
        assert await journal_repo.find_by_id(creating_journal_id) is not None
        await OutboxEventPublisher(async_connection).publish(
            JournalUpdated(
                journal_id=creating_journal_id,
                changed_fields={"title": ("Today", "Today, revised")},
                source=Provenance.UI,
                changed_by="ui",
            )
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-owner-narrowing"
        )

        task_rows = await _task_history(async_connection, task.id)
        journal_rows = await SqlFieldHistoryRepository(
            async_connection
        ).get_entity_history("journal", creating_journal_id)

        assert {row.user_id for row in task_rows} == {USER_ID}
        assert journal_rows, "the journal control must have been projected"
        assert {row.user_id for row in journal_rows} == {None}

    @pytest.mark.asyncio
    async def test_the_task_aggregation_strategy_reads_the_same_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The read surface and the projection agree about where rows live.

        Everything else in this file reads by ``(entity_type, entity_id)``
        directly. The endpoint and the MCP tool read through the registered
        ``"task"`` strategy instead, so this is the one test that closes the loop
        between what is written and what is served.
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

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-task-strategy"
        )

        direct = await _task_history(async_connection, task.id)
        via_strategy = await SqlFieldHistoryRepository(
            async_connection
        ).get_history_for_aggregate("task", task.id)

        assert [row.id for row in via_strategy] == [row.id for row in direct]


@pytest.mark.integration
class TestATaskReachesTheContactsOwnFeed:
    """The whole chain, read from the *contact* end.

    Everything above reads rows back under the task. The specification's
    *Contacts on tasks* asks for the same rows to surface on the person's
    activity history, which they reach through the widened ``"contact"``
    aggregation strategy rather than through a second projection. These tests
    close that loop: a real service write, relayed and projected, read through
    the strategy the contact history endpoint uses.
    """

    @staticmethod
    async def _contact_feed(
        conn: AsyncConnection, contact_id: int
    ) -> list[FieldHistoryEntry]:
        return await SqlFieldHistoryRepository(conn).get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

    @pytest.mark.asyncio
    async def test_a_task_created_with_someone_lands_on_their_feed(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
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
            stream_client, test_stream_name, async_connection, "test-contact-feed"
        )

        entries = await self._contact_feed(async_connection, contact_id)

        assert _values(entries) == {(f"contact:{contact_id}", None, str(contact_id))}
        assert entries[0].entity_type == TASK_ENTITY_TYPE
        assert entries[0].entity_id == task.id
        assert entries[0].source == Provenance.UI
        assert entries[0].changed_by == "ui"

    @pytest.mark.asyncio
    async def test_a_later_link_and_unlink_both_land_on_their_feed(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """Both halves of the pair, or the feed shows a removal with no addition."""
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)
        contact_id = await create_contact(async_connection, first_name="Marcus")

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
            source=Provenance.MCP,
            changed_by="mcp",
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
            stream_client, test_stream_name, async_connection, "test-contact-pair"
        )

        entries = await self._contact_feed(async_connection, contact_id)

        assert _values(entries) == {
            (f"contact:{contact_id}", None, str(contact_id)),
            (f"contact:{contact_id}", str(contact_id), None),
        }
        assert {e.source for e in entries} == {Provenance.MCP, Provenance.UI}

    @pytest.mark.asyncio
    async def test_the_tasks_own_lifecycle_stays_off_their_feed(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """Open decision 3: the record is the link, not the task's progress.

        A reword and a completion are projected — the assertions on the task's
        own history above prove that — and neither reaches the person's page.
        Folding them in would make a contact a third place to work through
        tasks, which the specification's *Where tasks appear* forbids.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)
        contact_id = await create_contact(async_connection, first_name="Quiet")

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
            contact_ids=[contact_id],
        )
        assert task.id is not None
        await service.update_task(
            user_id=USER_ID,
            task_id=task.id,
            text="Book the other venue",
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-contact-quiet"
        )

        task_rows = await _task_history(async_connection, task.id)
        feed = await self._contact_feed(async_connection, contact_id)

        assert {"text", "status"} <= {e.field_name for e in task_rows}
        assert [e.field_name for e in feed] == [f"contact:{contact_id}"]

    @pytest.mark.asyncio
    async def test_deleting_the_task_does_not_erase_it_from_their_feed(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """A hard-deleted task is still part of the person's past — and says so.

        Two things at once, because they are the same fact from both ends. The
        link entry survives, which is the test a ``task_contacts`` join fails:
        that row cascades away with the task, so a joined predicate would
        silently empty the feed. And the **delete marker** arrives beside it, so
        the person is not left with a link to a commitment that no longer
        exists, reading as though it still stands.
        """
        service = _task_service(async_connection)
        creating_journal_id, due_journal_id = await _anchors(async_connection)
        contact_id = await create_contact(async_connection, first_name="Remembered")

        task = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=TASK_TEXT,
            transaction=async_connection,
            contact_ids=[contact_id],
        )
        assert task.id is not None
        await service.delete_task(
            user_id=USER_ID,
            task_id=task.id,
            transaction=async_connection,
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-contact-deleted"
        )

        entries = await self._contact_feed(async_connection, contact_id)

        assert {e.entity_id for e in entries} == {task.id}
        assert _values(entries) == {
            (f"contact:{contact_id}", None, str(contact_id)),
            ("__deleted__", None, None),
        }

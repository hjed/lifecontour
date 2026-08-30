"""Integration tests for the journal delete guard against real PostgreSQL.

The unit tests pin the *rule*; these pin it against the schema that would
otherwise enforce it blindly. The anchors are ``ON DELETE RESTRICT``, so without
the guard every assertion here would still refuse the delete — but as a raw
``IntegrityError``, which is a 500 the caller can do nothing with. Each test
therefore asserts the *kind* of failure, not merely that one happened.

Four promises:

- **anchors block, whatever the status** — a done or cancelled task's link is
  part of the record, so the deletion is refused for all three statuses;
- **the explanation is complete** — the blocking task and the journal it can be
  actioned from come back on the error, so a caller can build the link;
- **mentions do not block** — a journal linked only as an intermediate journal
  still deletes, taking its link row with it and leaving the task whole;
- **one query** — the blockers arrive together, not one round trip per task.

The seeding goes through raw inserts (``task_seeding.create_task``) rather than
``TaskService``, because the states worth testing here — done, cancelled, due in
a journal that has since passed — are ones a task reaches after creation.
"""

import pytest
import pytest_asyncio
from core_shared.models.journals import BlockingTask, JournalHasAnchoredTasksError
from core_shared.models.tasks import TaskJournalRepointing, TaskStatus
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.models.repositories import TaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.statement_recorder import recorded_statements
from tests.integration.tasks.task_seeding import (
    create_journal,
    create_task,
    link_intermediate_journal,
    make_task_container,
)

_COUNT_JOURNAL = "SELECT COUNT(*) FROM journals WHERE id = :journal_id"
_COUNT_TASK = "SELECT COUNT(*) FROM tasks WHERE id = :task_id"
_COUNT_INTERMEDIATE = (
    "SELECT COUNT(*) FROM task_intermediate_journals WHERE task_id = :task_id"
)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def task_anchor_repository(
    async_connection: AsyncConnection,
) -> SqlTaskAnchorRepository:
    return SqlTaskAnchorRepository(async_connection)


@pytest_asyncio.fixture
async def journal_service(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    task_anchor_repository: SqlTaskAnchorRepository,
) -> JournalService:
    return JournalService(
        journal_repo=journal_repository,
        event_publisher=OutboxEventPublisher(async_connection),
        task_anchor_repo=task_anchor_repository,
    )


async def count(conn: AsyncConnection, sql: str, params: dict[str, int]) -> int:
    return int((await conn.execute(text(sql), params)).scalar_one())


@pytest.mark.integration
class TestAnchoredJournalCannotBeDeleted:
    """An anchoring journal is refused, explanatorily, at any task status."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status", [TaskStatus.NOT_DONE, TaskStatus.DONE, TaskStatus.CANCELLED]
    )
    async def test_deleting_the_due_journal_is_refused_whatever_the_status(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        journal_service: JournalService,
        status: TaskStatus,
    ):
        creating_id = await create_journal(journal_repository, title="Monday Planning")
        due_id = await create_journal(journal_repository, title="Permit Meeting")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )

        with pytest.raises(JournalHasAnchoredTasksError) as exc_info:
            await journal_service.delete_journal(due_id, async_connection)

        error = exc_info.value
        assert error.status_code == 409
        assert [blocker.task_id for blocker in error.blocking_tasks] == [task_id]
        blocker = error.blocking_tasks[0]
        assert blocker.status == status
        assert blocker.blocking_roles == ("due",)
        # The due journal is going away, so the task is actioned from where it
        # was created.
        assert blocker.action_journal_id == creating_id
        assert blocker.action_journal_title == "Monday Planning"
        assert (
            await count(async_connection, _COUNT_JOURNAL, {"journal_id": due_id}) == 1
        )

    @pytest.mark.asyncio
    async def test_deleting_the_creating_journal_points_at_the_due_journal(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        journal_service: JournalService,
    ):
        creating_id = await create_journal(journal_repository, title="Monday Planning")
        due_id = await create_journal(journal_repository, title="Permit Meeting")
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        with pytest.raises(JournalHasAnchoredTasksError) as exc_info:
            await journal_service.delete_journal(creating_id, async_connection)

        blocker = exc_info.value.blocking_tasks[0]
        assert blocker.blocking_roles == ("creating",)
        assert blocker.action_journal_id == due_id
        assert blocker.action_journal_title == "Permit Meeting"

    @pytest.mark.asyncio
    async def test_a_journal_that_is_both_anchors_points_at_itself(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        journal_service: JournalService,
    ):
        """The specification permits creating == due. The deletion is refused,
        so the journal is still there for the user to open and clear the task
        from."""
        journal_id = await create_journal(journal_repository, title="Permit Meeting")
        await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=journal_id,
        )

        with pytest.raises(JournalHasAnchoredTasksError) as exc_info:
            await journal_service.delete_journal(journal_id, async_connection)

        blocker = exc_info.value.blocking_tasks[0]
        assert blocker.blocking_roles == ("creating", "due")
        assert blocker.action_journal_id == journal_id

    @pytest.mark.asyncio
    async def test_the_failure_is_the_domain_error_and_never_an_integrity_error(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        journal_service: JournalService,
    ):
        """The guard replaces the raw foreign-key violation rather than sitting
        in front of it: nothing the caller sees mentions a constraint."""
        creating_id = await create_journal(journal_repository)
        due_id = await create_journal(journal_repository)
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        with pytest.raises(JournalHasAnchoredTasksError) as exc_info:
            await journal_service.delete_journal(due_id, async_connection)

        assert not isinstance(exc_info.value, IntegrityError)
        assert "fkey" not in exc_info.value.message
        assert "constraint" not in exc_info.value.message


@pytest.mark.integration
class TestConcurrentInsertBackstop:
    """The check-then-act window, against a database that really aborts."""

    @pytest.mark.asyncio
    async def test_a_task_that_appears_after_the_check_still_gets_the_explanation(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchor_repository: SqlTaskAnchorRepository,
    ):
        """A task anchored between the guard and the ``DELETE`` trips the
        foreign key, and the caller must still be told what blocks them.

        The race is staged by letting the first look-up miss — a first read that
        does not see a row a later one does is exactly what the window produces
        — while the row is really there for PostgreSQL to refuse the delete on.
        Only a real database exercises the half that matters: the failed
        statement poisons its transaction, so the re-check can only run because
        the delete is wrapped in a SAVEPOINT.
        """
        creating_id = await create_journal(journal_repository, title="Monday Planning")
        due_id = await create_journal(journal_repository, title="Permit Meeting")
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        service = JournalService(
            journal_repo=journal_repository,
            event_publisher=OutboxEventPublisher(async_connection),
            task_anchor_repo=BlindOnFirstLook(task_anchor_repository),
        )

        with pytest.raises(JournalHasAnchoredTasksError) as exc_info:
            await service.delete_journal(due_id, async_connection)

        assert exc_info.value.blocking_tasks[0].action_journal_id == creating_id
        assert (
            await count(async_connection, _COUNT_JOURNAL, {"journal_id": due_id}) == 1
        )
        # The connection is still usable: the SAVEPOINT took the aborted
        # statement with it rather than the whole request's transaction.
        assert (
            await count(async_connection, _COUNT_JOURNAL, {"journal_id": creating_id})
            == 1
        )

    @pytest.mark.asyncio
    async def test_a_blocker_that_vanishes_in_the_window_lets_the_delete_through(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The racing task can lose the race twice.

        It is anchored when the foreign key fires and gone by the time the guard
        looks — cancelled, retargeted or deleted in its turn. Nothing blocks the
        journal any more, so the delete is retried and the caller gets what they
        asked for instead of a 500 about a row that no longer exists. Staged by
        having the second look-up remove the task, which is what the racing
        writer would have done.
        """
        creating_id = await create_journal(journal_repository)
        due_id = await create_journal(journal_repository)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        service = JournalService(
            journal_repo=journal_repository,
            event_publisher=OutboxEventPublisher(async_connection),
            task_anchor_repo=BlockerVanishesOnSecondLook(async_connection, task_id),
        )

        await service.delete_journal(due_id, async_connection)

        assert (
            await count(async_connection, _COUNT_JOURNAL, {"journal_id": due_id}) == 0
        )


class _DeleteGuardDouble(TaskAnchorRepository):
    """Base for the doubles below, which stage a delete and never a merge.

    The port also carries the merge re-point, so a double has to answer for it.
    Refusing loudly is the honest answer: if the delete guard ever reached this,
    a test that looks like it is about deletion would quietly be exercising the
    merge path instead.
    """

    async def repoint_journal_links(
        self, *, source_journal_id: int, target_journal_id: int
    ) -> list[TaskJournalRepointing]:
        raise AssertionError("the delete guard must not re-point task links")


class BlindOnFirstLook(_DeleteGuardDouble):
    """Reports nothing the first time it is asked, then tells the truth."""

    def __init__(self, inner: TaskAnchorRepository) -> None:
        self.inner = inner
        self.looks = 0

    async def find_tasks_anchored_to_journal(
        self, journal_id: int
    ) -> list[BlockingTask]:
        self.looks += 1
        if self.looks == 1:
            return []
        return await self.inner.find_tasks_anchored_to_journal(journal_id)


class BlockerVanishesOnSecondLook(_DeleteGuardDouble):
    """Reports nothing, and clears the real blocker before the second answer.

    Stands in for the racing writer that anchors a task, loses the delete's
    foreign-key check for it, and then removes the task before the guard can
    name it.
    """

    def __init__(self, conn: AsyncConnection, task_id: int) -> None:
        self.conn = conn
        self.task_id = task_id
        self.looks = 0

    async def find_tasks_anchored_to_journal(
        self, journal_id: int
    ) -> list[BlockingTask]:
        self.looks += 1
        if self.looks > 1:
            await self.conn.execute(
                text("DELETE FROM tasks WHERE id = :task_id"), {"task_id": self.task_id}
            )
        return []


@pytest.mark.integration
class TestPermittedDeletes:
    """What the guard must not get in the way of."""

    @pytest.mark.asyncio
    async def test_a_journal_only_mentioned_by_a_task_still_deletes(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        journal_service: JournalService,
    ):
        creating_id = await create_journal(journal_repository)
        due_id = await create_journal(journal_repository)
        mentioned_id = await create_journal(journal_repository, title="Standup")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned_id
        )

        await journal_service.delete_journal(mentioned_id, async_connection)

        assert (
            await count(async_connection, _COUNT_JOURNAL, {"journal_id": mentioned_id})
            == 0
        )
        # The link row went with the journal; the task and both anchors did not.
        assert (
            await count(async_connection, _COUNT_INTERMEDIATE, {"task_id": task_id})
            == 0
        )
        assert await count(async_connection, _COUNT_TASK, {"task_id": task_id}) == 1
        anchors = (
            await async_connection.execute(
                text(
                    "SELECT creating_journal_id, due_journal_id FROM tasks "
                    "WHERE id = :task_id"
                ),
                {"task_id": task_id},
            )
        ).one()
        assert (anchors.creating_journal_id, anchors.due_journal_id) == (
            creating_id,
            due_id,
        )

    @pytest.mark.asyncio
    async def test_a_journal_no_task_touches_still_deletes(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        journal_service: JournalService,
    ):
        journal_id = await create_journal(journal_repository)

        await journal_service.delete_journal(journal_id, async_connection)

        assert (
            await count(async_connection, _COUNT_JOURNAL, {"journal_id": journal_id})
            == 0
        )


@pytest.mark.integration
class TestBlockingQuery:
    """The repository query itself."""

    @pytest.mark.asyncio
    async def test_many_blocking_tasks_come_back_from_one_query_in_id_order(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchor_repository: SqlTaskAnchorRepository,
    ):
        """One query, not one per task — and a stable order, because the error
        message enumerates them."""
        creating_id = await create_journal(journal_repository)
        due_id = await create_journal(journal_repository)
        task_ids = [
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text=f"task {index}",
            )
            for index in range(3)
        ]

        with recorded_statements(async_connection) as statements:
            blockers = await task_anchor_repository.find_tasks_anchored_to_journal(
                due_id
            )

        assert len(statements) == 1
        assert [blocker.task_id for blocker in blockers] == sorted(task_ids)

    @pytest.mark.asyncio
    async def test_a_journal_only_mentioned_by_tasks_has_no_blockers(
        self,
        clean_database: AsyncConnection,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchor_repository: SqlTaskAnchorRepository,
    ):
        creating_id = await create_journal(journal_repository)
        due_id = await create_journal(journal_repository)
        mentioned_id = await create_journal(journal_repository)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned_id
        )

        assert (
            await task_anchor_repository.find_tasks_anchored_to_journal(mentioned_id)
            == []
        )

    @pytest.mark.asyncio
    async def test_the_repository_is_resolved_from_the_container(
        self, clean_database: AsyncConnection, async_connection: AsyncConnection
    ):
        """The guard is only as good as its wiring: a ``JournalService`` built by
        the container has to arrive with a real anchor repository."""
        container = make_task_container(async_connection)
        try:
            async with container() as request_container:
                repository = await request_container.get(TaskAnchorRepository)
                service = await request_container.get(JournalService)

            assert isinstance(repository, SqlTaskAnchorRepository)
            assert service.task_anchor_repo is not None
        finally:
            await container.close()

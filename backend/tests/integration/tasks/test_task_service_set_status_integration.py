"""Integration tests for ``TaskService.set_status`` against real PostgreSQL.

The unit tests own the transition matrix. What only a real database can show is
that the matrix is wired to real rows:

- **the change is written**, read back from the ``tasks`` row rather than from
  the returned object, which would agree with itself whether or not anything
  was persisted;
- **the write happens inside a unit of work**, asserted by observing the open
  transaction *at the moment the repository writes* — see
  :class:`TestTheWriteIsAUnitOfWork` for why reading the row back cannot show
  this and what does;
- **the ``ck_tasks_status`` constraint and the domain enum agree**, since every
  value the service writes has to survive the CHECK;
- **ownership is enforced by the query** — another user's task is unreachable
  and reads exactly like one that never existed, with its row left alone;
- **a refused transition leaves the stored row untouched**, not merely the
  returned object;
- **no journal link is created**, which is the acceptance criterion that
  marking a task done or cancelled requires no journal.

Tasks are seeded through the repository rather than by driving the service,
because reaching *cancelled* through the service is itself one of the behaviours
under test.
"""

import pytest
from core_shared.models.tasks import (
    Task,
    TaskNotFoundError,
    TaskStatus,
    TaskStatusTransitionError,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService
from tests.integration.tasks.task_seeding import (
    COUNT_INTERMEDIATE_JOURNALS,
    OTHER_USER_ID,
    USER_ID,
    count,
    create_journal,
    create_task,
    stored_status,
)

ALLOWED_TRANSITIONS = [
    (TaskStatus.NOT_DONE, TaskStatus.DONE),
    (TaskStatus.NOT_DONE, TaskStatus.CANCELLED),
    (TaskStatus.DONE, TaskStatus.NOT_DONE),
    (TaskStatus.DONE, TaskStatus.CANCELLED),
]

REFUSED_TRANSITIONS = [
    (TaskStatus.CANCELLED, TaskStatus.NOT_DONE),
    (TaskStatus.CANCELLED, TaskStatus.DONE),
]


@pytest.mark.integration
class TestStatusChangesAgainstRealRows:
    """Every permitted transition survives the round trip."""

    @pytest.mark.parametrize(("current", "target"), ALLOWED_TRANSITIONS)
    async def test_the_new_status_is_committed(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        current: TaskStatus,
        target: TaskStatus,
    ):
        """Read back from the database, not from the object the service returned.

        This says the write *happened*; that it happened inside a unit of work
        is a separate question, asserted in :class:`TestTheWriteIsAUnitOfWork`.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            task_repository,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=current,
        )

        updated = await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=target,
            transaction=async_connection,
        )

        assert updated.status == target
        assert await stored_status(async_connection, task_id) == target.value

    async def test_a_lapsed_task_can_still_be_completed(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The future-dated rule is a write-time rule about *setting* a due journal.

        A task whose due journal has passed is lapsed, not invalid. Re-checking
        the journal here would make exactly the tasks a user most needs to close
        the ones they cannot.
        """
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            task_repository,
            creating_journal_id=past_id,
            due_journal_id=past_id,
        )

        updated = await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        assert updated.status == TaskStatus.DONE

    async def test_no_journal_link_is_created(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Marking a task done or cancelled attaches nothing to any journal."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            task_repository,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        for target in (TaskStatus.DONE, TaskStatus.NOT_DONE, TaskStatus.CANCELLED):
            await service.set_status(
                user_id=USER_ID,
                task_id=task_id,
                status=target,
                transaction=async_connection,
            )

        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0
        assert await task_repository.list_intermediate_journal_ids(
            task_id, USER_ID
        ) == ([])

    async def test_asking_for_the_current_status_does_not_touch_the_row(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """``updated_at`` must not move for a change that did not happen.

        The history projection derives a status-change event from a write, so a
        no-op that still wrote would report a change the user never made — and
        the timestamp is the only evidence out here that no write occurred.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            task_repository,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )
        before = await task_repository.find_by_id(task_id, USER_ID)
        assert before is not None

        result = await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.CANCELLED,
            transaction=async_connection,
        )

        after = await task_repository.find_by_id(task_id, USER_ID)
        assert after is not None
        assert after.updated_at == before.updated_at
        assert result.status == TaskStatus.CANCELLED

    async def test_the_anchors_are_unchanged(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The creating journal in particular is immutable, whatever else changes."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            task_repository,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.CANCELLED,
            transaction=async_connection,
        )

        persisted = await task_repository.find_by_id(task_id, USER_ID)
        assert persisted is not None
        assert persisted.creating_journal_id == creating_id
        assert persisted.due_journal_id == due_id


@pytest.mark.integration
class TestTheWriteIsAUnitOfWork:
    """The write is wrapped in a unit of work, and this is how that is provable.

    **Reading the row back after the call does not show it.** The integration
    fixture owns an outer transaction and marks the connection, so
    ``unit_of_work`` stands a SAVEPOINT in for the real commit and every read on
    that same connection sees the write — with or without ``@transactional``.
    Every "read it back afterwards" assertion in this phase is therefore
    evidence that the write *happened*, not that it was committed; deleting the
    decorator leaves them all green.

    What *is* observable is the transaction open around the repository call. The
    unit of work opens a nested transaction on entry, so a repository that looks
    at the connection while it writes can tell whether it is running inside one.
    Remove ``@transactional`` from ``set_status`` and this test — alone — fails.
    """

    async def test_the_repository_writes_inside_an_open_unit_of_work(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            SqlTaskRepository(async_connection),
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        observed: list[bool] = []

        class _ObservingRepository(SqlTaskRepository):
            async def save(self, task: Task) -> Task:
                observed.append(async_connection.get_nested_transaction() is not None)
                return await super().save(task)

        service = TaskService(
            task_repo=_ObservingRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
        )

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        assert observed == [True]

    async def test_no_unit_of_work_is_left_open_afterwards(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The scope closes: in production this is the commit before the response."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            SqlTaskRepository(async_connection),
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        await service.set_status(
            user_id=USER_ID,
            task_id=task_id,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        assert async_connection.get_nested_transaction() is None


@pytest.mark.integration
class TestRefusedTransitionsChangeNothing:
    """Leaving cancelled is retargeting's job, and the row proves it did not happen."""

    @pytest.mark.parametrize(("current", "target"), REFUSED_TRANSITIONS)
    async def test_the_stored_row_is_untouched(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        current: TaskStatus,
        target: TaskStatus,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            task_repository,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=current,
        )

        with pytest.raises(TaskStatusTransitionError):
            await service.set_status(
                user_id=USER_ID,
                task_id=task_id,
                status=target,
                transaction=async_connection,
            )

        assert await stored_status(async_connection, task_id) == current.value


@pytest.mark.integration
class TestOwnershipIsEnforcedByTheQuery:
    """Another user's task is not merely refused — it is invisible."""

    async def test_another_users_task_is_not_found_and_not_changed(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        task_id = await create_task(
            task_repository,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskNotFoundError):
            await service.set_status(
                user_id=USER_ID,
                task_id=task_id,
                status=TaskStatus.DONE,
                transaction=async_connection,
            )

        assert await stored_status(async_connection, task_id) == (
            TaskStatus.NOT_DONE.value
        )

    async def test_an_absent_task_gives_the_same_answer(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
    ):
        """Byte-identical once the ids are stripped, so neither can probe the other."""
        with pytest.raises(TaskNotFoundError) as absent:
            await service.set_status(
                user_id=USER_ID,
                task_id=999_999,
                status=TaskStatus.DONE,
                transaction=async_connection,
            )

        assert str(absent.value) == str(TaskNotFoundError(999_999))

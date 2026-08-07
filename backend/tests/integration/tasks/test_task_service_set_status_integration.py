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

import asyncio

import pytest
from core_shared.models.tasks import (
    Task,
    TaskNotFoundError,
    TaskStatus,
    TaskStatusTransitionError,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

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
    committed_task,
    count,
    create_journal,
    create_task,
    service_on,
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
            async_connection,
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
            async_connection,
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
            async_connection,
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
            async_connection,
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
            async_connection,
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
            async_connection,
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
            async_connection,
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
class TestOverlappingCallsCannotBypassTheMatrix:
    """Two callers racing on one task still obey the refusal rule.

    Raised by review on this phase's pull request. ``set_status`` decides from
    the status it read and then writes that decision back, so with an unlocked
    read both callers see *not done*, both find their transition allowed, and
    the later write wins: cancelling a task while somebody else marks it done
    could leave it **done** and answer both callers ``200`` — the very
    transition the matrix refuses, reached by timing rather than by request.

    The row lock makes the outcome the same whichever call gets there first:

    - done commits, then cancel reads *done* and is allowed → **cancelled**;
    - cancel commits, then done reads *cancelled* and is refused → **cancelled**.

    So *cancelled* is the single correct answer, and the assertion needs no
    knowledge of the interleaving. This test needs two real connections, which
    means committing outside the fixture's rolled-back transaction: it uses its
    own user id and deletes its rows in a ``finally``.
    """

    async def test_the_read_holds_the_row_until_the_writer_commits(
        self,
        async_engine: AsyncEngine,
    ):
        """The lock itself, asserted without depending on any interleaving.

        This is the deterministic half of the pair. A second reader-for-update
        **must block** while the first transaction is open, and must see the
        committed status once it closes — which is exactly what stops the second
        caller from deciding against a status that is already stale. Drop the
        ``FOR NO KEY UPDATE`` and the blocked read returns immediately, so this
        test fails every time rather than most times.
        """
        async with committed_task(async_engine) as (user_id, task_id, _):
            async with (
                async_engine.connect() as holder,
                async_engine.connect() as waiter,
            ):
                await holder.begin()
                held = await SqlTaskRepository(holder).find_by_id_for_update(
                    task_id, user_id
                )
                assert held is not None

                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(
                        SqlTaskRepository(waiter).find_by_id_for_update(
                            task_id, user_id
                        ),
                        timeout=1.0,
                    )

                await holder.execute(
                    text("UPDATE tasks SET status = 'cancelled' WHERE id = :task_id"),
                    {"task_id": task_id},
                )
                await holder.commit()

            async with async_engine.connect() as after:
                unblocked = await SqlTaskRepository(after).find_by_id_for_update(
                    task_id, user_id
                )
                assert unblocked is not None
                assert unblocked.status == TaskStatus.CANCELLED

    async def test_a_done_that_overlaps_a_cancel_is_refused(
        self,
        async_engine: AsyncEngine,
        user_settings_repository: SqlUserSettingsRepository,
    ):
        """The whole service path, overlapping — with one fixed outcome.

        The two calls really do overlap: the *done* starts while the cancel's
        unit of work is still open and holding the row, which is the only state
        in which the bug can appear. What is not left to chance is which one
        gets there first. An earlier version started both with ``gather`` and
        accepted either result for the ``done`` call, since the scheduler
        decided it — two outcomes for one test, which the repository's
        determinism rule forbids and review rightly caught.

        So the cancel signals once its read has the row, and only then is the
        done started. Every outcome asserted here is now fixed: the cancel
        succeeds, the done blocks on the read, sees ``cancelled``, and is
        refused. Nothing in this test is left for the scheduler to decide.

        **What it is not** is a reliable detector of the lock's absence, and the
        claim that it is was wrong when first written here. Measured against the
        unlocked read, it fails roughly one run in three: the done's read can
        land *after* the cancel has committed, in which case it reads
        ``cancelled`` and is refused for the right reason by accident. Making it
        fail every time needs the done to have read *before* the cancel commits,
        and a barrier for that deadlocks against the very lock it is testing.
        The regression guarantee therefore lives in the two tests that do fail
        every time: :meth:`test_the_read_holds_the_row_until_the_writer_commits`
        above, and the unit test that ``set_status`` uses the locking read at
        all. This one is here because it is the only test that exercises the
        whole path — two units of work, two connections, one row.

        The signal is sent from **both** read methods on purpose. Hanging it off
        the locking read alone would mean that removing the lock stopped the
        signal ever firing, and the test would hang on the wait instead of
        failing — a regression that times CI out rather than reporting itself.
        The wait is bounded for the same reason.
        """
        async with committed_task(async_engine) as (user_id, task_id, _):
            holds_the_row = asyncio.Event()

            class _SignallingRepository(SqlTaskRepository):
                async def find_by_id_for_update(
                    self, task_id: int, user_id: str
                ) -> Task | None:
                    task = await super().find_by_id_for_update(task_id, user_id)
                    holds_the_row.set()
                    return task

                async def find_by_id(self, task_id: int, user_id: str) -> Task | None:
                    task = await super().find_by_id(task_id, user_id)
                    holds_the_row.set()
                    return task

            async with (
                async_engine.connect() as first,
                async_engine.connect() as second,
            ):

                async def _cancel(connection: AsyncConnection = first) -> Task:
                    return await service_on(
                        connection,
                        user_settings_repository,
                        repo=_SignallingRepository,
                    ).set_status(
                        user_id=user_id,
                        task_id=task_id,
                        status=TaskStatus.CANCELLED,
                        transaction=connection,
                    )

                async def _done(connection: AsyncConnection = second) -> Task:
                    return await service_on(
                        connection, user_settings_repository
                    ).set_status(
                        user_id=user_id,
                        task_id=task_id,
                        status=TaskStatus.DONE,
                        transaction=connection,
                    )

                cancel = asyncio.create_task(_cancel())
                await asyncio.wait_for(holds_the_row.wait(), timeout=10.0)

                done = asyncio.create_task(_done())

                cancelled = await cancel
                with pytest.raises(TaskStatusTransitionError) as refused:
                    await done

            assert cancelled.status == TaskStatus.CANCELLED
            assert refused.value.current_status == TaskStatus.CANCELLED
            assert refused.value.target_status == TaskStatus.DONE

            async with async_engine.connect() as check:
                assert await stored_status(check, task_id) == (
                    TaskStatus.CANCELLED.value
                )


@pytest.mark.integration
class TestRefusedTransitionsChangeNothing:
    """Leaving cancelled is retargeting's job, and the row proves it did not happen."""

    @pytest.mark.parametrize(("current", "target"), REFUSED_TRANSITIONS)
    async def test_the_stored_row_is_untouched(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        current: TaskStatus,
        target: TaskStatus,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
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
            async_connection,
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

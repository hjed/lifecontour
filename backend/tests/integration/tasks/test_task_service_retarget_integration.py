"""Integration tests for ``TaskService.retarget_due_journal`` against real PostgreSQL.

The unit tests own the rules. What only a real database can show is that they
are wired to real rows and real journals:

- **the retarget is written** — the new due journal and *not done* read back from
  the ``tasks`` row rather than from the object the service returned, which would
  agree with itself whether or not anything was persisted;
- **the automatic link is a real row** in ``task_intermediate_journals``, and
  **de-duplicates against the live primary key** rather than against a mock that
  was told to return ``False``;
- **the creating anchor never moves**, asserted on the stored column;
- **the journal rules are revalidated against real journals** — a past-dated one
  and another user's are both refused, whatever the task's status;
- **the write happens inside a unit of work**, asserted by observing the open
  transaction *at the moment the repository writes* (see
  :class:`TestTheWriteIsAUnitOfWork` for why reading the row back cannot show
  this);
- **the locking read closes the acknowledgement hole** — a task marked done by
  an overlapping caller cannot be reopened without the acknowledgement.

Tasks are seeded through rows rather than by driving the service, because
reaching *cancelled*, *done* and *lapsed* is exactly the starting position under
test and creation can only produce a not-done task due in a future journal.
"""

import asyncio

import pytest
from core_shared.models.tasks import (
    Task,
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskNotFoundError,
    TaskReopenNotAcknowledgedError,
    TaskStatus,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.tasks.task_seeding import (
    COUNT_INTERMEDIATE_JOURNALS,
    OTHER_USER_ID,
    USER_ID,
    committed_task,
    count,
    create_journal,
    create_task,
    intermediate_journal_ids,
    link_intermediate_journal,
    service_on,
    stored_anchors,
    stored_status,
)

ALL_STATUSES = list(TaskStatus)

# Only *done* needs an acknowledgement, so a parametrised test that is about
# something else can ask for the right one instead of branching.
ACKNOWLEDGEMENT_FOR = {
    TaskStatus.NOT_DONE: False,
    TaskStatus.CANCELLED: False,
    TaskStatus.DONE: True,
}


async def retarget(
    service: TaskService,
    connection: AsyncConnection,
    *,
    task_id: int,
    due_journal_id: int,
    user_id: str = USER_ID,
    acknowledge_reopen: bool = False,
) -> Task:
    """Call ``retarget_due_journal`` with the ordinary arguments."""
    return await service.retarget_due_journal(
        user_id=user_id,
        task_id=task_id,
        due_journal_id=due_journal_id,
        acknowledge_reopen=acknowledge_reopen,
        transaction=connection,
    )


@pytest.mark.integration
class TestRetargetAgainstRealRows:
    """The round trip, for each status a task can start in."""

    @pytest.mark.parametrize("current", ALL_STATUSES)
    async def test_the_new_due_journal_and_not_done_are_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        current: TaskStatus,
    ):
        """Read back from the ``tasks`` row, not from the returned object."""
        creating_id, due_id = task_anchors
        target_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=current,
        )

        updated = await retarget(
            service,
            async_connection,
            task_id=task_id,
            due_journal_id=target_id,
            acknowledge_reopen=ACKNOWLEDGEMENT_FOR[current],
        )

        assert updated.due_journal_id == target_id
        assert updated.status == TaskStatus.NOT_DONE
        assert await stored_anchors(async_connection, task_id) == (
            creating_id,
            target_id,
        )
        assert await stored_status(async_connection, task_id) == (
            TaskStatus.NOT_DONE.value
        )

    async def test_the_previous_due_journal_becomes_a_real_link_row(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The model's one automatic link, as a row rather than as a mock call."""
        creating_id, due_id = task_anchors
        target_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        await retarget(
            service, async_connection, task_id=task_id, due_journal_id=target_id
        )

        assert await intermediate_journal_ids(async_connection, task_id) == [due_id]
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 1

    async def test_the_creating_journal_and_text_are_untouched(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The creating anchor is set once and never changes — on the stored column.

        ``created_at`` goes with it: when the commitment arose does not change
        because when it is due did.
        """
        creating_id, due_id = task_anchors
        target_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="return Sarah's book",
        )
        before = await task_repository.find_by_id(task_id, USER_ID)
        assert before is not None

        await retarget(
            service, async_connection, task_id=task_id, due_journal_id=target_id
        )

        after = await task_repository.find_by_id(task_id, USER_ID)
        assert after is not None
        assert after.creating_journal_id == creating_id
        assert after.text == "return Sarah's book"
        assert after.created_at == before.created_at

    async def test_a_lapsed_task_is_resurrected(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The journal it is *leaving* being in the past is not re-judged.

        A lapsed task — due in a journal that has passed, still not done —
        disappears from the dashboard and is brought back by exactly this
        operation, so applying the future-dated rule to the old journal would
        make the tasks a user most needs to resurrect the ones they cannot.
        """
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        target_id = await create_journal(
            journal_repository, title="Next week", days_offset=7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=past_id,
            due_journal_id=past_id,
        )

        updated = await retarget(
            service, async_connection, task_id=task_id, due_journal_id=target_id
        )

        assert updated.due_journal_id == target_id
        assert updated.status == TaskStatus.NOT_DONE
        assert await intermediate_journal_ids(async_connection, task_id) == [past_id]

    async def test_a_cancelled_task_is_reopened_without_acknowledgement(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Retargeting *is* the documented way out of cancelled.

        ``set_status`` refuses to leave cancelled and names this operation in
        its refusal, so this is the path that refusal points at.
        """
        creating_id, due_id = task_anchors
        target_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        await retarget(
            service, async_connection, task_id=task_id, due_journal_id=target_id
        )

        assert await stored_status(async_connection, task_id) == (
            TaskStatus.NOT_DONE.value
        )


@pytest.mark.integration
class TestTheAutomaticLinkIsDeDuplicated:
    """Against the live primary key on ``task_intermediate_journals``."""

    async def test_a_journal_already_linked_is_not_linked_twice(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A raw duplicate insert would violate the composite primary key.

        So this passing at all is the de-duplication: the service either asks
        the repository for an idempotent add or it raises.
        """
        creating_id, due_id = task_anchors
        target_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=due_id
        )

        await retarget(
            service, async_connection, task_id=task_id, due_journal_id=target_id
        )

        assert await intermediate_journal_ids(async_connection, task_id) == [due_id]

    async def test_repeated_deferral_accumulates_the_trail(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Every journal a repeatedly-deferred task passed through keeps it.

        The last hop moves the task back onto a journal that is *already* an
        intermediate link, which is the shape that makes the automatic link
        collide with itself — and it still leaves one row per journal.
        """
        creating_id, first_due = task_anchors
        second_due = await create_journal(
            journal_repository, title="Fortnight", days_offset=14
        )
        third_due = await create_journal(
            journal_repository, title="Three weeks", days_offset=21
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=first_due,
        )

        for target in (second_due, first_due, third_due):
            await retarget(
                service, async_connection, task_id=task_id, due_journal_id=target
            )

        assert sorted(await intermediate_journal_ids(async_connection, task_id)) == (
            sorted([first_due, second_due])
        )
        assert await stored_anchors(async_connection, task_id) == (
            creating_id,
            third_due,
        )


@pytest.mark.integration
class TestReopeningADoneTaskNeedsAcknowledgement:
    """The stored row is what proves the refusal wrote nothing."""

    async def test_without_acknowledgement_nothing_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Not the status, not the due anchor, and not the automatic link."""
        creating_id, due_id = task_anchors
        target_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        with pytest.raises(TaskReopenNotAcknowledgedError):
            await retarget(
                service, async_connection, task_id=task_id, due_journal_id=target_id
            )

        assert await stored_status(async_connection, task_id) == TaskStatus.DONE.value
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_with_acknowledgement_the_row_is_reopened(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """And the automatic link appears along with it."""
        creating_id, due_id = task_anchors
        target_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        await retarget(
            service,
            async_connection,
            task_id=task_id,
            due_journal_id=target_id,
            acknowledge_reopen=True,
        )

        assert await stored_status(async_connection, task_id) == (
            TaskStatus.NOT_DONE.value
        )
        assert await intermediate_journal_ids(async_connection, task_id) == [due_id]


@pytest.mark.integration
class TestTheDueJournalIsRevalidated:
    """Invariant 4 and the ownership rule apply at *every* moment a due journal is set."""

    @pytest.mark.parametrize("current", ALL_STATUSES)
    async def test_a_past_dated_journal_is_refused_and_nothing_changes(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        current: TaskStatus,
    ):
        """Not even a cancelled task may be reopened onto a journal that has passed."""
        creating_id, due_id = task_anchors
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=current,
        )

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await retarget(
                service,
                async_connection,
                task_id=task_id,
                due_journal_id=past_id,
                acknowledge_reopen=ACKNOWLEDGEMENT_FOR[current],
            )

        assert exc_info.value.journal_id == past_id
        assert await stored_status(async_connection, task_id) == current.value
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_another_users_journal_cannot_become_the_due_journal(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """It exists and it is future-dated; it is simply not this user's.

        The read is owner-scoped, so it is refused exactly as an absent journal
        is — the error cannot say which, and so cannot be used to probe.
        """
        creating_id, due_id = task_anchors
        foreign_id = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=14,
            user_id=OTHER_USER_ID,
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as foreign:
            await retarget(
                service, async_connection, task_id=task_id, due_journal_id=foreign_id
            )

        with pytest.raises(TaskAnchorJournalNotFoundError) as absent:
            await retarget(
                service, async_connection, task_id=task_id, due_journal_id=999_999
            )

        assert foreign.value.anchor == "due"
        assert str(foreign.value).replace(str(foreign_id), "") == (
            str(absent.value).replace("999999", "")
        )
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)


@pytest.mark.integration
class TestOwnershipIsEnforcedByTheQuery:
    """Another user's task is not merely refused — it is invisible."""

    async def test_another_users_task_is_not_found_and_not_changed(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        _, target_id = task_anchors
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
            await retarget(
                service, async_connection, task_id=task_id, due_journal_id=target_id
            )

        assert await stored_anchors(async_connection, task_id) == (
            foreign_journal,
            foreign_journal,
        )
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_an_absent_task_gives_the_same_answer(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Byte-identical once the ids are stripped, so neither can probe the other."""
        _, target_id = task_anchors

        with pytest.raises(TaskNotFoundError) as absent:
            await retarget(
                service, async_connection, task_id=999_999, due_journal_id=target_id
            )

        assert str(absent.value) == str(TaskNotFoundError(999_999))


@pytest.mark.integration
class TestRetargetingOntoTheCurrentDueJournal:
    """Asking for the journal a task is already due in is not a retarget."""

    async def test_does_not_touch_the_row(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Nothing is written for a change that did not happen.

        The task here is **lapsed**, which is the case that shows the no-op is a
        no-op rather than a re-validation: were the due journal re-judged, a
        journal already in the past would be refused even though the caller
        asked for the one the task already has.

        **The evidence is the status, not ``updated_at``.** This test previously
        compared timestamps, and that assertion could not fail: the row is
        stamped with ``now()``, which in PostgreSQL is the *transaction*
        timestamp, and the savepoint fixture runs the whole test inside one — so
        a rewrite lands exactly the value the insert did. Found in ITER18-001
        Phase 8 by probing rather than by reading: a test asserting the timestamp
        **does** move on a real retarget fails. A *cancelled* task is used
        instead, because every path but the no-op would have written *not done*
        over it, which is an assertion that can fail.
        """
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=past_id,
            due_journal_id=past_id,
            status=TaskStatus.CANCELLED,
        )

        result = await retarget(
            service, async_connection, task_id=task_id, due_journal_id=past_id
        )

        after = await task_repository.find_by_id(task_id, USER_ID)
        assert after is not None
        assert after.status == TaskStatus.CANCELLED
        assert (after.creating_journal_id, after.due_journal_id) == (past_id, past_id)
        assert result.due_journal_id == past_id
        assert result.status == TaskStatus.CANCELLED
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0


@pytest.mark.integration
class TestTheWriteIsAUnitOfWork:
    """Both writes are wrapped in one unit of work, and this is how that is provable.

    **Reading the row back after the call does not show it.** The integration
    fixture owns an outer transaction and marks the connection, so
    ``unit_of_work`` stands a SAVEPOINT in for the real commit and every read on
    that same connection sees the write — with or without ``@transactional``.
    Every "read it back afterwards" assertion in this file is therefore evidence
    that the write *happened*, not that it was committed.

    What *is* observable is the transaction open around the repository calls.
    Remove ``@transactional`` from ``retarget_due_journal`` and this test —
    alone — fails. It matters more here than on a status change because a
    retarget writes **twice**: the link row and the task row must land together,
    or a task can end up pointing at a new journal with no record of the old one.
    """

    async def test_both_writes_happen_inside_one_open_unit_of_work(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        target_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
        observed: list[str] = []

        class _ObservingRepository(SqlTaskRepository):
            def _note(self, what: str) -> None:
                if async_connection.get_nested_transaction() is not None:
                    observed.append(what)

            async def save(self, task: Task) -> Task:
                self._note("save")
                return await super().save(task)

            async def add_intermediate_journal(
                self, task_id: int, journal_id: int, user_id: str
            ) -> bool:
                self._note("link")
                return await super().add_intermediate_journal(
                    task_id, journal_id, user_id
                )

        service = TaskService(
            task_repo=_ObservingRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
            event_publisher=OutboxEventPublisher(async_connection),
        )

        await retarget(
            service, async_connection, task_id=task_id, due_journal_id=target_id
        )

        # Sorted rather than ordered: which of the two writes goes first is an
        # implementation choice with no observable difference inside one unit of
        # work, and pinning it here would make a harmless reordering a failure.
        assert sorted(observed) == ["link", "save"]

    async def test_no_unit_of_work_is_left_open_afterwards(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The scope closes: in production this is the commit before the response."""
        creating_id, due_id = task_anchors
        target_id = await create_journal(
            journal_repository, title="Next fortnight", days_offset=14
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        await retarget(
            service, async_connection, task_id=task_id, due_journal_id=target_id
        )

        assert async_connection.get_nested_transaction() is None


@pytest.mark.integration
class TestOverlappingCallsCannotBypassTheAcknowledgement:
    """A task marked done underneath a retarget is still not reopened silently.

    ``retarget_due_journal`` decides from the status it read — whether an
    acknowledgement was required — and then writes that decision back. With an
    unlocked read, a retarget that started while the task was *not done* would
    still be running when somebody marks it **done**, and would go on to reopen
    it with no acknowledgement at all: the rule this phase exists to enforce,
    bypassed by timing rather than by request.

    The retarget is started only once the done's unit of work already holds the
    row, so with the lock there is exactly one possible outcome: the retarget
    blocks on its read, sees *done* once the done commits, and is refused. The
    test asserts that one outcome and not "either of two".

    **It is deliberately not the regression detector**, and the same claim was
    wrong when Phase 6 first made it about its own overlapping test. Measured
    against the unlocked read — ``find_by_id`` substituted in
    ``retarget_due_journal`` — this test still passes: the retarget's read lands
    after the done has committed anyway, and it is refused for the right reason
    by accident. Making it fail every time would need the retarget to read
    *before* the done commits, and a barrier for that deadlocks against the very
    lock under test. The every-time guarantee therefore lives in the unit test
    that ``retarget_due_journal`` uses the locking read at all (37 of its tests
    fail under that substitution) and in Phase 6's
    ``test_the_read_holds_the_row_until_the_writer_commits``, which pins the
    lock's behaviour on the repository itself. This test is here because it is
    the only one that exercises the whole path: two units of work, two
    connections, one row.

    It needs two real connections, which means committing outside the fixture's
    rolled-back transaction: ``committed_task`` uses its own user id and deletes
    its rows in a ``finally``.
    """

    async def test_a_retarget_overlapping_a_done_is_refused(
        self,
        async_engine: AsyncEngine,
        user_settings_repository: SqlUserSettingsRepository,
    ):
        async with committed_task(async_engine, journal_offsets=(7, 14)) as (
            user_id,
            task_id,
            journal_ids,
        ):
            _, target_id = journal_ids
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

                async def _mark_done(connection: AsyncConnection = first) -> Task:
                    return await service_on(
                        connection,
                        user_settings_repository,
                        repo=_SignallingRepository,
                    ).set_status(
                        user_id=user_id,
                        task_id=task_id,
                        status=TaskStatus.DONE,
                        transaction=connection,
                    )

                async def _retarget(connection: AsyncConnection = second) -> Task:
                    return await service_on(
                        connection, user_settings_repository
                    ).retarget_due_journal(
                        user_id=user_id,
                        task_id=task_id,
                        due_journal_id=target_id,
                        acknowledge_reopen=False,
                        transaction=connection,
                    )

                done = asyncio.create_task(_mark_done())
                # The signal is sent from **both** read methods on purpose:
                # hanging it off the locking read alone would mean that removing
                # the lock stopped the signal firing, and this test would hang
                # rather than fail. The wait is bounded for the same reason.
                await asyncio.wait_for(holds_the_row.wait(), timeout=10.0)

                retargeting = asyncio.create_task(_retarget())

                completed = await done
                with pytest.raises(TaskReopenNotAcknowledgedError):
                    await retargeting

            assert completed.status == TaskStatus.DONE

            async with async_engine.connect() as check:
                assert await stored_status(check, task_id) == TaskStatus.DONE.value
                assert await intermediate_journal_ids(check, task_id) == []

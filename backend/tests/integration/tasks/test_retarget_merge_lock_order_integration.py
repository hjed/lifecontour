"""A retarget and a journal merge, overlapping, against real PostgreSQL.

The two operations touch the same two kinds of row. Until ITER18-002 Phase 6
they took them in opposite orders:

===================================================  ==================  ==================
operation                                            first               then
===================================================  ==================  ==================
``TaskService.retarget_due_journal``                 the **task** row    the **journal** rows
``TaskAnchorRepository.repoint_journal_links``       the **journal**     the **task** rows
and ``JournalMergeService``                          rows
===================================================  ==================  ==================

so retargeting a task while a merge absorbed the journal it was due in
deadlocked: PostgreSQL aborted one side and that caller saw a raw database
error. It is reachable whenever a merge's source is a task's current or incoming
due journal, which is exactly the pair a retarget touches.

**Only a real database can show this.** A deadlock is a property of the lock
manager, not of the code's shape, and neither side half-applies — so there is no
row a functional assertion could look at afterwards to tell the two orderings
apart. It also needs **two real connections**, which the savepoint fixture
cannot give: its outer transaction is invisible to every other connection and is
rolled back at teardown. ``committed_task`` commits the rows for real under a
one-off user id and deletes them in a ``finally``.

**Both interleavings are exercised**, because a lock order is only a guarantee
if it holds whichever side gets there first, and the two are not symmetrical:

- *retarget first* — the merge queues on the journal locks the retarget already
  holds, and runs once it commits;
- *merge first* — the retarget queues on the merge's, and finds when it resumes
  that the journal it was leaving has been **absorbed and deleted**. That is the
  re-verification path, end to end: the peek that named the journals to lock is
  no longer true, and the locking read is what says so.

Each side is driven through its real service — ``JournalMergeService`` on one
connection, ``TaskService`` on the other — because what is under test is the
lock sequence of the whole operation, including the journal writes and the
delete the merge ends with. Every wait is bounded, so a regression fails in
seconds rather than hanging the suite.
"""

import asyncio

import pytest
from core_shared.models.journals import Journal
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.services.task_journal_merge_service import TaskJournalMergeService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.tasks.task_seeding import (
    committed_task,
    intermediate_journal_ids,
    service_on,
    stored_anchors,
)

# Long enough that a slow container is not mistaken for a deadlock, short enough
# that a genuine one is reported rather than waited on.
TIMEOUT = 20.0


def merge_service_on(
    connection: AsyncConnection,
    anchor_repo: type[SqlTaskAnchorRepository] = SqlTaskAnchorRepository,
) -> JournalMergeService:
    """A ``JournalMergeService`` over real adapters on ``connection``.

    The merge fixtures elsewhere are bound to the test's single savepoint
    connection; an overlap needs one service per real connection. ``anchor_repo``
    lets a test signal from inside the re-point, which is where the merge takes
    the journal locks.
    """
    return JournalMergeService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        task_merge_service=TaskJournalMergeService(
            task_anchor_repo=anchor_repo(connection),
            event_publisher=OutboxEventPublisher(connection),
        ),
    )


def journal_repository_signalling_around_the_lock(
    *,
    before: asyncio.Event | None = None,
    after: asyncio.Event | None = None,
    resume: asyncio.Event | None = None,
) -> type[SqlJournalRepository]:
    """A journal repository that says where the retarget is relative to its locks.

    Which side of the call the signal comes from is the whole of the setup, and
    the two tests need different sides. ``before`` fires with the request about
    to be made, so the other operation can be inside its own critical section
    while this one queues on it. ``after`` fires with the locks actually held,
    which is what lets a test start the merge knowing it must wait. ``resume``
    holds the retarget where it is until the test releases it.
    """

    class _SignallingJournalRepository(SqlJournalRepository):
        async def find_and_lock_by_ids_for_user(
            self, user_id: str, journal_ids: list[int]
        ) -> list[Journal]:
            if before is not None:
                before.set()
            found = await super().find_and_lock_by_ids_for_user(user_id, journal_ids)
            if after is not None:
                after.set()
            if resume is not None:
                await resume.wait()
            return found

    return _SignallingJournalRepository


def anchor_repository_signalling_around_the_lock(
    *,
    before: asyncio.Event | None = None,
    after: asyncio.Event | None = None,
    resume: asyncio.Event | None = None,
) -> type[SqlTaskAnchorRepository]:
    """The merge's counterpart to the journal repository above.

    The signal has to come from *inside* ``repoint_journal_links``: the locks are
    taken as its first act and released only when the merge's unit of work
    commits, so anywhere outside it is either too early to have them or too late
    to still be holding them. ``before`` is the only signal available to the side
    that is about to **block** — once it is waiting on a lock it cannot report
    anything — so it is what the other operation waits on to know the merge is in
    flight rather than merely scheduled.
    """

    class _SignallingAnchorRepository(SqlTaskAnchorRepository):
        async def _lock_journals(
            self, source_journal_id: int, target_journal_id: int
        ) -> None:
            if before is not None:
                before.set()
            await super()._lock_journals(source_journal_id, target_journal_id)
            if after is not None:
                after.set()
            if resume is not None:
                await resume.wait()

    return _SignallingAnchorRepository


@pytest.mark.integration
class TestARetargetOverlappingAMergeOfItsDueJournal:
    """Neither ordering deadlocks, and both leave the same rows behind.

    The task is **due** in ``absorbed`` and **created** in a fourth journal the
    merge never touches. That separation is deliberate: sharing the two anchors
    would make the merge move both, and the outcome would then differ between the
    two interleavings for a reason that has nothing to do with locking — a
    retarget that ran first leaves an intermediate link the merge's last
    statement then drops as redundant with the creating anchor. Isolating the due
    anchor keeps the assertion about the pair of operations rather than about
    that rule.

    The merge absorbs ``absorbed`` into ``survivor``; the retarget moves the due
    journal onto ``target``. Whichever runs first, the task ends up still created
    where it was, due in ``target``, with ``survivor`` on its trail — the merge
    moved the link, the retarget moved the deadline, and neither was refused,
    lost, or aborted.
    """

    @staticmethod
    async def _assert_settled(
        async_engine: AsyncEngine,
        *,
        task_id: int,
        creating_id: int,
        survivor_id: int,
        target_id: int,
    ) -> None:
        """Both operations applied in full, read back from the rows themselves."""
        async with async_engine.connect() as check:
            assert await stored_anchors(check, task_id) == (creating_id, target_id)
            assert await intermediate_journal_ids(check, task_id) == [survivor_id]

    async def test_the_merge_queues_behind_a_retarget_that_started_first(
        self,
        async_engine: AsyncEngine,
        user_settings_repository: SqlUserSettingsRepository,
    ):
        """The retarget holds the journal locks; the merge waits and then runs.

        Under the old ordering the retarget held the **task** row at this point
        and had not yet touched a journal, so the merge sailed through its own
        journal locks and then blocked on the task row — while the retarget
        blocked on the journal it was about to link. That is the cycle; here
        there is only a queue.
        """
        async with committed_task(
            async_engine, journal_offsets=(7, 14, 21, 28), creating_index=3
        ) as (user_id, task_id, journal_ids):
            absorbed_id, survivor_id, target_id, creating_id = journal_ids
            retarget_holds_journals = asyncio.Event()
            merge_started = asyncio.Event()

            async with (
                async_engine.connect() as retarget_conn,
                async_engine.connect() as merge_conn,
            ):
                # The retarget is released once the merge is under way, so the
                # two are genuinely in flight together rather than in sequence.
                async def _retarget() -> None:
                    await service_on(
                        retarget_conn,
                        user_settings_repository,
                        journal_repo=journal_repository_signalling_around_the_lock(
                            after=retarget_holds_journals, resume=merge_started
                        ),
                    ).retarget_due_journal(
                        user_id=user_id,
                        task_id=task_id,
                        due_journal_id=target_id,
                        transaction=retarget_conn,
                    )

                async def _merge() -> None:
                    await merge_service_on(
                        merge_conn,
                        anchor_repo=anchor_repository_signalling_around_the_lock(
                            before=merge_started
                        ),
                    ).merge_journals(
                        target_id=survivor_id,
                        source_id=absorbed_id,
                        transaction=merge_conn,
                    )

                retargeting = asyncio.create_task(_retarget())
                await asyncio.wait_for(retarget_holds_journals.wait(), timeout=TIMEOUT)

                merging = asyncio.create_task(_merge())
                # Released by the merge itself, from immediately before its lock
                # request — not by this line creating the task, which would let
                # the retarget commit before the merge had run a single step and
                # turn an overlap into a sequence.
                await asyncio.wait_for(merge_started.wait(), timeout=TIMEOUT)

                await asyncio.wait_for(
                    asyncio.gather(retargeting, merging), timeout=TIMEOUT
                )

            await self._assert_settled(
                async_engine,
                task_id=task_id,
                creating_id=creating_id,
                survivor_id=survivor_id,
                target_id=target_id,
            )

    async def test_a_retarget_queues_behind_a_merge_that_started_first(
        self,
        async_engine: AsyncEngine,
        user_settings_repository: SqlUserSettingsRepository,
    ):
        """And re-verifies, because the journal it was leaving no longer exists.

        The merge holds both journal locks and has not committed, so the
        retarget's peek still reports the absorbed journal while its locking read
        queues behind the merge. By the time it resumes the anchor has moved onto
        the survivor and the absorbed journal has been deleted — so the journal
        the retarget links and announces has to come from the read it took under
        the task's own lock, not from the peek that named the locks.
        """
        async with committed_task(
            async_engine, journal_offsets=(7, 14, 21, 28), creating_index=3
        ) as (user_id, task_id, journal_ids):
            absorbed_id, survivor_id, target_id, creating_id = journal_ids
            merge_holds_journals = asyncio.Event()
            retarget_at_the_lock = asyncio.Event()

            async with (
                async_engine.connect() as retarget_conn,
                async_engine.connect() as merge_conn,
            ):

                async def _merge() -> None:
                    await merge_service_on(
                        merge_conn,
                        anchor_repo=anchor_repository_signalling_around_the_lock(
                            after=merge_holds_journals, resume=retarget_at_the_lock
                        ),
                    ).merge_journals(
                        target_id=survivor_id,
                        source_id=absorbed_id,
                        transaction=merge_conn,
                    )

                async def _retarget() -> None:
                    await service_on(
                        retarget_conn,
                        user_settings_repository,
                        journal_repo=journal_repository_signalling_around_the_lock(
                            before=retarget_at_the_lock
                        ),
                    ).retarget_due_journal(
                        user_id=user_id,
                        task_id=task_id,
                        due_journal_id=target_id,
                        transaction=retarget_conn,
                    )

                merging = asyncio.create_task(_merge())
                await asyncio.wait_for(merge_holds_journals.wait(), timeout=TIMEOUT)

                retargeting = asyncio.create_task(_retarget())

                await asyncio.wait_for(
                    asyncio.gather(merging, retargeting), timeout=TIMEOUT
                )

            await self._assert_settled(
                async_engine,
                task_id=task_id,
                creating_id=creating_id,
                survivor_id=survivor_id,
                target_id=target_id,
            )

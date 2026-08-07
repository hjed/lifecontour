"""Integration tests for ``TaskService.update_task`` and ``delete_task``.

The unit tests own the rules. What only a real database can show:

- **the edit is written**, read back from the ``tasks`` row rather than from the
  returned object, which agrees with itself either way;
- **the write happens inside a unit of work**, observed at the moment the
  repository writes — reading the row back afterwards cannot show this, for the
  reason :class:`TestTheWritesAreUnitsOfWork` sets out;
- **deletion is a cascade, not a sweep.** The service issues one statement; the
  link rows go because migration 0105's foreign keys say so, and the journals
  and contacts they pointed at stay. That is a property of the *schema*, and the
  only place it can be asserted is against one;
- **ownership is enforced by the statement** — another user's task is unreachable
  and reads exactly like one that never existed, with its row left alone.

Tasks are seeded through direct inserts rather than by driving the service,
because the states this file needs — cancelled, and due in a journal that has
since passed — are not reachable through a creation path that only makes
not-done tasks due in future journals.

**The row lock is not re-tested here.** ``update_task`` inherits Phase 6's
``FOR NO KEY UPDATE`` read, and ``set_status`` now delegates to it — so the
two-connection overlapping-call test in
``test_task_service_set_status_integration.py`` already exercises *this* code
path end to end. That the locking read is the one used is pinned per-method in
the unit tests, where it is a cheap assertion rather than a second copy of the
committed-rows-and-barriers machinery.
"""

import pytest
from core_shared.models.tasks import (
    Task,
    TaskNotFoundError,
    TaskStatus,
    TaskValidationError,
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
    COUNT_CONTACT_LINKS,
    COUNT_INTERMEDIATE_JOURNALS,
    COUNT_TASKS,
    OTHER_USER_ID,
    USER_ID,
    backdate_updated_at,
    count,
    create_contact,
    create_journal,
    create_task,
    link_contact,
    link_intermediate_journal,
    stored_status,
    stored_text,
    task_exists,
)

REWORDED = "return Sarah's book and the DVD"


async def _seed_linked_task(
    conn: AsyncConnection,
    journal_repository: SqlJournalRepository,
    *,
    user_id: str = USER_ID,
) -> tuple[int, int, int]:
    """A task with one intermediate journal link and one contact link.

    Returns the task, the intermediate journal and the contact, so a deletion
    test can assert that the two survivors are still there afterwards.
    """
    creating_id = await create_journal(
        journal_repository, title="Where it arose", days_offset=1, user_id=user_id
    )
    due_id = await create_journal(
        journal_repository, title="Where it is due", days_offset=7, user_id=user_id
    )
    mentioned_id = await create_journal(
        journal_repository, title="Where it came up", days_offset=3, user_id=user_id
    )
    task_id = await create_task(
        conn,
        creating_journal_id=creating_id,
        due_journal_id=due_id,
        user_id=user_id,
    )
    contact_id = await create_contact(conn)
    await link_intermediate_journal(conn, task_id=task_id, journal_id=mentioned_id)
    await link_contact(conn, task_id=task_id, contact_id=contact_id)
    return task_id, mentioned_id, contact_id


@pytest.mark.integration
class TestTextIsEditableInAnyStatus:
    """The specification's "at any time, in any status", against real rows."""

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_the_new_text_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """Read back from the database, not from the object the service returned."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )

        updated = await service.update_task(
            user_id=USER_ID,
            task_id=task_id,
            text=REWORDED,
            transaction=async_connection,
        )

        assert updated.text == REWORDED
        assert await stored_text(async_connection, task_id) == REWORDED
        assert await stored_status(async_connection, task_id) == status.value

    async def test_a_lapsed_task_can_still_be_reworded(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The due journal is not re-read, so its date cannot block a typo fix.

        Invariant 4 is a write-time rule about *setting* a due journal. A task
        whose journal has since passed is lapsed, not invalid — and lapsed tasks
        are precisely the ones a user is most likely to be tidying up when they
        next see them.
        """
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            async_connection, creating_journal_id=past_id, due_journal_id=past_id
        )

        updated = await service.update_task(
            user_id=USER_ID,
            task_id=task_id,
            text=REWORDED,
            transaction=async_connection,
        )

        assert updated.text == REWORDED
        assert await stored_text(async_connection, task_id) == REWORDED

    async def test_no_journal_link_is_created_by_an_edit(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Intermediate links are explicit only; editing infers none."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        await service.update_task(
            user_id=USER_ID,
            task_id=task_id,
            text=REWORDED,
            transaction=async_connection,
        )

        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0
        assert (
            await task_repository.list_intermediate_journal_ids(task_id, USER_ID) == []
        )

    async def test_the_anchors_are_unchanged(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The creating journal is immutable; the due journal moves by retargeting."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        await service.update_task(
            user_id=USER_ID,
            task_id=task_id,
            text=REWORDED,
            transaction=async_connection,
        )

        persisted = await task_repository.find_by_id(task_id, USER_ID)
        assert persisted is not None
        assert persisted.creating_journal_id == creating_id
        assert persisted.due_journal_id == due_id

    async def test_text_and_status_travel_together(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """One request, one row change — the reason a single method owns both."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        await service.update_task(
            user_id=USER_ID,
            task_id=task_id,
            text=REWORDED,
            status=TaskStatus.DONE,
            transaction=async_connection,
        )

        assert await stored_text(async_connection, task_id) == REWORDED
        assert await stored_status(async_connection, task_id) == "done"


@pytest.mark.integration
class TestRejectedEdits:
    """A refused edit leaves the stored row exactly as it was."""

    @pytest.mark.parametrize("blank", ["", "   "])
    async def test_blank_text_leaves_the_row_untouched(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        blank: str,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )

        with pytest.raises(TaskValidationError):
            await service.update_task(
                user_id=USER_ID,
                task_id=task_id,
                text=blank,
                transaction=async_connection,
            )

        assert await stored_text(async_connection, task_id) == "print the permit"

    async def test_the_same_text_does_not_move_updated_at(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """``updated_at`` is the only evidence out here that no write happened.

        ITER18-002's history projection derives its events from writes, so a
        write that changed nothing would surface as a change the user never made.

        **The timestamp is backdated first, and the test is worthless without
        that** — see :func:`backdate_updated_at`. PostgreSQL's ``now()`` is
        constant across a transaction and the fixture runs the whole test in
        one, so comparing an insert-time ``now()`` against an update-time
        ``now()`` compares a value with itself. Review caught this assertion
        passing against a service with the no-op short-circuit removed.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )
        backdated = await backdate_updated_at(async_connection, task_id)

        await service.update_task(
            user_id=USER_ID,
            task_id=task_id,
            text="print the permit",
            transaction=async_connection,
        )

        after = await task_repository.find_by_id(task_id, USER_ID)
        assert after is not None
        assert after.updated_at == backdated

    async def test_a_real_edit_does_move_updated_at(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The other half of the pair, without which the first proves nothing.

        A backdated timestamp that never moves is equally consistent with "the
        no-op worked" and "no write ever reaches this column". This is the test
        that rules the second out.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )
        backdated = await backdate_updated_at(async_connection, task_id)

        await service.update_task(
            user_id=USER_ID,
            task_id=task_id,
            text=REWORDED,
            transaction=async_connection,
        )

        after = await task_repository.find_by_id(task_id, USER_ID)
        assert after is not None
        assert after.updated_at is not None
        assert after.updated_at > backdated


@pytest.mark.integration
class TestDeletingATask:
    """ "Removing the task and its link rows and nothing else" — the criterion."""

    async def test_the_task_row_is_gone(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        await service.delete_task(
            user_id=USER_ID, task_id=task_id, transaction=async_connection
        )

        assert not await task_exists(async_connection, task_id)
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_both_kinds_of_link_row_go_with_it(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The cascade is migration 0105's, and this is where it is provable.

        The service issues one ``DELETE``; nothing in the code walks either link
        table. If a foreign key were ever changed to ``RESTRICT`` — as the
        *anchor* columns deliberately are — this would fail rather than silently
        leaving orphans behind.
        """
        task_id, _, _ = await _seed_linked_task(async_connection, journal_repository)
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 1
        assert await count(async_connection, COUNT_CONTACT_LINKS, {}) == 1

        await service.delete_task(
            user_id=USER_ID, task_id=task_id, transaction=async_connection
        )

        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 0
        assert await count(async_connection, COUNT_CONTACT_LINKS, {}) == 0

    async def test_the_journals_and_contacts_themselves_survive(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A task is not entitled to destroy what it merely pointed at.

        Both anchors, the intermediate journal and the contact all outlive it —
        the anchors especially, since they are the journals ITER18-002 refuses
        to delete *because* a task points at them.
        """
        task_id, mentioned_id, contact_id = await _seed_linked_task(
            async_connection, journal_repository
        )
        journals_before = await count(
            async_connection,
            "SELECT COUNT(*) FROM journals WHERE user_id = :user_id",
            {"user_id": USER_ID},
        )

        await service.delete_task(
            user_id=USER_ID, task_id=task_id, transaction=async_connection
        )

        assert (
            await count(
                async_connection,
                "SELECT COUNT(*) FROM journals WHERE user_id = :user_id",
                {"user_id": USER_ID},
            )
            == journals_before
        )
        assert await journal_repository.find_by_id(mentioned_id) is not None
        assert (
            await count(
                async_connection,
                "SELECT COUNT(*) FROM contacts WHERE id = :contact_id",
                {"contact_id": contact_id},
            )
            == 1
        )

    async def test_another_tasks_links_to_the_same_rows_are_untouched(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The cascade is keyed on the *task*, not on the journal or the contact.

        Raised by review: every other link assertion in this phase is an
        unqualified ``COUNT(*)`` over a link table in which only the doomed task
        has rows, so a delete that over-reached along the other side of either
        link — removing every row pointing at the shared intermediate journal,
        or at the shared contact — would satisfy all of them. Here a second task
        shares both, and keeps both.
        """
        mentioned_id = await create_journal(
            journal_repository, title="Where they both came up", days_offset=3
        )
        creating_id = await create_journal(
            journal_repository, title="Where it arose", days_offset=1
        )
        due_id = await create_journal(
            journal_repository, title="Where it is due", days_offset=7
        )
        contact_id = await create_contact(async_connection)

        doomed = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        survivor = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="somebody else's problem",
        )
        for task_id in (doomed, survivor):
            await link_intermediate_journal(
                async_connection, task_id=task_id, journal_id=mentioned_id
            )
            await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        await service.delete_task(
            user_id=USER_ID, task_id=doomed, transaction=async_connection
        )

        assert not await task_exists(async_connection, doomed)
        assert await task_repository.list_intermediate_journal_ids(
            survivor, USER_ID
        ) == [mentioned_id]
        assert await task_repository.list_contact_ids(survivor, USER_ID) == [contact_id]
        assert await count(async_connection, COUNT_INTERMEDIATE_JOURNALS, {}) == 1
        assert await count(async_connection, COUNT_CONTACT_LINKS, {}) == 1

    async def test_other_tasks_are_untouched(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The statement names one id; a sibling sharing both anchors stays."""
        creating_id, due_id = task_anchors
        doomed = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        survivor = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="somebody else's problem",
        )

        await service.delete_task(
            user_id=USER_ID, task_id=doomed, transaction=async_connection
        )

        assert not await task_exists(async_connection, doomed)
        assert (
            await stored_text(async_connection, survivor) == "somebody else's problem"
        )


@pytest.mark.integration
class TestUnreachableTasks:
    """Somebody else's task and a nonexistent one are the same answer."""

    async def test_editing_another_users_task_is_not_found_and_writes_nothing(
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
        foreign_task = await create_task(
            async_connection,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            text="not yours",
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskNotFoundError) as exc_info:
            await service.update_task(
                user_id=USER_ID,
                task_id=foreign_task,
                text=REWORDED,
                transaction=async_connection,
            )

        assert str(exc_info.value) == str(TaskNotFoundError(foreign_task))
        assert await stored_text(async_connection, foreign_task) == "not yours"

    async def test_deleting_another_users_task_is_not_found_and_leaves_the_row(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The row must survive, which is the half a 404 alone would not prove."""
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task = await create_task(
            async_connection,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskNotFoundError):
            await service.delete_task(
                user_id=USER_ID, task_id=foreign_task, transaction=async_connection
            )

        assert await task_exists(async_connection, foreign_task)

    async def test_an_absent_id_gives_the_identical_message(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Indistinguishable once the ids are stripped, on both operations.

        A difference here would turn either call into a way to ask whether a
        given task id belongs to somebody.
        """
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task = await create_task(
            async_connection,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskNotFoundError) as foreign:
            await service.delete_task(
                user_id=USER_ID, task_id=foreign_task, transaction=async_connection
            )
        with pytest.raises(TaskNotFoundError) as absent:
            await service.delete_task(
                user_id=USER_ID, task_id=999_999, transaction=async_connection
            )

        assert str(foreign.value).replace(str(foreign_task), "X") == str(
            absent.value
        ).replace("999999", "X")

    async def test_deleting_a_task_twice_is_not_found_the_second_time(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A delete that quietly succeeded on nothing would mislead a retry."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        await service.delete_task(
            user_id=USER_ID, task_id=task_id, transaction=async_connection
        )

        with pytest.raises(TaskNotFoundError):
            await service.delete_task(
                user_id=USER_ID, task_id=task_id, transaction=async_connection
            )


@pytest.mark.integration
class TestTheWritesAreUnitsOfWork:
    """Both new writes are wrapped, and this is how that is provable.

    **Reading the row back after the call does not show it.** The integration
    fixture owns an outer transaction and marks the connection, so
    ``unit_of_work`` stands a SAVEPOINT in for the real commit and every read on
    that connection sees the write with or without ``@transactional``. Phase 6
    corrected that claim wherever it appeared; this file inherits the correction
    rather than repeating the mistake.

    What *is* observable is the transaction open around the repository call. A
    repository that looks at the connection while it writes can tell whether it
    is inside one. Remove ``@transactional`` from either method and the matching
    test here — alone — fails.
    """

    async def test_the_edit_is_written_inside_an_open_unit_of_work(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
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

        await service.update_task(
            user_id=USER_ID,
            task_id=task_id,
            text=REWORDED,
            transaction=async_connection,
        )

        assert observed == [True]

    async def test_the_delete_is_issued_inside_an_open_unit_of_work(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        observed: list[bool] = []

        class _ObservingRepository(SqlTaskRepository):
            async def delete(self, task_id: int, user_id: str) -> None:
                observed.append(async_connection.get_nested_transaction() is not None)
                await super().delete(task_id, user_id)

        service = TaskService(
            task_repo=_ObservingRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
        )

        await service.delete_task(
            user_id=USER_ID, task_id=task_id, transaction=async_connection
        )

        assert observed == [True]

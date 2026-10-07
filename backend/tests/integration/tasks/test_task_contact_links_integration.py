"""Integration tests for the task contact-link service against real PostgreSQL.

Three of this phase's properties are only real against a database:

- **idempotency is the composite primary key's**, not the service's. Linking
  twice leaves one row because ``ON CONFLICT (task_id, contact_id) DO NOTHING``
  says so, and the ``RETURNING`` clause is what turns that into the "did
  anything change" answer the surfaces report.
- **deleting a contact drops its links and spares the task.** That is the
  ``ON DELETE CASCADE`` migration 0105 put on ``task_contacts.contact_id``,
  next to the ``ON DELETE RESTRICT`` on the journal anchors. The phase's fourth
  acceptance criterion asks for it to be asserted here, through a link this
  surface created rather than one hand-inserted.
- **a contact that vanishes between the existence check and the write** still
  answers 404. The batched insert cannot say *which* contact went, so the
  service re-reads to find out — and that recovery read is only possible because
  the insert runs inside a ``SAVEPOINT``. PostgreSQL aborts a transaction on a
  foreign-key violation, so without the savepoint the lookup would itself fail.
  A hand-built error cannot prove any of that; this is the test that can.

Owner scoping is asserted against a **real second user's rows** rather than an
absent id, because a query that dropped its ``user_id`` filter would still
return nothing for an id that never existed.
"""

import pytest
from core_shared.models.tasks import TaskNotFoundError, TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.contact_seeding import seed_contacts
from tests.integration.tasks.task_seeding import (
    COUNT_CONTACT_LINKS_FOR_TASK,
    COUNT_TASKS,
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
    create_task,
    delete_contact,
    link_contact,
    linked_contact_ids,
    stored_anchors,
    stored_status,
)

pytestmark = pytest.mark.integration


async def _links_for(conn: AsyncConnection, task_id: int) -> int:
    return await count(conn, COUNT_CONTACT_LINKS_FOR_TASK, {"task_id": task_id})


class TestLinkingAContact:
    """The round trip, and the row the composite key allows exactly one of."""

    async def test_the_link_row_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")

        changed = await service.link_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )

        assert changed is True
        assert await linked_contact_ids(async_connection, task_id) == [sarah]

    async def test_linking_again_leaves_one_row_and_reports_no_change(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Idempotency comes from the primary key, not from a read-then-write.

        There is no "is it already linked?" query anywhere: the insert asks the
        database, which is what makes two concurrent links safe without a lock.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")

        first = await service.link_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )
        second = await service.link_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )

        assert (first, second) == (True, False)
        assert await _links_for(async_connection, task_id) == 1

    async def test_several_contacts_accumulate_rather_than_replacing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A task references *any number* of contacts; linking is not setting."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        tom = await create_contact(async_connection, first_name="Tom")

        for contact_id in (sarah, tom):
            await service.link_contact(
                user_id=USER_ID,
                task_id=task_id,
                contact_id=contact_id,
                transaction=async_connection,
            )

        assert sorted(await linked_contact_ids(async_connection, task_id)) == sorted(
            [sarah, tom]
        )


class TestContactsAreNeverInferredFromTheText:
    """*"Contacts are not parsed out of the task text."*

    This is a criterion about a code path that must **not** exist, so it is
    asserted where its absence is observable: a task whose text names a real
    contact, by the exact string the contacts table holds, still has no links.
    A future "helpful" enrichment step would fail here rather than shipping.
    """

    async def test_naming_a_contact_in_the_text_links_nobody(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        sarah = await create_contact(async_connection, first_name="Sarah")

        created = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="return Sarah's book to Sarah",
            transaction=async_connection,
        )

        assert created.id is not None
        assert sarah > 0  # the contact really exists, so the absence means something
        assert await linked_contact_ids(async_connection, created.id) == []


class TestUnlinkingAContact:
    """Removal round-trips, and a repeat is not an error."""

    async def test_the_link_row_is_removed(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=sarah)

        changed = await service.unlink_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )

        assert changed is True
        assert await linked_contact_ids(async_connection, task_id) == []

    async def test_unlinking_again_is_accepted_and_reports_no_change(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=sarah)

        first = await service.unlink_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )
        second = await service.unlink_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )

        assert (first, second) == (True, False)

    async def test_unlinking_leaves_the_other_links_alone(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        tom = await create_contact(async_connection, first_name="Tom")
        await link_contact(async_connection, task_id=task_id, contact_id=sarah)
        await link_contact(async_connection, task_id=task_id, contact_id=tom)

        await service.unlink_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )

        assert await linked_contact_ids(async_connection, task_id) == [tom]


class TestContactLinksAreEditableInAnyStatus:
    """*"Task text and contact links can be edited at any time, in any status."*"""

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_linking_works_and_leaves_the_status_alone(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """Cancelled included, which no *status* call may leave."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )
        sarah = await create_contact(async_connection, first_name="Sarah")

        assert (
            await service.link_contact(
                user_id=USER_ID,
                task_id=task_id,
                contact_id=sarah,
                transaction=async_connection,
            )
            is True
        )
        assert await stored_status(async_connection, task_id) == status.value

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_unlinking_works_and_leaves_the_status_alone(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=sarah)

        assert (
            await service.unlink_contact(
                user_id=USER_ID,
                task_id=task_id,
                contact_id=sarah,
                transaction=async_connection,
            )
            is True
        )
        assert await stored_status(async_connection, task_id) == status.value


class TestDeletingAContact:
    """Criterion 4: the link goes, the task stays, and the anchors are untouched."""

    async def test_the_link_goes_and_the_task_survives(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Asserted through a link *this surface* made, not a hand-inserted row.

        Phase 1 proved the cascade against the table. What this adds is that the
        link the service writes is the same row the cascade reaches — a service
        that wrote somewhere else would pass that test and fail this one.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        tom = await create_contact(async_connection, first_name="Tom")
        for contact_id in (sarah, tom):
            await service.link_contact(
                user_id=USER_ID,
                task_id=task_id,
                contact_id=contact_id,
                transaction=async_connection,
            )

        await delete_contact(async_connection, sarah)

        assert await linked_contact_ids(async_connection, task_id) == [tom]
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 1
        assert await stored_status(async_connection, task_id) == "not_done"
        # The anchors are asserted rather than assumed. They are the one part of
        # the task a cascade could plausibly have reached, and "without touching
        # the tasks" is the whole of the criterion.
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)

    async def test_the_task_can_still_be_unlinked_from_the_deleted_contact(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The reason unlink does not demand the contact exist.

        The cascade already removed the row, so the call has nothing to do — and
        it must say so calmly rather than 404 on a contact the user is trying to
        tidy away.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        await service.link_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )

        await delete_contact(async_connection, sarah)

        assert (
            await service.unlink_contact(
                user_id=USER_ID,
                task_id=task_id,
                contact_id=sarah,
                transaction=async_connection,
            )
            is False
        )


class TestRejections:
    """An unknown contact, and a task that is not the acting user's."""

    async def test_an_unknown_contact_is_rejected_and_nothing_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        with pytest.raises(ContactNotFoundError) as exc_info:
            await service.link_contact(
                user_id=USER_ID,
                task_id=task_id,
                contact_id=999_999,
                transaction=async_connection,
            )

        assert exc_info.value.contact_id == 999_999
        assert await _links_for(async_connection, task_id) == 0

    async def test_another_users_task_cannot_be_linked_to(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A real second user's row, and the answer an absent id would give."""
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
        sarah = await create_contact(async_connection, first_name="Sarah")

        with pytest.raises(TaskNotFoundError) as foreign:
            await service.link_contact(
                user_id=USER_ID,
                task_id=foreign_task,
                contact_id=sarah,
                transaction=async_connection,
            )
        with pytest.raises(TaskNotFoundError) as absent:
            await service.link_contact(
                user_id=USER_ID,
                task_id=999_999,
                contact_id=sarah,
                transaction=async_connection,
            )

        assert str(foreign.value).replace(str(foreign_task), "X") == str(
            absent.value
        ).replace("999999", "X")
        assert await _links_for(async_connection, foreign_task) == 0

    async def test_another_users_task_cannot_be_unlinked_from(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """And the link that user does have is still there afterwards."""
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
        sarah = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=foreign_task, contact_id=sarah)

        with pytest.raises(TaskNotFoundError):
            await service.unlink_contact(
                user_id=USER_ID,
                task_id=foreign_task,
                contact_id=sarah,
                transaction=async_connection,
            )

        assert await linked_contact_ids(async_connection, foreign_task) == [sarah]


class TestTheBatchedWrite:
    """Phase 4's follow-up: N contacts cost one link call, not N."""

    async def test_create_links_every_contact_in_one_call(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        """Each ``add_contact`` re-proved ownership with its own locking read.

        Three contacts therefore cost six statements to link a task the service
        had created three lines earlier. The observing repository asserts the
        *shape* of the call rather than counting SQL, because the shape is what a
        future refactor would quietly change back.
        """
        creating_id, due_id = task_anchors
        contacts = [
            await create_contact(async_connection, first_name=name)
            for name in ("Sarah", "Tom", "Priya")
        ]
        calls: list[list[int]] = []

        class _CountingRepository(SqlTaskRepository):
            async def add_contacts(
                self, task_id: int, contact_ids: list[int], user_id: str
            ) -> list[int]:
                calls.append(list(contact_ids))
                return await super().add_contacts(task_id, contact_ids, user_id)

        service = TaskService(
            task_repo=_CountingRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
            event_publisher=OutboxEventPublisher(async_connection),
        )

        created = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="return everybody's books",
            contact_ids=contacts,
            transaction=async_connection,
        )

        assert calls == [contacts]
        assert created.id is not None
        assert sorted(await linked_contact_ids(async_connection, created.id)) == sorted(
            contacts
        )


class TestAContactThatVanishesMidWrite:
    """The Phase 4 race, now against a batched insert and a real database.

    The service checks the contacts exist and then writes them. A contact
    deleted in that window fails the foreign key, and the caller was promised a
    404 rather than a 500. With one contact per statement the id was known; with
    a batch it is not, so the service re-reads to find out which one went —
    and *that read is the point of the savepoint*. PostgreSQL puts a transaction
    into a failed state on a constraint violation, so without the savepoint the
    recovery lookup would itself raise and the mapping could never run.

    **Mutation-checked**, because that is a claim about the database rather than
    about the code: replacing ``savepoint(transaction)`` with a plain block makes
    this test fail with ``InFailedSQLTransactionError`` — *"current transaction
    is aborted, commands ignored until end of transaction block"* — which is the
    500 the mapping exists to prevent.
    """

    async def test_a_contact_deleted_after_the_check_still_answers_not_found(
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
        sarah = await create_contact(async_connection, first_name="Sarah")

        class _VanishingContactRepository(SqlContactRepository):
            """Reports the contact, then deletes it before the link is written."""

            deleted = False

            async def find_names_by_ids(
                self, contact_ids: list[int], *, user_id: str
            ) -> dict[int, tuple[str | None, str | None, str | None]]:
                names = await super().find_names_by_ids(contact_ids, user_id=user_id)
                if not self.deleted:
                    self.deleted = True
                    await delete_contact(async_connection, sarah)
                return names

        service = TaskService(
            task_repo=SqlTaskRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=_VanishingContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
            event_publisher=OutboxEventPublisher(async_connection),
        )

        with pytest.raises(ContactNotFoundError) as exc_info:
            await service.link_contact(
                user_id=USER_ID,
                task_id=task_id,
                contact_id=sarah,
                transaction=async_connection,
            )

        assert exc_info.value.contact_id == sarah
        assert await _links_for(async_connection, task_id) == 0


class TestTheWritesAreUnitsOfWork:
    """What ``@transactional`` actually guarantees, asserted where it is visible.

    Reading a row back after the call proves nothing here: the fixture owns an
    outer transaction and marks the connection, so ``unit_of_work`` stands a
    SAVEPOINT in for the commit and the row is visible with or without the
    decorator. What *is* observable is the transaction open around the
    repository call.

    Note which repository each test observes. ``unlink_contact`` is watched at
    its own write. ``link_contact`` is watched at the **contact read**, which
    happens before the insert — because the insert is wrapped in a savepoint of
    its own, and a nested transaction would be open there whether or not the
    method is a unit of work.

    **Mutation-checked:** deleting ``@transactional`` from ``unlink_contact``
    makes the first of these fail and nothing else in the suite.
    """

    async def test_unlink_writes_inside_an_open_unit_of_work(
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
        sarah = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=sarah)
        observed: list[bool] = []

        class _ObservingRepository(SqlTaskRepository):
            async def remove_contact(
                self, task_id: int, contact_id: int, user_id: str
            ) -> bool:
                observed.append(async_connection.get_nested_transaction() is not None)
                return await super().remove_contact(task_id, contact_id, user_id)

        service = TaskService(
            task_repo=_ObservingRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
            event_publisher=OutboxEventPublisher(async_connection),
        )

        await service.unlink_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )

        assert observed == [True]

    async def test_link_runs_inside_an_open_unit_of_work(
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
        sarah = await create_contact(async_connection, first_name="Sarah")
        observed: list[bool] = []

        class _ObservingContactRepository(SqlContactRepository):
            async def find_names_by_ids(
                self, contact_ids: list[int], *, user_id: str
            ) -> dict[int, tuple[str | None, str | None, str | None]]:
                observed.append(async_connection.get_nested_transaction() is not None)
                return await super().find_names_by_ids(contact_ids, user_id=user_id)

        service = TaskService(
            task_repo=SqlTaskRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=_ObservingContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
            event_publisher=OutboxEventPublisher(async_connection),
        )

        await service.link_contact(
            user_id=USER_ID,
            task_id=task_id,
            contact_id=sarah,
            transaction=async_connection,
        )

        assert observed == [True]


class TestAVeryLargeContactSet:
    """*"A task may reference any number of contacts"* — meant literally.

    The first version of the batched insert emitted one bind parameter per
    contact, which is correct until there are 32,767 of them: asyncpg's hard
    limit on query arguments. Past it a wholly valid create raised an
    ``InterfaceError`` the caller saw as a 500. Raised by the pull request's
    automated review.

    The fix passes the ids as a single ``integer[]`` and ``unnest``es them, so
    the parameter count no longer depends on *N*. This test exists because a
    smaller one proves nothing: the bug had a threshold, so the regression test
    has to stand on the far side of it.
    """

    async def test_more_contacts_than_asyncpg_allows_parameters(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        # Seeded in one statement: 33k round trips would make the test's own
        # setup the slowest thing in the suite.
        contact_ids = await seed_contacts(async_connection, 33_000)
        assert len(contact_ids) > 32_767, "the fixture must exceed the old limit"

        created = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="invite everybody",
            contact_ids=contact_ids,
            transaction=async_connection,
        )

        assert created.id is not None
        assert await _links_for(async_connection, created.id) == len(contact_ids)

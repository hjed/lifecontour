"""Integration tests for ``SqlTaskRepository`` against real PostgreSQL.

The repository is the tasks domain's only persistence surface, and this phase
holds it to four promises:

- **round trips** — a task saved is a task read back, status included;
- **link idempotency** — adding the same link twice cannot create a second row,
  so a retry is safe;
- **cascade on delete** — deleting a task takes its links with it and leaves the
  journals and contacts it referenced alone;
- **owner scoping** — every statement filters on ``user_id``, so no method can
  read, mutate or delete another user's task.

Owner scoping is asserted against a *real* second user's rows rather than an
absent id: a query that forgot its ``user_id`` filter still returns nothing for
an id that does not exist, so only real foreign data can catch it.

The invariants the repository is deliberately **not** responsible for — the due
journal existing, being owned by the acting user, and being future-dated — are
service-layer concerns and arrive with Phases 3 and 4.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from core_shared.models.tasks import Task, TaskNotFoundError, TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.models.repositories import TaskRepository
from tests.integration.statement_recorder import recorded_statements
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
    create_task,
    link_intermediate_journal,
    make_task_container,
)

_COUNT_INTERMEDIATE = (
    "SELECT COUNT(*) FROM task_intermediate_journals WHERE task_id = :task_id"
)
_COUNT_CONTACTS = "SELECT COUNT(*) FROM task_contacts WHERE task_id = :task_id"
_COUNT_TASKS_BY_ID = "SELECT COUNT(*) FROM tasks WHERE id = :task_id"


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def task_repository(async_connection: AsyncConnection) -> SqlTaskRepository:
    return SqlTaskRepository(async_connection)


@pytest_asyncio.fixture
async def anchors(journal_repository: SqlJournalRepository) -> tuple[int, int]:
    """A creating journal and a future due journal, as ``(creating, due)``."""
    creating_id = await create_journal(journal_repository, title="Where it arose")
    due_id = await create_journal(
        journal_repository, title="Where it matters", days_offset=7
    )
    return creating_id, due_id


@pytest_asyncio.fixture
async def saved_task(
    task_repository: SqlTaskRepository, anchors: tuple[int, int]
) -> Task:
    """A persisted task owned by ``USER_ID``."""
    creating_id, due_id = anchors
    return await task_repository.save(
        Task(
            user_id=USER_ID,
            text="return Sarah's book",
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
    )


@pytest_asyncio.fixture
async def other_users_task(
    task_repository: SqlTaskRepository, journal_repository: SqlJournalRepository
) -> Task:
    """A persisted task owned by somebody else, anchored to their journals."""
    creating_id = await create_journal(
        journal_repository, title="Their journal", user_id=OTHER_USER_ID
    )
    due_id = await create_journal(
        journal_repository,
        title="Their later journal",
        days_offset=7,
        user_id=OTHER_USER_ID,
    )
    return await task_repository.save(
        Task(
            user_id=OTHER_USER_ID,
            text="their commitment",
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )
    )


@pytest.mark.integration
class TestSaveAndFind:
    """Round-tripping a task through the database."""

    async def test_save_populates_id_and_timestamps(self, saved_task: Task):
        """The database owns the id and both timestamps."""
        assert saved_task.id is not None
        assert saved_task.created_at is not None
        assert saved_task.updated_at is not None

    async def test_new_task_defaults_to_not_done(self, saved_task: Task):
        """A task starts as an outstanding commitment."""
        assert saved_task.status is TaskStatus.NOT_DONE

    async def test_find_by_id_round_trips_every_field(
        self, task_repository: SqlTaskRepository, saved_task: Task
    ):
        """Reading back returns the same task, with status as the enum."""
        assert saved_task.id is not None
        found = await task_repository.find_by_id(saved_task.id, USER_ID)

        assert found is not None
        assert found.id == saved_task.id
        assert found.user_id == USER_ID
        assert found.text == "return Sarah's book"
        assert found.status is TaskStatus.NOT_DONE
        assert found.creating_journal_id == saved_task.creating_journal_id
        assert found.due_journal_id == saved_task.due_journal_id
        assert found.created_at == saved_task.created_at
        assert found.updated_at == saved_task.updated_at

    async def test_creating_and_due_may_be_the_same_journal(
        self, task_repository: SqlTaskRepository, anchors: tuple[int, int]
    ):
        """Invariant 6 — one journal may be both anchors."""
        _, due_id = anchors

        saved = await task_repository.save(
            Task(
                user_id=USER_ID,
                text="bring the permit",
                creating_journal_id=due_id,
                due_journal_id=due_id,
            )
        )

        assert saved.id is not None
        found = await task_repository.find_by_id(saved.id, USER_ID)
        assert found is not None
        assert found.creating_journal_id == due_id
        assert found.due_journal_id == due_id

    async def test_save_updates_text_and_status(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        saved_task: Task,
    ):
        """An existing task is updated in place; ``created_at`` is untouched.

        ``updated_at`` is not asserted to have *advanced*: PostgreSQL's ``now()``
        is transaction-scoped, and the test fixture holds one transaction open,
        so the insert and the update stamp the same instant.

        **Nor is it asserted to have been re-stamped**, which an earlier version
        of this docstring claimed. The comparison below reads the column back and
        checks it against the value ``RETURNING`` gave — which proves the entity
        agrees with the stored row, and would hold just as well if the ``UPDATE``
        had left the column alone. Under this fixture there is no assertion that
        can tell those apart; the corrected claim is the narrower one.
        """
        assert saved_task.id is not None
        original_created_at = saved_task.created_at
        saved_task.text = "return Sarah's book and her umbrella"
        saved_task.status = TaskStatus.DONE

        updated = await task_repository.save(saved_task)

        assert updated.id == saved_task.id
        assert updated.text == "return Sarah's book and her umbrella"
        assert updated.status is TaskStatus.DONE
        assert updated.created_at == original_created_at
        stored_updated_at = (
            await async_connection.execute(
                text("SELECT updated_at FROM tasks WHERE id = :task_id"),
                {"task_id": saved_task.id},
            )
        ).scalar_one()
        assert updated.updated_at == stored_updated_at

        reread = await task_repository.find_by_id(saved_task.id, USER_ID)
        assert reread is not None
        assert reread.text == "return Sarah's book and her umbrella"
        assert reread.status is TaskStatus.DONE

    async def test_find_by_id_returns_none_for_unknown_id(
        self, task_repository: SqlTaskRepository
    ):
        """A task that never existed is simply absent."""
        assert await task_repository.find_by_id(999_999, USER_ID) is None


@pytest.mark.integration
class TestOwnerScoping:
    """No method may reach another user's task."""

    async def test_find_by_id_cannot_see_another_users_task(
        self, task_repository: SqlTaskRepository, other_users_task: Task
    ):
        """A real task belonging to someone else reads as absent."""
        assert other_users_task.id is not None

        assert await task_repository.find_by_id(other_users_task.id, USER_ID) is None

    async def test_save_cannot_update_another_users_task(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        other_users_task: Task,
    ):
        """Re-owning a task by saving over it is refused, and the row survives."""
        assert other_users_task.id is not None
        hijacked = Task(
            id=other_users_task.id,
            user_id=USER_ID,
            text="stolen",
            creating_journal_id=other_users_task.creating_journal_id,
            due_journal_id=other_users_task.due_journal_id,
        )

        with pytest.raises(TaskNotFoundError):
            await task_repository.save(hijacked)

        still_theirs = await task_repository.find_by_id(
            other_users_task.id, OTHER_USER_ID
        )
        assert still_theirs is not None
        assert still_theirs.text == "their commitment"
        assert (
            await count(
                async_connection, _COUNT_TASKS_BY_ID, {"task_id": other_users_task.id}
            )
            == 1
        )

    async def test_delete_cannot_remove_another_users_task(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        other_users_task: Task,
    ):
        """The row survives a delete attempt by the wrong owner."""
        assert other_users_task.id is not None

        with pytest.raises(TaskNotFoundError):
            await task_repository.delete(other_users_task.id, USER_ID)

        assert (
            await count(
                async_connection, _COUNT_TASKS_BY_ID, {"task_id": other_users_task.id}
            )
            == 1
        )

    async def test_journal_link_methods_reject_another_users_task(
        self,
        task_repository: SqlTaskRepository,
        anchors: tuple[int, int],
        other_users_task: Task,
    ):
        """Attaching to, detaching from or listing a foreign task all raise."""
        assert other_users_task.id is not None
        task_id = other_users_task.id
        _, journal_id = anchors

        with pytest.raises(TaskNotFoundError):
            await task_repository.add_intermediate_journal(task_id, journal_id, USER_ID)

        with pytest.raises(TaskNotFoundError):
            await task_repository.remove_intermediate_journal(
                task_id, journal_id, USER_ID
            )

        with pytest.raises(TaskNotFoundError):
            await task_repository.list_intermediate_journal_ids(task_id, USER_ID)

    async def test_contact_link_methods_reject_another_users_task(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        other_users_task: Task,
    ):
        """The same guard applies to contact links."""
        assert other_users_task.id is not None
        task_id = other_users_task.id
        contact_id = await create_contact(async_connection, first_name="Priya")

        with pytest.raises(TaskNotFoundError):
            await task_repository.add_contacts(task_id, [contact_id], USER_ID)

        with pytest.raises(TaskNotFoundError):
            await task_repository.remove_contact(task_id, contact_id, USER_ID)

        with pytest.raises(TaskNotFoundError):
            await task_repository.list_contact_ids(task_id, USER_ID)


@pytest.mark.integration
class TestDelete:
    """Deleting a task, and what it takes with it."""

    async def test_delete_removes_the_task(
        self, task_repository: SqlTaskRepository, saved_task: Task
    ):
        """After a delete the task is gone."""
        assert saved_task.id is not None

        await task_repository.delete(saved_task.id, USER_ID)

        assert await task_repository.find_by_id(saved_task.id, USER_ID) is None

    async def test_delete_of_unknown_task_raises(
        self, task_repository: SqlTaskRepository
    ):
        """Deleting nothing is an error, not a silent success."""
        with pytest.raises(TaskNotFoundError):
            await task_repository.delete(999_999, USER_ID)

    async def test_delete_cascades_links_and_spares_journals_and_contacts(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
        saved_task: Task,
    ):
        """Links go with the task; the journals and contacts it named stay."""
        assert saved_task.id is not None
        task_id = saved_task.id
        mentioned_id = await create_journal(journal_repository, title="Mentioned here")
        contact_id = await create_contact(async_connection)
        await task_repository.add_intermediate_journal(task_id, mentioned_id, USER_ID)
        await task_repository.add_contacts(task_id, [contact_id], USER_ID)

        await task_repository.delete(task_id, USER_ID)

        assert (
            await count(async_connection, _COUNT_INTERMEDIATE, {"task_id": task_id})
            == 0
        )
        assert await count(async_connection, _COUNT_CONTACTS, {"task_id": task_id}) == 0
        assert await journal_repository.find_by_id(mentioned_id) is not None
        assert (
            await count(
                async_connection,
                "SELECT COUNT(*) FROM contacts WHERE id = :contact_id",
                {"contact_id": contact_id},
            )
            == 1
        )


@pytest.mark.integration
class TestVanishedTask:
    """A task that is gone reports as not found, never as a database error.

    The port promises ``TaskNotFoundError`` for a task the caller cannot reach,
    and the link methods check ownership in a statement of their own. If that
    check did not hold against the task disappearing, the guarded statement
    would surface a raw foreign-key violation from the link insert, or a bare
    ``False``/``[]`` from the remove and list — three different answers to one
    question.

    A genuinely *concurrent* delete cannot be staged here: the integration
    fixture holds a single savepoint-bound transaction, so a second connection
    could not even see the task, let alone race it. These tests pin the
    serialised form of the same case; the concurrent form is held off by the
    ``FOR KEY SHARE`` the ownership check takes.
    """

    async def test_every_link_method_reports_a_deleted_task_as_not_found(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
        saved_task: Task,
    ):
        """No link method leaks an IntegrityError once the task is gone."""
        assert saved_task.id is not None
        task_id = saved_task.id
        journal_id = await create_journal(journal_repository, title="Mentioned here")
        contact_id = await create_contact(async_connection)
        await task_repository.delete(task_id, USER_ID)

        with pytest.raises(TaskNotFoundError):
            await task_repository.add_intermediate_journal(task_id, journal_id, USER_ID)
        with pytest.raises(TaskNotFoundError):
            await task_repository.remove_intermediate_journal(
                task_id, journal_id, USER_ID
            )
        with pytest.raises(TaskNotFoundError):
            await task_repository.list_intermediate_journal_ids(task_id, USER_ID)
        with pytest.raises(TaskNotFoundError):
            await task_repository.add_contacts(task_id, [contact_id], USER_ID)
        with pytest.raises(TaskNotFoundError):
            await task_repository.remove_contact(task_id, contact_id, USER_ID)
        with pytest.raises(TaskNotFoundError):
            await task_repository.list_contact_ids(task_id, USER_ID)

    async def test_a_link_write_locks_the_task_against_deletion(
        self, task_repository: SqlTaskRepository, async_connection: AsyncConnection
    ):
        """The guard takes a row lock, which is what holds the window shut.

        Asserted through the row's ``xmax``: PostgreSQL stamps it with the
        locking transaction's id when a row is locked, and leaves it zero
        otherwise. Locking is the mechanism, so a test that only re-checked the
        returned value would pass just as well with the lock removed.

        ``remove_contact`` is the vehicle because its own statement deletes a
        *child* row, which needs no lock on the parent. An insert would take one
        for its foreign-key check whether the guard ran or not, so the xmax
        would be stamped either way and the test would prove nothing.
        """
        journal_repository = SqlJournalRepository(async_connection)
        journal_id = await create_journal(journal_repository, title="Anchor")
        task = await task_repository.save(
            Task(
                user_id=USER_ID,
                text="locked while linking",
                creating_journal_id=journal_id,
                due_journal_id=journal_id,
            )
        )
        assert task.id is not None
        contact_id = await create_contact(async_connection, first_name="Priya")
        read_xmax = text("SELECT xmax::text::bigint FROM tasks WHERE id = :task_id")

        unlocked = (
            await async_connection.execute(read_xmax, {"task_id": task.id})
        ).scalar_one()
        await task_repository.remove_contact(task.id, contact_id, USER_ID)
        locked = (
            await async_connection.execute(read_xmax, {"task_id": task.id})
        ).scalar_one()

        assert unlocked == 0
        assert locked != 0

    async def test_listing_links_does_not_lock_the_task(
        self, task_repository: SqlTaskRepository, async_connection: AsyncConnection
    ):
        """A read scopes itself without taking the write path's row lock.

        The mirror of the case above, and the reason the two reads no longer go
        through the guard at all: reading a task's links has no window to hold
        shut, and a lock taken here would block a concurrent writer for as long
        as the reading transaction lived. Pinned so a later "just reuse the
        guard" tidy-up cannot quietly reintroduce it.
        """
        journal_repository = SqlJournalRepository(async_connection)
        journal_id = await create_journal(journal_repository, title="Anchor")
        task = await task_repository.save(
            Task(
                user_id=USER_ID,
                text="read without locking",
                creating_journal_id=journal_id,
                due_journal_id=journal_id,
            )
        )
        assert task.id is not None
        read_xmax = text("SELECT xmax::text::bigint FROM tasks WHERE id = :task_id")

        await task_repository.list_contact_ids(task.id, USER_ID)
        await task_repository.list_intermediate_journal_ids(task.id, USER_ID)

        assert (
            await async_connection.execute(read_xmax, {"task_id": task.id})
        ).scalar_one() == 0

    async def test_listing_links_costs_one_statement(
        self, task_repository: SqlTaskRepository, async_connection: AsyncConnection
    ):
        """Each read is a single round trip, owner scoping included.

        The read used to pay a separate ownership statement before its own —
        two round trips to answer one question, on a path the task-write
        responses take as well. The count is the whole of what changed, so it is
        the thing to assert.
        """
        journal_repository = SqlJournalRepository(async_connection)
        journal_id = await create_journal(journal_repository, title="Anchor")
        task = await task_repository.save(
            Task(
                user_id=USER_ID,
                text="one statement",
                creating_journal_id=journal_id,
                due_journal_id=journal_id,
            )
        )
        assert task.id is not None

        with recorded_statements(async_connection) as statements:
            await task_repository.list_contact_ids(task.id, USER_ID)

        assert len(statements) == 1


@pytest.mark.integration
class TestTheTwoEmptyResults:
    """ "No links" and "not your task" both return no rows, and must not read alike.

    A single statement now has to separate them, so each is asserted for each
    read method. Written as its own class because the pair is the guarantee: a
    join that lost its ``LEFT`` would raise on a task with no links, and one
    that lost its ``user_id`` predicate would hand another user's links back as
    an ordinary empty list.
    """

    async def test_a_task_with_no_intermediate_journals_returns_empty(
        self, task_repository: SqlTaskRepository, saved_task: Task
    ):
        """A task that has never been linked to anything is not an error."""
        assert saved_task.id is not None

        assert (
            await task_repository.list_intermediate_journal_ids(saved_task.id, USER_ID)
            == []
        )

    async def test_a_task_with_no_contacts_returns_empty(
        self, task_repository: SqlTaskRepository, saved_task: Task
    ):
        """The same for contacts, which most tasks have none of."""
        assert saved_task.id is not None

        assert await task_repository.list_contact_ids(saved_task.id, USER_ID) == []

    async def test_another_users_unlinked_task_still_raises(
        self,
        task_repository: SqlTaskRepository,
        other_users_task: Task,
    ):
        """A foreign task with no links raises rather than reading as empty.

        The sharpest case for the ``user_id`` predicate: a foreign task that
        *has* links would come back non-empty and be caught by any assertion,
        but one with none returns exactly what a legitimately empty task
        returns, so only the error tells them apart.
        """
        assert other_users_task.id is not None

        with pytest.raises(TaskNotFoundError):
            await task_repository.list_intermediate_journal_ids(
                other_users_task.id, USER_ID
            )

        with pytest.raises(TaskNotFoundError):
            await task_repository.list_contact_ids(other_users_task.id, USER_ID)

    async def test_an_absent_task_raises_for_both_reads(
        self, task_repository: SqlTaskRepository
    ):
        """An id that never existed is refused the same way as a foreign one."""
        with pytest.raises(TaskNotFoundError):
            await task_repository.list_intermediate_journal_ids(999_999, USER_ID)

        with pytest.raises(TaskNotFoundError):
            await task_repository.list_contact_ids(999_999, USER_ID)


@pytest.mark.integration
class TestIntermediateJournalLinks:
    """Journals where the task was discussed, revisited, or previously due."""

    async def test_add_creates_the_link(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        saved_task: Task,
    ):
        """A new link is reported as created."""
        assert saved_task.id is not None
        mentioned_id = await create_journal(journal_repository, title="Mentioned here")

        assert (
            await task_repository.add_intermediate_journal(
                saved_task.id, mentioned_id, USER_ID
            )
            is True
        )
        assert await task_repository.list_intermediate_journal_ids(
            saved_task.id, USER_ID
        ) == [mentioned_id]

    async def test_add_is_idempotent(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
        saved_task: Task,
    ):
        """A retry reports no change and cannot create a duplicate row."""
        assert saved_task.id is not None
        task_id = saved_task.id
        mentioned_id = await create_journal(journal_repository, title="Mentioned here")
        await task_repository.add_intermediate_journal(task_id, mentioned_id, USER_ID)

        assert (
            await task_repository.add_intermediate_journal(
                task_id, mentioned_id, USER_ID
            )
            is False
        )
        assert (
            await count(async_connection, _COUNT_INTERMEDIATE, {"task_id": task_id})
            == 1
        )

    async def test_remove_reports_whether_it_removed_anything(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        saved_task: Task,
    ):
        """Removing an existing link is True; removing it again is False."""
        assert saved_task.id is not None
        task_id = saved_task.id
        mentioned_id = await create_journal(journal_repository, title="Mentioned here")
        await task_repository.add_intermediate_journal(task_id, mentioned_id, USER_ID)

        assert (
            await task_repository.remove_intermediate_journal(
                task_id, mentioned_id, USER_ID
            )
            is True
        )
        assert (
            await task_repository.remove_intermediate_journal(
                task_id, mentioned_id, USER_ID
            )
            is False
        )
        assert (
            await task_repository.list_intermediate_journal_ids(task_id, USER_ID) == []
        )

    async def test_list_returns_every_linked_journal(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        saved_task: Task,
    ):
        """All intermediate links come back, oldest link first."""
        assert saved_task.id is not None
        task_id = saved_task.id
        first_id = await create_journal(journal_repository, title="First mention")
        second_id = await create_journal(journal_repository, title="Second mention")
        await task_repository.add_intermediate_journal(task_id, first_id, USER_ID)
        await task_repository.add_intermediate_journal(task_id, second_id, USER_ID)

        linked = await task_repository.list_intermediate_journal_ids(task_id, USER_ID)

        # Order is asserted, not just membership: the port promises oldest link
        # first, and inside one transaction ``created_at`` ties, so the query's
        # journal_id tiebreak is what has to hold it.
        assert linked == [first_id, second_id]


@pytest.mark.integration
class TestContactLinks:
    """Plain contact references — no relationship type, role or status."""

    async def test_add_creates_the_link(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        saved_task: Task,
    ):
        """A new contact link is reported as created."""
        assert saved_task.id is not None
        contact_id = await create_contact(async_connection)

        assert await task_repository.add_contacts(
            saved_task.id, [contact_id], USER_ID
        ) == [contact_id]
        assert await task_repository.list_contact_ids(saved_task.id, USER_ID) == [
            contact_id
        ]

    async def test_add_is_idempotent(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        saved_task: Task,
    ):
        """A retry reports no change and cannot create a duplicate row."""
        assert saved_task.id is not None
        task_id = saved_task.id
        contact_id = await create_contact(async_connection)
        await task_repository.add_contacts(task_id, [contact_id], USER_ID)

        assert await task_repository.add_contacts(task_id, [contact_id], USER_ID) == []
        assert await count(async_connection, _COUNT_CONTACTS, {"task_id": task_id}) == 1

    async def test_remove_reports_whether_it_removed_anything(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        saved_task: Task,
    ):
        """Removing an existing link is True; removing it again is False."""
        assert saved_task.id is not None
        task_id = saved_task.id
        contact_id = await create_contact(async_connection)
        await task_repository.add_contacts(task_id, [contact_id], USER_ID)

        assert (
            await task_repository.remove_contact(task_id, contact_id, USER_ID) is True
        )
        assert (
            await task_repository.remove_contact(task_id, contact_id, USER_ID) is False
        )
        assert await task_repository.list_contact_ids(task_id, USER_ID) == []

    async def test_list_returns_every_linked_contact(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        saved_task: Task,
    ):
        """All contact links come back, oldest link first."""
        assert saved_task.id is not None
        task_id = saved_task.id
        sarah_id = await create_contact(async_connection, first_name="Sarah")
        priya_id = await create_contact(async_connection, first_name="Priya")
        await task_repository.add_contacts(task_id, [sarah_id], USER_ID)
        await task_repository.add_contacts(task_id, [priya_id], USER_ID)

        linked = await task_repository.list_contact_ids(task_id, USER_ID)

        assert linked == [sarah_id, priya_id]


@pytest.mark.integration
class TestDependencyInjection:
    """The repository is reachable through the container, not just importable."""

    async def test_task_provider_supplies_the_sql_adapter(
        self, async_connection: AsyncConnection
    ):
        """Resolving the port yields the SQL adapter on the request connection."""
        container = make_task_container(async_connection)
        try:
            async with container() as request_container:
                repository = await request_container.get(TaskRepository)

            assert isinstance(repository, SqlTaskRepository)
        finally:
            await container.close()


@pytest.mark.integration
class TestDueTaskCounts:
    """How many live commitments each of a page of journals holds.

    The journal list's indicator, and the only read in this repository whose
    subject is a *journal* rather than a task. It answers for a whole page in
    one statement, because the alternative is a query per row on the busiest
    listing in the product.

    What it deliberately does **not** know about is lapsing. A journal's date
    and its cancellation are the caller's to judge — see
    ``TaskReadService.due_task_counts`` — so everything here is about the two
    facts SQL can settle: the task is not done, and this journal is the one it
    is due in.
    """

    async def test_counts_not_done_tasks_per_due_journal(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Each journal is reported with its own count, not the page's total."""
        creating_id = await create_journal(journal_repository, title="Where it arose")
        busy_id = await create_journal(journal_repository, title="Busy", days_offset=7)
        quiet_id = await create_journal(
            journal_repository, title="Quiet", days_offset=8
        )
        for text_ in ("book the hut", "pack the rope"):
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=busy_id,
                text=text_,
            )
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=quiet_id,
            text="return the key",
        )

        counts = await task_repository.count_not_done_tasks_by_due_journal(
            [busy_id, quiet_id], USER_ID
        )

        assert counts == {busy_id: 2, quiet_id: 1}

    async def test_a_journal_with_no_due_tasks_is_absent(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
    ):
        """Absent rather than present with a zero, as the batched reads are.

        The caller reads through ``.get(journal_id, 0)``, so a page of journals
        holding nothing costs no rows at all rather than one row each.
        """
        empty_id = await create_journal(journal_repository, title="Nothing due here")

        assert (
            await task_repository.count_not_done_tasks_by_due_journal(
                [empty_id], USER_ID
            )
            == {}
        )

    async def test_done_and_cancelled_tasks_are_not_counted(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Only a not-done task is a live commitment.

        The not-done task beside them is what makes this a count rather than an
        existence check: without it the journal would be absent either way, and
        a query that had dropped its status predicate would pass.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        for status in (TaskStatus.NOT_DONE, TaskStatus.DONE, TaskStatus.CANCELLED):
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text=f"a {status.value} task",
                status=status,
            )

        counts = await task_repository.count_not_done_tasks_by_due_journal(
            [due_id], USER_ID
        )

        assert counts == {due_id: 1}

    async def test_another_users_task_does_not_count(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A foreign task due in the caller's journal is invisible to the count.

        Nothing in the schema forbids the row — the two foreign keys point at
        ``journals`` without comparing owners — so the predicate is what keeps
        one user's commitments off another's list, and this is the only way to
        show it is there.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="not yours to see",
            user_id=OTHER_USER_ID,
        )

        assert (
            await task_repository.count_not_done_tasks_by_due_journal([due_id], USER_ID)
            == {}
        )

    async def test_only_the_due_anchor_counts(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A journal the task was created in, or merely mentions, lights nothing.

        The indicator says *tasks due here*, which is one of the three link
        roles rather than any of them: a journal that recorded a commitment is
        not a journal that is waiting on one.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        mentioned_id = await create_journal(journal_repository, title="Mentioned")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="one commitment, three journals",
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned_id
        )

        counts = await task_repository.count_not_done_tasks_by_due_journal(
            [creating_id, mentioned_id, due_id], USER_ID
        )

        assert counts == {due_id: 1}

    async def test_a_task_anchored_twice_to_one_journal_is_counted_once(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Invariant 6's shared journal is one commitment, not two.

        A count is what makes this assertable at all: a boolean signal would
        read the same whether the task were counted once or twice.
        """
        shared_id = await create_journal(
            journal_repository, title="Both", days_offset=7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=shared_id,
            due_journal_id=shared_id,
            text="arose and matters here",
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=shared_id
        )

        counts = await task_repository.count_not_done_tasks_by_due_journal(
            [shared_id], USER_ID
        )

        assert counts == {shared_id: 1}

    async def test_journals_outside_the_page_are_not_counted(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """The answer is about the ids asked for, not about the user's tasks.

        A listing is a page of a much longer list, and a count that ignored its
        argument would still satisfy every assertion above.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        on_page_id = await create_journal(
            journal_repository, title="On page", days_offset=7
        )
        off_page_id = await create_journal(
            journal_repository, title="Off page", days_offset=8
        )
        for due_id in (on_page_id, off_page_id):
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="a commitment",
            )

        counts = await task_repository.count_not_done_tasks_by_due_journal(
            [on_page_id], USER_ID
        )

        assert counts == {on_page_id: 1}

    async def test_the_page_costs_one_statement_whatever_its_size(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """One round trip for two journals, and still one for eight.

        The doubling is the part that matters. A fixed number on its own would
        pass against a loop that happened to run a fixed number of times, so the
        assertion is that the number does not move when the page does.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        journal_ids = [
            await create_journal(
                journal_repository, title=f"Due {index}", days_offset=index + 1
            )
            for index in range(8)
        ]
        for due_id in journal_ids:
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="a commitment",
            )

        with recorded_statements(async_connection) as few:
            small = await task_repository.count_not_done_tasks_by_due_journal(
                journal_ids[:2], USER_ID
            )
        with recorded_statements(async_connection) as many:
            large = await task_repository.count_not_done_tasks_by_due_journal(
                journal_ids, USER_ID
            )

        assert len(small) == 2
        assert len(large) == 8
        assert len(few) == 1
        assert len(many) == 1

    async def test_an_empty_page_issues_no_statement(
        self, task_repository: SqlTaskRepository, async_connection: AsyncConnection
    ):
        """Nothing asked about is nothing to ask.

        The common shape on a filtered listing that matched no journals, and the
        same short-circuit ``find_cancelled_journal_ids`` takes.
        """
        with recorded_statements(async_connection) as statements:
            counts = await task_repository.count_not_done_tasks_by_due_journal(
                [], USER_ID
            )

        assert counts == {}
        assert statements == []


@pytest.mark.integration
class TestTasksDueInJournals:
    """Every task due in a set of journals, whatever became of it.

    The daily summary's past-day read. Its subject is a *journal* rather than a
    task, like ``count_not_done_tasks_by_due_journal`` above and unlike anything
    else here — but where the indicator asks *how many are still live*, this asks
    *which ones were due, and what happened to them*, which is why it is a
    sibling query rather than a widening of either that one or
    ``find_upcoming_tasks``.

    **The status filter is its defining absence.** ``find_upcoming_tasks`` drops
    everything but ``NOT_DONE`` because a done commitment is not upcoming; here a
    done commitment is precisely the answer. So the first test below is the one
    that separates a correct implementation from a copy of its neighbour.
    """

    async def test_returns_tasks_in_every_status(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Done, cancelled and not-done all come back — nothing is filtered.

        A summary of a past day reports how each commitment resolved, and two of
        the three resolutions are statuses the sibling listings exist to exclude.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=-1)
        for status in (TaskStatus.NOT_DONE, TaskStatus.DONE, TaskStatus.CANCELLED):
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text=f"a {status.value} task",
                status=status,
            )

        tasks = await task_repository.find_tasks_due_in_journals([due_id], USER_ID)

        assert {task.status for task in tasks} == {
            TaskStatus.NOT_DONE,
            TaskStatus.DONE,
            TaskStatus.CANCELLED,
        }

    async def test_a_task_carries_its_whole_row_back(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """The entity, not an id — the read model is assembled from these fields."""
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=-1)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="book the hut",
            status=TaskStatus.DONE,
        )

        (task,) = await task_repository.find_tasks_due_in_journals([due_id], USER_ID)

        assert task.id == task_id
        assert task.user_id == USER_ID
        assert task.text == "book the hut"
        assert task.status is TaskStatus.DONE
        assert task.creating_journal_id == creating_id
        assert task.due_journal_id == due_id

    async def test_only_the_due_anchor_qualifies(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A journal that recorded a commitment is not a journal it was due in.

        The same distinction the indicator draws, and it matters more here: the
        creating journal is nearly always in the past, so a query reading it
        would attribute half the user's commitments to whatever day they were
        first written down.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        mentioned_id = await create_journal(journal_repository, title="Mentioned")
        due_id = await create_journal(journal_repository, title="Due", days_offset=-1)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="one commitment, three journals",
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned_id
        )

        found = await task_repository.find_tasks_due_in_journals(
            [creating_id, mentioned_id], USER_ID
        )

        assert found == []

    async def test_another_users_task_is_invisible(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A foreign task due in the caller's journal never reaches their prompt.

        Nothing in the schema forbids the row — the anchors point at ``journals``
        without comparing owners — so the predicate is the only thing keeping one
        user's commitments out of another's summary, and a real second user's row
        is the only way to show it is there.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=-1)
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="not yours to see",
            user_id=OTHER_USER_ID,
        )

        assert await task_repository.find_tasks_due_in_journals([due_id], USER_ID) == []

    async def test_journals_outside_the_set_are_not_read(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """The answer is about the ids asked for, not about the user's tasks.

        A day is a handful of journals out of a much longer list, and a query
        that ignored its argument would still satisfy every assertion above.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        asked_id = await create_journal(
            journal_repository, title="Asked", days_offset=-1
        )
        other_id = await create_journal(
            journal_repository, title="Other", days_offset=-2
        )
        for due_id, task_text in ((asked_id, "on the day"), (other_id, "another day")):
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text=task_text,
            )

        tasks = await task_repository.find_tasks_due_in_journals([asked_id], USER_ID)

        assert [task.text for task in tasks] == ["on the day"]

    async def test_several_journals_are_answered_in_one_statement(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A day is a set of journals, and it costs one read however many.

        A functional test cannot see an N+1 — the answer is right either way —
        so the statement count is asserted directly, as the batched link reads
        beside this one are.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_ids = [
            await create_journal(
                journal_repository, title=f"Due {index}", days_offset=-1
            )
            for index in range(3)
        ]
        for index, due_id in enumerate(due_ids):
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text=f"task {index}",
            )

        with recorded_statements(async_connection) as statements:
            tasks = await task_repository.find_tasks_due_in_journals(due_ids, USER_ID)

        assert len(tasks) == 3
        assert len(statements) == 1

    async def test_the_order_is_the_due_journals_own(
        self,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Earliest journal first, ties broken by task id.

        The day's own order, so the prompt reads down the day rather than down
        the ``tasks`` table. The tie-break is what makes it **total**: a day's
        journal commonly holds several tasks sharing one start, and without it
        the same request could answer differently between runs.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        later_id = await create_journal(
            journal_repository,
            title="Afternoon",
            start=datetime(2026, 5, 4, 15, tzinfo=UTC),
        )
        earlier_id = await create_journal(
            journal_repository,
            title="Morning",
            start=datetime(2026, 5, 4, 9, tzinfo=UTC),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=later_id,
            text="third",
        )
        for task_text in ("first", "second"):
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=earlier_id,
                text=task_text,
            )

        tasks = await task_repository.find_tasks_due_in_journals(
            [later_id, earlier_id], USER_ID
        )

        assert [task.text for task in tasks] == ["first", "second", "third"]

    async def test_an_empty_set_issues_no_statement(
        self, task_repository: SqlTaskRepository, async_connection: AsyncConnection
    ):
        """A day with no journals has nothing to ask about.

        The quiet-day case the always-eligible rule exists for, and the same
        short-circuit ``count_not_done_tasks_by_due_journal`` takes.
        """
        with recorded_statements(async_connection) as statements:
            tasks = await task_repository.find_tasks_due_in_journals([], USER_ID)

        assert tasks == []
        assert statements == []

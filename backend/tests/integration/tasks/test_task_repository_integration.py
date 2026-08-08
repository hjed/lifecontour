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

import pytest
import pytest_asyncio
from core_shared.models.tasks import Task, TaskNotFoundError, TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.models.repositories import TaskRepository
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
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

    async def test_ownership_check_locks_the_task_against_deletion(
        self, task_repository: SqlTaskRepository, async_connection: AsyncConnection
    ):
        """The guard takes a row lock, which is what holds the window shut.

        Asserted through the row's ``xmax``: PostgreSQL stamps it with the
        locking transaction's id when a row is locked, and leaves it zero
        otherwise. Locking is the mechanism, so a test that only re-checked the
        returned value would pass just as well with the lock removed.
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
        read_xmax = text("SELECT xmax::text::bigint FROM tasks WHERE id = :task_id")

        unlocked = (
            await async_connection.execute(read_xmax, {"task_id": task.id})
        ).scalar_one()
        await task_repository.list_contact_ids(task.id, USER_ID)
        locked = (
            await async_connection.execute(read_xmax, {"task_id": task.id})
        ).scalar_one()

        assert unlocked == 0
        assert locked != 0


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

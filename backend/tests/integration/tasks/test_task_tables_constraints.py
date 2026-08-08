"""Foreign-key and constraint behaviour for the task tables.

The specification's *Journal Anchor Integrity* rules are load-bearing, and the
database is the last line of defence for them until ITER18-002 adds the
explanatory blocking in the service layer:

- deleting a journal that **anchors** a task (creating or due) must be refused,
  never allowed to silently destroy the task;
- deleting a journal that is only an **intermediate** link is permitted, removes
  the link, and leaves the task alone;
- deleting a **contact** drops its task links without touching tasks;
- deleting a **task** cascades away all of its links.

Each expected violation gets its own test: a failed statement poisons the
surrounding transaction, so the test must end there and let the fixture roll back.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.tasks.task_seeding import USER_ID
from tests.integration.tasks.task_seeding import count as _count
from tests.integration.tasks.task_seeding import create_contact as _create_contact
from tests.integration.tasks.task_seeding import create_journal as _create_journal
from tests.integration.tasks.task_seeding import link_contact as _link_contact
from tests.integration.tasks.task_seeding import (
    link_intermediate_journal as _link_intermediate_journal,
)

# Statements are built once at module level so that a ``pytest.raises`` block
# wraps only the execution under test, never the construction of its SQL.
_DELETE_JOURNAL = text("DELETE FROM journals WHERE id = :id")
_DELETE_TASK = text("DELETE FROM tasks WHERE id = :id")
_DELETE_CONTACT = text("DELETE FROM contacts WHERE id = :id")
_INSERT_TASK_WITHOUT_CREATING_JOURNAL = text(
    """
    INSERT INTO tasks (user_id, text, creating_journal_id, due_journal_id)
    VALUES (:user_id, 'Orphan', NULL, :due_id)
    """
)
_INSERT_TASK_WITHOUT_DUE_JOURNAL = text(
    """
    INSERT INTO tasks (user_id, text, creating_journal_id, due_journal_id)
    VALUES (:user_id, 'Orphan', :creating_id, NULL)
    """
)


async def _create_task(
    conn: AsyncConnection,
    *,
    creating_journal_id: int,
    due_journal_id: int,
    task_text: str = "Return Sarah's book",
) -> int:
    """Create a task row directly — the repository lands in Phase 2."""
    task_id = (
        await conn.execute(
            text(
                """
                INSERT INTO tasks (
                    user_id, text, creating_journal_id, due_journal_id
                )
                VALUES (:user_id, :text, :creating_id, :due_id)
                RETURNING id
                """
            ),
            {
                "user_id": USER_ID,
                "text": task_text,
                "creating_id": creating_journal_id,
                "due_id": due_journal_id,
            },
        )
    ).scalar_one()
    return int(task_id)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def anchors(journal_repository: SqlJournalRepository) -> tuple[int, int]:
    """A creating journal and a future due journal, as ``(creating, due)``."""
    creating_id = await _create_journal(journal_repository, title="Where it arose")
    due_id = await _create_journal(
        journal_repository, title="Where it matters", days_offset=7
    )
    return creating_id, due_id


@pytest_asyncio.fixture
async def anchored_task(
    async_connection: AsyncConnection, anchors: tuple[int, int]
) -> tuple[int, int, int]:
    """A task with both anchors, as ``(task_id, creating_id, due_id)``."""
    creating_id, due_id = anchors
    task_id = await _create_task(
        async_connection, creating_journal_id=creating_id, due_journal_id=due_id
    )
    return task_id, creating_id, due_id


@pytest.mark.integration
class TestAnchorJournalDeletionIsRefused:
    """A journal that anchors a task cannot be destroyed silently."""

    async def test_deleting_the_creating_journal_is_refused(
        self,
        async_connection: AsyncConnection,
        anchored_task: tuple[int, int, int],
    ) -> None:
        _, creating_id, _ = anchored_task

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_DELETE_JOURNAL, {"id": creating_id})

        # Name the constraint: both anchors point at journals, so a bare
        # IntegrityError would not prove the *creating* anchor is what refused.
        assert "tasks_creating_journal_id_fkey" in str(exc_info.value)

    async def test_deleting_the_due_journal_is_refused(
        self,
        async_connection: AsyncConnection,
        anchored_task: tuple[int, int, int],
    ) -> None:
        _, _, due_id = anchored_task

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_DELETE_JOURNAL, {"id": due_id})

        assert "tasks_due_journal_id_fkey" in str(exc_info.value)


@pytest.mark.integration
class TestIntermediateJournalDeletionIsPermitted:
    """An intermediate link is not an anchor."""

    async def test_deleting_an_intermediate_journal_drops_only_the_link(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        anchored_task: tuple[int, int, int],
    ) -> None:
        task_id, _, _ = anchored_task
        mentioned_id = await _create_journal(
            journal_repository, title="Where it came up again"
        )
        await _link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned_id
        )

        await async_connection.execute(_DELETE_JOURNAL, {"id": mentioned_id})

        assert (
            await _count(
                async_connection,
                "SELECT count(*) FROM task_intermediate_journals WHERE task_id = :id",
                {"id": task_id},
            )
            == 0
        )
        assert (
            await _count(
                async_connection,
                "SELECT count(*) FROM tasks WHERE id = :id",
                {"id": task_id},
            )
            == 1
        )


@pytest.mark.integration
class TestTaskDeletionCascadesItsLinks:
    """Deleting a task takes its links with it and nothing else."""

    async def test_task_delete_cascades_links_but_spares_journals_and_contacts(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        anchored_task: tuple[int, int, int],
    ) -> None:
        task_id, creating_id, due_id = anchored_task
        mentioned_id = await _create_journal(
            journal_repository, title="Where it came up again"
        )
        contact_id = await _create_contact(async_connection)
        await _link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned_id
        )
        await _link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        await async_connection.execute(_DELETE_TASK, {"id": task_id})

        assert (
            await _count(
                async_connection,
                "SELECT count(*) FROM task_intermediate_journals WHERE task_id = :id",
                {"id": task_id},
            )
            == 0
        )
        assert (
            await _count(
                async_connection,
                "SELECT count(*) FROM task_contacts WHERE task_id = :id",
                {"id": task_id},
            )
            == 0
        )
        assert (
            await _count(
                async_connection,
                "SELECT count(*) FROM journals WHERE id IN (:a, :b, :c)",
                {"a": creating_id, "b": due_id, "c": mentioned_id},
            )
            == 3
        )
        assert (
            await _count(
                async_connection,
                "SELECT count(*) FROM contacts WHERE id = :id",
                {"id": contact_id},
            )
            == 1
        )


@pytest.mark.integration
class TestContactDeletionDropsLinksOnly:
    """A contact link is a plain reference — losing it must not lose the task."""

    async def test_deleting_a_contact_drops_its_task_links_only(
        self,
        async_connection: AsyncConnection,
        anchored_task: tuple[int, int, int],
    ) -> None:
        task_id, _, _ = anchored_task
        contact_id = await _create_contact(async_connection)
        await _link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        await async_connection.execute(_DELETE_CONTACT, {"id": contact_id})

        assert (
            await _count(
                async_connection,
                "SELECT count(*) FROM task_contacts WHERE task_id = :id",
                {"id": task_id},
            )
            == 0
        )
        assert (
            await _count(
                async_connection,
                "SELECT count(*) FROM tasks WHERE id = :id",
                {"id": task_id},
            )
            == 1
        )


@pytest.mark.integration
class TestAnchorsAreMandatory:
    """Core invariants 1-3 expressed in the schema."""

    async def test_a_task_cannot_be_inserted_without_a_creating_journal(
        self,
        async_connection: AsyncConnection,
        anchors: tuple[int, int],
    ) -> None:
        _, due_id = anchors

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(
                _INSERT_TASK_WITHOUT_CREATING_JOURNAL,
                {"user_id": USER_ID, "due_id": due_id},
            )

        assert 'null value in column "creating_journal_id"' in str(exc_info.value)

    async def test_a_task_cannot_be_inserted_without_a_due_journal(
        self,
        async_connection: AsyncConnection,
        anchors: tuple[int, int],
    ) -> None:
        creating_id, _ = anchors

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(
                _INSERT_TASK_WITHOUT_DUE_JOURNAL,
                {"user_id": USER_ID, "creating_id": creating_id},
            )

        assert 'null value in column "due_journal_id"' in str(exc_info.value)

    async def test_creating_and_due_may_be_the_same_journal(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Core invariant 6 — nothing in the schema forbids one journal."""
        journal_id = await _create_journal(
            journal_repository, title="Both anchors", days_offset=7
        )

        task_id = await _create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=journal_id,
        )

        assert (
            await _count(
                async_connection,
                "SELECT count(*) FROM tasks WHERE id = :id",
                {"id": task_id},
            )
            == 1
        )


@pytest.mark.integration
class TestLinkTablesRejectDuplicates:
    """The composite primary keys are what make Phase 2's link adds idempotent."""

    async def test_duplicate_intermediate_journal_link_is_rejected(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        anchored_task: tuple[int, int, int],
    ) -> None:
        task_id, _, _ = anchored_task
        mentioned_id = await _create_journal(
            journal_repository, title="Where it came up again"
        )
        await _link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned_id
        )

        with pytest.raises(IntegrityError) as exc_info:
            await _link_intermediate_journal(
                async_connection, task_id=task_id, journal_id=mentioned_id
            )

        assert "task_intermediate_journals_pkey" in str(exc_info.value)

    async def test_duplicate_contact_link_is_rejected(
        self,
        async_connection: AsyncConnection,
        anchored_task: tuple[int, int, int],
    ) -> None:
        task_id, _, _ = anchored_task
        contact_id = await _create_contact(async_connection)
        await _link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        with pytest.raises(IntegrityError) as exc_info:
            await _link_contact(
                async_connection, task_id=task_id, contact_id=contact_id
            )

        assert "task_contacts_pkey" in str(exc_info.value)

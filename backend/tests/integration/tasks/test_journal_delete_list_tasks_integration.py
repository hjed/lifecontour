"""Deleting a journal that list tasks link to, against real PostgreSQL.

The specification's *Journal changes* table: a journal delete is **not blocked**
by a task on a list. The task's link to that journal — creating, due or
intermediate — is removed, and a task that was due in it becomes undated.
Journal-only tasks keep blocking, exactly as before.

Only a real database can show this, for the reason the delete guard's own
integration tests give: the anchors are ``ON DELETE RESTRICT``, so a list task
the service forgot to detach would surface as a raw ``IntegrityError`` rather
than an assertion failure. And the table's CHECKs refuse every shape the
product does not allow, so each list task seeded here is one that can exist.

What is asserted, in order:

- each link kind is removed, alone and together, at every status;
- a mixed journal is still refused and its list tasks are left untouched;
- each detached task announces itself once, and history records it;
- the preview's count is exactly what the delete then removes;
- a second user's rows are never touched;
- a list task that links to the journal after the detach is caught by the
  existing retry rather than becoming a 500.
"""

from typing import Any

import pytest
import pytest_asyncio
from core_shared.models.history import Provenance
from core_shared.models.journals import JournalHasAnchoredTasksError
from core_shared.models.tasks import TaskJournalDetachment, TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import (
    JournalDeletePreview,
    JournalService,
)
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.models.repositories import TaskAnchorRepository
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_journal,
    create_list_task,
    create_task,
    link_intermediate_journal,
    seed_task_list,
    task_events,
)
from tests.journal_service_factory import build_journal_service

_SELECT_TASK = text(
    "SELECT creating_journal_id, due_journal_id, due_date, task_list_id, status"
    " FROM tasks WHERE id = :task_id"
)
_SELECT_MENTIONS = text(
    "SELECT journal_id FROM task_intermediate_journals"
    " WHERE task_id = :task_id ORDER BY journal_id"
)
_COUNT_JOURNAL = text("SELECT COUNT(*) FROM journals WHERE id = :journal_id")


async def _task_row(conn: AsyncConnection, task_id: int) -> Any:
    return (await conn.execute(_SELECT_TASK, {"task_id": task_id})).one()


async def _mentions(conn: AsyncConnection, task_id: int) -> list[int]:
    rows = await conn.execute(_SELECT_MENTIONS, {"task_id": task_id})
    return [int(journal_id) for journal_id in rows.scalars()]


async def _journal_exists(conn: AsyncConnection, journal_id: int) -> bool:
    count = (await conn.execute(_COUNT_JOURNAL, {"journal_id": journal_id})).scalar()
    return bool(count)


@pytest_asyncio.fixture
async def journal_service(async_connection: AsyncConnection) -> JournalService:
    return build_journal_service(async_connection)


@pytest_asyncio.fixture
async def task_list_id(async_connection: AsyncConnection) -> int:
    task_list = await seed_task_list(async_connection, "Trip prep")
    assert task_list.id is not None
    return task_list.id


@pytest_asyncio.fixture
async def doomed_id(journal_repository: SqlJournalRepository) -> int:
    """The journal each test deletes."""
    return await create_journal(
        journal_repository, title="Cancelled trip", days_offset=5
    )


@pytest_asyncio.fixture
async def elsewhere_id(journal_repository: SqlJournalRepository) -> int:
    """A journal that survives every delete here, to anchor the other role."""
    return await create_journal(journal_repository, title="Planning", days_offset=-1)


@pytest.mark.integration
class TestEachLinkKindIsRemoved:
    """The spec's three link kinds, each alone and then all at once."""

    async def test_a_list_task_due_in_the_journal_becomes_undated(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        task_list_id: int,
        doomed_id: int,
        elsewhere_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            creating_journal_id=elsewhere_id,
            due_journal_id=doomed_id,
        )

        await journal_service.delete_journal(doomed_id, async_connection)

        row = await _task_row(async_connection, task_id)
        assert row.due_journal_id is None
        assert row.due_date is None
        assert row.creating_journal_id == elsewhere_id
        assert row.task_list_id == task_list_id
        assert not await _journal_exists(async_connection, doomed_id)

    async def test_a_list_task_created_in_the_journal_loses_that_anchor(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        task_list_id: int,
        doomed_id: int,
        elsewhere_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            creating_journal_id=doomed_id,
            due_journal_id=elsewhere_id,
        )

        await journal_service.delete_journal(doomed_id, async_connection)

        row = await _task_row(async_connection, task_id)
        assert row.creating_journal_id is None
        assert row.due_journal_id == elsewhere_id

    async def test_a_list_task_anchored_twice_to_the_journal_loses_both(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        task_list_id: int,
        doomed_id: int,
    ) -> None:
        """The list task left with no journal at all is still a legal row: the
        two-anchor CHECK applies only to a task with no list."""
        task_id = await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            creating_journal_id=doomed_id,
            due_journal_id=doomed_id,
        )

        await journal_service.delete_journal(doomed_id, async_connection)

        row = await _task_row(async_connection, task_id)
        assert row.creating_journal_id is None
        assert row.due_journal_id is None
        assert row.task_list_id == task_list_id

    async def test_a_list_task_that_only_mentions_the_journal_loses_the_mention(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        task_list_id: int,
        doomed_id: int,
        elsewhere_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection, task_list_id=task_list_id, due_journal_id=elsewhere_id
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=doomed_id
        )

        await journal_service.delete_journal(doomed_id, async_connection)

        assert await _mentions(async_connection, task_id) == []
        assert (await _task_row(async_connection, task_id)).due_journal_id == (
            elsewhere_id
        )

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_closed_list_task_is_detached_too(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        task_list_id: int,
        doomed_id: int,
        status: TaskStatus,
    ) -> None:
        """A done task's link is part of the record for a journal-only task,
        which is why those block whatever their status. A list task never
        blocks, so its status changes nothing here either — and is kept."""
        task_id = await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            due_journal_id=doomed_id,
            status=status,
        )

        await journal_service.delete_journal(doomed_id, async_connection)

        row = await _task_row(async_connection, task_id)
        assert row.due_journal_id is None
        assert row.status == status.value

    async def test_a_list_task_with_no_link_to_the_journal_is_untouched(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        task_list_id: int,
        doomed_id: int,
        elsewhere_id: int,
    ) -> None:
        task_id = await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            creating_journal_id=elsewhere_id,
            due_journal_id=elsewhere_id,
        )

        removed = await journal_service.delete_journal(doomed_id, async_connection)

        assert removed == 0
        row = await _task_row(async_connection, task_id)
        assert (row.creating_journal_id, row.due_journal_id) == (
            elsewhere_id,
            elsewhere_id,
        )
        assert await task_events(async_connection, task_id=task_id) == []


@pytest.mark.integration
class TestJournalOnlyTasksStillBlock:
    async def test_a_mixed_journal_is_refused_and_its_list_task_kept_whole(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        task_list_id: int,
        doomed_id: int,
        elsewhere_id: int,
    ) -> None:
        """The refusal names only the journal-only task, and the list task keeps
        every link — the detach runs only once the guard has passed."""
        blocker_id = await create_task(
            async_connection, creating_journal_id=elsewhere_id, due_journal_id=doomed_id
        )
        list_task_id = await create_list_task(
            async_connection, task_list_id=task_list_id, due_journal_id=doomed_id
        )
        await link_intermediate_journal(
            async_connection, task_id=list_task_id, journal_id=doomed_id
        )

        with pytest.raises(JournalHasAnchoredTasksError) as exc_info:
            await journal_service.delete_journal(doomed_id, async_connection)

        assert [t.task_id for t in exc_info.value.blocking_tasks] == [blocker_id]
        assert (await _task_row(async_connection, list_task_id)).due_journal_id == (
            doomed_id
        )
        assert await _mentions(async_connection, list_task_id) == [doomed_id]
        assert await task_events(async_connection, task_id=list_task_id) == []
        assert await _journal_exists(async_connection, doomed_id)


@pytest.mark.integration
class TestEachDetachedTaskIsAnnounced:
    async def test_one_event_per_task_naming_every_link_it_lost(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        task_list_id: int,
        doomed_id: int,
        elsewhere_id: int,
    ) -> None:
        everything_id = await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            creating_journal_id=doomed_id,
            due_journal_id=doomed_id,
        )
        await link_intermediate_journal(
            async_connection, task_id=everything_id, journal_id=doomed_id
        )
        mention_id = await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            position=1,
            due_journal_id=elsewhere_id,
        )
        await link_intermediate_journal(
            async_connection, task_id=mention_id, journal_id=doomed_id
        )

        removed = await journal_service.delete_journal(
            doomed_id, async_connection, changed_by="ui", source=Provenance.UI
        )

        assert removed == 2
        events = [
            e
            for e in await task_events(async_connection)
            if e.event_type == "TaskJournalLinksRemoved"
        ]
        assert [e.aggregate_id for e in events] == sorted([everything_id, mention_id])
        by_task = {e.aggregate_id: e.payload for e in events}
        assert by_task[everything_id]["changed_fields"] == {
            "creating_journal_id": [doomed_id, None],
            "due_journal_id": [doomed_id, None],
            f"journal:{doomed_id}": [doomed_id, None],
        }
        assert by_task[mention_id]["changed_fields"] == {
            f"journal:{doomed_id}": [doomed_id, None]
        }
        assert by_task[mention_id]["journal_id"] == doomed_id
        assert by_task[mention_id]["user_id"] == USER_ID
        assert by_task[mention_id]["source"] == Provenance.UI.value


@pytest.mark.integration
class TestThePreviewMatchesTheDelete:
    async def test_the_preview_counts_every_link_kind_once_per_task(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        task_list_id: int,
        doomed_id: int,
        elsewhere_id: int,
    ) -> None:
        """Due, creating and intermediate each count; a task holding two of
        them counts once; a journal-only task never counts (it blocks instead);
        and the number is the one the delete then reports."""
        await create_list_task(
            async_connection, task_list_id=task_list_id, due_journal_id=doomed_id
        )
        await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            position=1,
            creating_journal_id=doomed_id,
            due_journal_id=elsewhere_id,
        )
        twice_id = await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            position=2,
            due_journal_id=doomed_id,
        )
        await link_intermediate_journal(
            async_connection, task_id=twice_id, journal_id=doomed_id
        )
        mention_id = await create_list_task(
            async_connection,
            task_list_id=task_list_id,
            position=3,
            due_journal_id=elsewhere_id,
        )
        await link_intermediate_journal(
            async_connection, task_id=mention_id, journal_id=doomed_id
        )

        preview = await journal_service.preview_delete(doomed_id)

        assert preview == JournalDeletePreview(list_tasks_losing_link=4)
        assert await journal_service.delete_journal(doomed_id, async_connection) == 4

    async def test_a_journal_only_task_is_not_counted(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        doomed_id: int,
        elsewhere_id: int,
    ) -> None:
        await create_task(
            async_connection, creating_journal_id=elsewhere_id, due_journal_id=doomed_id
        )

        preview = await journal_service.preview_delete(doomed_id)

        assert preview.list_tasks_losing_link == 0


@pytest.mark.integration
class TestAnotherUsersRowsAreUntouched:
    async def test_deleting_my_journal_leaves_their_list_task_alone(
        self,
        async_connection: AsyncConnection,
        journal_service: JournalService,
        journal_repository: SqlJournalRepository,
        doomed_id: int,
    ) -> None:
        their_journal_id = await create_journal(
            journal_repository, title="Their trip", user_id=OTHER_USER_ID
        )
        their_list = await seed_task_list(
            async_connection, "Theirs", user_id=OTHER_USER_ID
        )
        assert their_list.id is not None
        their_task_id = await create_list_task(
            async_connection,
            task_list_id=their_list.id,
            due_journal_id=their_journal_id,
            user_id=OTHER_USER_ID,
        )

        await journal_service.delete_journal(doomed_id, async_connection)

        assert (await _task_row(async_connection, their_task_id)).due_journal_id == (
            their_journal_id
        )


class _DetachBlindOnFirstLook(TaskAnchorRepository):
    """The real anchor port, except that its first detach removes nothing.

    Stands in for the window between the detach and the ``DELETE``: a list task
    that links to the journal after the detach has run is exactly a row the
    first detach could not see. The row is really there for PostgreSQL to
    refuse the delete on, so the retry has to detach it for real.
    """

    def __init__(self, inner: SqlTaskAnchorRepository) -> None:
        self.inner = inner
        self.detaches = 0

    async def find_tasks_anchored_to_journal(self, journal_id: int) -> list[Any]:
        return await self.inner.find_tasks_anchored_to_journal(journal_id)

    async def repoint_journal_links(
        self, *, source_journal_id: int, target_journal_id: int
    ) -> list[Any]:
        raise AssertionError("a delete must not re-point task links")

    async def detach_list_tasks_from_journal(
        self, journal_id: int
    ) -> list[TaskJournalDetachment]:
        self.detaches += 1
        if self.detaches == 1:
            return []
        return await self.inner.detach_list_tasks_from_journal(journal_id)

    async def count_list_tasks_linked_to_journal(self, journal_id: int) -> int:
        return await self.inner.count_list_tasks_linked_to_journal(journal_id)


@pytest.mark.integration
class TestARacingListTaskIsCaughtByTheRetry:
    async def test_a_list_task_the_first_detach_missed_is_detached_on_retry(
        self,
        async_connection: AsyncConnection,
        task_list_id: int,
        doomed_id: int,
    ) -> None:
        """Without the second detach this is a raw ``IntegrityError``: nothing
        blocks the journal, so the guard has nothing to explain, and the RESTRICT
        anchor refuses the retried ``DELETE`` too."""
        task_id = await create_list_task(
            async_connection, task_list_id=task_list_id, due_journal_id=doomed_id
        )
        anchors = _DetachBlindOnFirstLook(SqlTaskAnchorRepository(async_connection))
        service = build_journal_service(async_connection, task_anchor_repo=anchors)

        removed = await service.delete_journal(doomed_id, async_connection)

        assert anchors.detaches == 2
        assert removed == 1
        assert (await _task_row(async_connection, task_id)).due_journal_id is None
        assert not await _journal_exists(async_connection, doomed_id)

"""Integration tests for the task list repository's two batch lookups.

Both serve read surfaces that label tasks with their list:

- ``find_by_ids`` resolves the lists a page of tasks names, in one statement,
  for the task read model;
- ``find_for_tasks`` resolves the list each of a page of task ids sits on, for
  a contact's history feed, whose rows carry only a task id.

Owner scoping is asserted against a second owner's *real* rows, never an absent
id: a query that forgot its ``user_id`` filter still finds nothing for an id
that does not exist.
"""

import pytest
import pytest_asyncio
from core_shared.models.tasks import TaskIcon
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from tests.integration.tasks.task_seeding import (
    ARCHIVED_AT,
    OTHER_USER_ID,
    USER_ID,
    create_journal,
    create_list_task,
    create_task,
    seed_task_list,
)

pytestmark = pytest.mark.integration

# Far beyond any id a test transaction can reach.
UNKNOWN_ID = 999_999_999


@pytest_asyncio.fixture
async def repository(async_connection: AsyncConnection) -> SqlTaskListRepository:
    return SqlTaskListRepository(async_connection)


async def journal_only_task(conn: AsyncConnection, *, user_id: str = USER_ID) -> int:
    """A journal-only task of ``user_id``'s, anchored to one fresh journal."""
    journal_id = await create_journal(
        SqlJournalRepository(conn), days_offset=3, user_id=user_id
    )
    return await create_task(
        conn,
        creating_journal_id=journal_id,
        due_journal_id=journal_id,
        user_id=user_id,
    )


class TestFindByIds:
    """The owner's lists among a set of ids, keyed by id."""

    async def test_it_returns_each_named_list_keyed_by_id(
        self, async_connection: AsyncConnection, repository: SqlTaskListRepository
    ) -> None:
        packing = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.PACKAGE
        )
        shopping = await seed_task_list(async_connection, "Shopping")
        await seed_task_list(async_connection, "Not asked for")
        assert packing.id is not None and shopping.id is not None

        found = await repository.find_by_ids([packing.id, shopping.id], USER_ID)

        assert found == {packing.id: packing, shopping.id: shopping}

    async def test_an_archived_list_is_found(
        self, async_connection: AsyncConnection, repository: SqlTaskListRepository
    ) -> None:
        """A task on an archived list still reads, so its list must resolve."""
        archived = await seed_task_list(
            async_connection, "Old trip", archived_at=ARCHIVED_AT
        )
        assert archived.id is not None

        found = await repository.find_by_ids([archived.id], USER_ID)

        assert found[archived.id].is_archived is True

    async def test_an_unknown_id_is_absent(
        self, async_connection: AsyncConnection, repository: SqlTaskListRepository
    ) -> None:
        packing = await seed_task_list(async_connection, "Packing")
        assert packing.id is not None

        found = await repository.find_by_ids([packing.id, UNKNOWN_ID], USER_ID)

        assert list(found) == [packing.id]

    async def test_another_owners_list_is_absent(
        self, async_connection: AsyncConnection, repository: SqlTaskListRepository
    ) -> None:
        theirs = await seed_task_list(async_connection, "Theirs", user_id=OTHER_USER_ID)
        assert theirs.id is not None

        assert await repository.find_by_ids([theirs.id], USER_ID) == {}

    async def test_no_ids_finds_nothing(
        self, repository: SqlTaskListRepository
    ) -> None:
        assert await repository.find_by_ids([], USER_ID) == {}


class TestFindForTasks:
    """The list each of a set of tasks sits on, keyed by task id."""

    async def test_a_list_task_maps_to_its_list(
        self, async_connection: AsyncConnection, repository: SqlTaskListRepository
    ) -> None:
        packing = await seed_task_list(async_connection, "Packing")
        shopping = await seed_task_list(
            async_connection, "Shopping", archived_at=ARCHIVED_AT
        )
        assert packing.id is not None and shopping.id is not None
        torch = await create_list_task(async_connection, task_list_id=packing.id)
        milk = await create_list_task(async_connection, task_list_id=shopping.id)

        found = await repository.find_for_tasks([torch, milk], USER_ID)

        assert found == {torch: packing, milk: shopping}

    async def test_a_journal_only_task_is_absent(
        self, async_connection: AsyncConnection, repository: SqlTaskListRepository
    ) -> None:
        task_id = await journal_only_task(async_connection)

        assert await repository.find_for_tasks([task_id], USER_ID) == {}

    async def test_an_unknown_task_is_absent(
        self, repository: SqlTaskListRepository
    ) -> None:
        assert await repository.find_for_tasks([UNKNOWN_ID], USER_ID) == {}

    async def test_another_owners_task_on_their_list_is_absent(
        self, async_connection: AsyncConnection, repository: SqlTaskListRepository
    ) -> None:
        theirs = await seed_task_list(async_connection, "Theirs", user_id=OTHER_USER_ID)
        assert theirs.id is not None
        their_task = await create_list_task(
            async_connection, task_list_id=theirs.id, user_id=OTHER_USER_ID
        )

        assert await repository.find_for_tasks([their_task], USER_ID) == {}

    async def test_my_task_on_another_owners_list_is_absent(
        self, async_connection: AsyncConnection, repository: SqlTaskListRepository
    ) -> None:
        """A cross-owner row never names the other owner's list."""
        theirs = await seed_task_list(async_connection, "Theirs", user_id=OTHER_USER_ID)
        assert theirs.id is not None
        mine = await create_list_task(
            async_connection, task_list_id=theirs.id, user_id=USER_ID
        )

        assert await repository.find_for_tasks([mine], USER_ID) == {}

    async def test_another_owners_task_on_my_list_is_absent(
        self, async_connection: AsyncConnection, repository: SqlTaskListRepository
    ) -> None:
        """The task's owner is checked too, not only the list's."""
        mine = await seed_task_list(async_connection, "Mine")
        assert mine.id is not None
        theirs = await create_list_task(
            async_connection, task_list_id=mine.id, user_id=OTHER_USER_ID
        )

        assert await repository.find_for_tasks([theirs], USER_ID) == {}

    async def test_no_ids_finds_nothing(
        self, repository: SqlTaskListRepository
    ) -> None:
        assert await repository.find_for_tasks([], USER_ID) == {}

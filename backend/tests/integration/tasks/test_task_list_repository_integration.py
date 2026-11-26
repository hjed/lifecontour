"""Integration tests for ``SqlTaskListRepository`` against real PostgreSQL.

The repository is the only persistence surface for task lists, and this phase
holds it to three promises:

- **round trips** — a list saved is a list read back, icon included;
- **positions** — a new list joins the bottom of its owner's lists, and lists
  read back in ``(position, id)`` order, with an archived filter;
- **owner scoping** — every statement filters on ``user_id``, so no method can
  read, change or delete another user's list;
- **the associated journal** — saved, changed and cleared through ``save``, and
  carried by every read.

Owner scoping is asserted against a second owner's *real* rows rather than an
absent id: a query that forgot its ``user_id`` filter still finds nothing for
an id that does not exist, so only a real foreign row can catch it.
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.models.tasks import (
    TaskIcon,
    TaskList,
    TaskListArchiveFilter,
    TaskListBusyError,
    TaskListNotFoundError,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.models.repositories import TaskListRepository
from tests.integration.concurrency_helpers import bounded
from tests.integration.statement_recorder import recorded_statements
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_list_task,
    make_task_container,
)

pytestmark = pytest.mark.integration

ARCHIVED_EARLIER = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
ARCHIVED_LATER = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

_SELECT_ROW = text("SELECT name, icon, position FROM task_lists WHERE id = :list_id")
_COUNT_BY_ID = text("SELECT COUNT(*) FROM task_lists WHERE id = :list_id")
_SELECT_ASSOCIATION = text(
    "SELECT associated_journal_id FROM task_lists WHERE id = :list_id"
)
_INSERT_JOURNAL = text("""
    INSERT INTO journals (title, content, user_id,
        event_date_range_start, event_date_range_end)
    VALUES (:title, '', :user_id, '2026-12-01', '2026-12-01')
    RETURNING id
""")
# The fixture runs every test in one transaction, so ``now()`` is the same
# instant throughout. Back-dating the row is what lets a test see the update
# path move ``updated_at`` and leave ``created_at`` alone.
_BACKDATE = text("""
    UPDATE task_lists
    SET created_at = now() - interval '2 days',
        updated_at = now() - interval '1 day'
    WHERE id = :list_id
    RETURNING created_at, updated_at
""")


@pytest_asyncio.fixture
async def repository(async_connection: AsyncConnection) -> SqlTaskListRepository:
    return SqlTaskListRepository(async_connection)


async def save_list(
    repository: SqlTaskListRepository,
    name: str,
    *,
    user_id: str = USER_ID,
    icon: TaskIcon | None = None,
    archived_at: datetime | None = None,
) -> TaskList:
    """Insert a list and return it as persisted."""
    return await repository.save(
        TaskList(user_id=user_id, name=name, icon=icon, archived_at=archived_at)
    )


async def set_position(
    conn: AsyncConnection, task_list: TaskList, position: int
) -> None:
    """Move a list directly in the table, bypassing ``reposition``."""
    await conn.execute(
        text("UPDATE task_lists SET position = :position WHERE id = :list_id"),
        {"position": position, "list_id": task_list.id},
    )


def ids(task_lists: list[TaskList]) -> list[int | None]:
    return [task_list.id for task_list in task_lists]


async def insert_journal(conn: AsyncConnection, title: str = "Trip") -> int:
    """A journal row for a list to name; its dates are irrelevant here."""
    result = await conn.execute(_INSERT_JOURNAL, {"title": title, "user_id": USER_ID})
    return int(result.scalar_one())


async def stored_association(conn: AsyncConnection, task_list: TaskList) -> int | None:
    """The association as the row holds it, read past the repository."""
    result = await conn.execute(_SELECT_ASSOCIATION, {"list_id": task_list.id})
    association: int | None = result.scalar_one()
    return association


class TestInsert:
    """Creating a list: what the database assigns, and where the list goes."""

    async def test_insert_populates_id_and_timestamps(
        self, repository: SqlTaskListRepository
    ) -> None:
        saved = await save_list(repository, "Groceries")

        assert saved.id is not None
        assert saved.created_at is not None
        assert saved.updated_at is not None
        assert saved.archived_at is None

    async def test_a_first_list_goes_to_the_top(
        self, repository: SqlTaskListRepository
    ) -> None:
        saved = await save_list(repository, "Groceries")

        assert saved.position == 0

    async def test_each_new_list_joins_the_bottom(
        self, repository: SqlTaskListRepository
    ) -> None:
        first = await save_list(repository, "Groceries")
        second = await save_list(repository, "Packing")
        third = await save_list(repository, "Errands")

        assert [first.position, second.position, third.position] == [0, 1, 2]

    async def test_the_bottom_counts_archived_lists(
        self, repository: SqlTaskListRepository
    ) -> None:
        """An archived list keeps its place, so unarchiving it returns it there
        rather than onto a position a newer list has since taken."""
        await save_list(repository, "Old trip", archived_at=ARCHIVED_EARLIER)

        saved = await save_list(repository, "Groceries")

        assert saved.position == 1

    async def test_the_bottom_is_the_owners_own(
        self, repository: SqlTaskListRepository
    ) -> None:
        """Another user's lists neither push a new list down nor are pushed."""
        await save_list(repository, "Theirs", user_id=OTHER_USER_ID)
        await save_list(repository, "Also theirs", user_id=OTHER_USER_ID)

        mine = await save_list(repository, "Mine")
        their_next = await save_list(repository, "Theirs again", user_id=OTHER_USER_ID)

        assert mine.position == 0
        assert their_next.position == 2

    async def test_a_given_position_is_ignored_on_insert(
        self, repository: SqlTaskListRepository
    ) -> None:
        """The repository places a new list; a caller cannot choose a slot."""
        await save_list(repository, "Groceries")

        saved = await repository.save(
            TaskList(user_id=USER_ID, name="Packing", position=0)
        )

        assert saved.position == 1


class TestFind:
    """Reading one list back."""

    async def test_find_by_id_round_trips_every_field(
        self, repository: SqlTaskListRepository
    ) -> None:
        saved = await save_list(
            repository,
            "Packing",
            icon=TaskIcon.LUGGAGE,
            archived_at=ARCHIVED_EARLIER,
        )
        assert saved.id is not None

        found = await repository.find_by_id(saved.id, USER_ID)

        assert found == saved
        assert found is not None
        assert found.icon is TaskIcon.LUGGAGE
        assert found.archived_at == ARCHIVED_EARLIER

    async def test_a_list_without_an_icon_reads_back_without_one(
        self, repository: SqlTaskListRepository
    ) -> None:
        saved = await save_list(repository, "Groceries")
        assert saved.id is not None

        found = await repository.find_by_id(saved.id, USER_ID)

        assert found is not None
        assert found.icon is None

    async def test_a_missing_id_is_not_found(
        self, repository: SqlTaskListRepository
    ) -> None:
        assert await repository.find_by_id(999_999, USER_ID) is None

    async def test_another_users_list_is_not_found(
        self, repository: SqlTaskListRepository
    ) -> None:
        theirs = await save_list(repository, "Theirs", user_id=OTHER_USER_ID)
        assert theirs.id is not None

        assert await repository.find_by_id(theirs.id, USER_ID) is None

    async def test_find_for_update_returns_the_owners_list(
        self, repository: SqlTaskListRepository
    ) -> None:
        saved = await save_list(repository, "Groceries")
        assert saved.id is not None

        assert await repository.find_by_id_for_update(saved.id, USER_ID) == saved

    async def test_find_for_update_does_not_find_another_users_list(
        self, repository: SqlTaskListRepository
    ) -> None:
        theirs = await save_list(repository, "Theirs", user_id=OTHER_USER_ID)
        assert theirs.id is not None

        assert await repository.find_by_id_for_update(theirs.id, USER_ID) is None

    async def test_find_for_update_locks_the_row(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """``FOR NO KEY UPDATE``, as tasks use: it excludes other writers of the
        list without blocking a foreign-key check against it."""
        saved = await save_list(repository, "Groceries")
        assert saved.id is not None

        with recorded_statements(async_connection) as statements:
            await repository.find_by_id_for_update(saved.id, USER_ID)

        assert len(statements) == 1
        assert "FOR NO KEY UPDATE" in statements[0]

    async def test_find_for_share_returns_the_owners_list(
        self, repository: SqlTaskListRepository
    ) -> None:
        saved = await save_list(repository, "Packing", archived_at=ARCHIVED_EARLIER)
        assert saved.id is not None

        assert await repository.find_by_id_for_share(saved.id, USER_ID) == saved

    async def test_find_for_share_does_not_find_another_users_list(
        self, repository: SqlTaskListRepository
    ) -> None:
        theirs = await save_list(repository, "Theirs", user_id=OTHER_USER_ID)
        assert theirs.id is not None

        assert await repository.find_by_id_for_share(theirs.id, USER_ID) is None

    async def test_find_for_share_of_a_missing_id_is_not_found(
        self, repository: SqlTaskListRepository
    ) -> None:
        assert await repository.find_by_id_for_share(999_999, USER_ID) is None

    async def test_find_for_share_takes_the_share_lock(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """``FOR SHARE``: a task write holds its list against an archive, which
        takes ``FOR NO KEY UPDATE``, without queueing behind another task write
        on the same list. The lock's effect is proved by the overlap tests in
        ``test_task_service_archived_list_integration.py``."""
        saved = await save_list(repository, "Groceries")
        assert saved.id is not None

        with recorded_statements(async_connection) as statements:
            await repository.find_by_id_for_share(saved.id, USER_ID)

        assert len(statements) == 1
        assert "FOR SHARE" in statements[0]


class TestUpdate:
    """Saving a list that already has an id."""

    async def test_update_changes_name_icon_and_archived_state(
        self, repository: SqlTaskListRepository
    ) -> None:
        saved = await save_list(repository, "Groceries")

        updated = await repository.save(
            replace(
                saved,
                name="Weekly shop",
                icon=TaskIcon.SHOPPING_CART,
                archived_at=ARCHIVED_LATER,
            )
        )

        assert updated.id == saved.id
        assert updated.name == "Weekly shop"
        assert updated.icon is TaskIcon.SHOPPING_CART
        assert updated.archived_at == ARCHIVED_LATER
        assert updated.is_archived

    async def test_update_can_clear_icon_and_unarchive(
        self, repository: SqlTaskListRepository
    ) -> None:
        saved = await save_list(
            repository, "Packing", icon=TaskIcon.LUGGAGE, archived_at=ARCHIVED_EARLIER
        )

        updated = await repository.save(replace(saved, icon=None, archived_at=None))

        assert updated.icon is None
        assert updated.archived_at is None
        assert not updated.is_archived

    async def test_update_moves_updated_at_and_keeps_created_at(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        saved = await save_list(repository, "Groceries")
        result = await async_connection.execute(_BACKDATE, {"list_id": saved.id})
        created_at, backdated_updated_at = result.one()

        updated = await repository.save(replace(saved, name="Weekly shop"))

        assert updated.created_at == created_at
        assert updated.updated_at is not None
        assert updated.updated_at > backdated_updated_at

    async def test_update_never_moves_the_list(
        self, repository: SqlTaskListRepository
    ) -> None:
        """Only reordering moves a list, so a rename racing a reorder cannot
        put the list back where the rename read it from."""
        saved = await save_list(repository, "Groceries")
        await save_list(repository, "Packing")

        updated = await repository.save(replace(saved, name="Shop", position=1))

        assert updated.position == 0

    async def test_updating_another_users_list_is_refused(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        theirs = await save_list(
            repository, "Theirs", user_id=OTHER_USER_ID, icon=TaskIcon.STAR
        )
        assert theirs.id is not None

        with pytest.raises(TaskListNotFoundError) as raised:
            await repository.save(replace(theirs, user_id=USER_ID, name="Mine now"))

        assert raised.value.task_list_id == theirs.id
        row = (
            await async_connection.execute(_SELECT_ROW, {"list_id": theirs.id})
        ).one()
        assert (row.name, row.icon, row.position) == ("Theirs", "star", 0)

    async def test_updating_a_missing_list_is_refused(
        self, repository: SqlTaskListRepository
    ) -> None:
        with pytest.raises(TaskListNotFoundError):
            await repository.save(TaskList(id=999_999, user_id=USER_ID, name="Gone"))


class TestListForUser:
    """Listing the owner's lists, in order, with the archived filter."""

    async def test_active_lists_come_in_position_order(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """Positions are set against creation order, so an order by id alone
        would fail."""
        first = await save_list(repository, "Groceries")
        second = await save_list(repository, "Packing")
        third = await save_list(repository, "Errands")
        await set_position(async_connection, first, 2)
        await set_position(async_connection, third, 0)

        listed = await repository.list_for_user(USER_ID)

        assert ids(listed) == ids([third, second, first])

    async def test_a_shared_position_is_broken_by_id(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """Positions are not unique — two concurrent creates can both take the
        bottom — so the id makes the order total. Only the older list is
        updated, so its row version is the newer one on disk and an order by
        position alone would tend to return it last."""
        first = await save_list(repository, "Groceries")
        second = await save_list(repository, "Packing")
        await set_position(async_connection, first, 1)

        listed = await repository.list_for_user(USER_ID)

        assert ids(listed) == ids([first, second])

    async def test_active_is_the_default_and_leaves_archived_lists_out(
        self, repository: SqlTaskListRepository
    ) -> None:
        active = await save_list(repository, "Groceries")
        await save_list(repository, "Old trip", archived_at=ARCHIVED_EARLIER)

        assert ids(await repository.list_for_user(USER_ID)) == ids([active])
        assert ids(
            await repository.list_for_user(USER_ID, TaskListArchiveFilter.ACTIVE)
        ) == ids([active])

    async def test_archived_lists_come_most_recently_archived_first(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """The archived page groups lists by the month they were archived, so
        the most recent sits at the top. Ids and positions both put the earlier
        archive first, so only the archived time gives this order."""
        await save_list(repository, "Groceries")
        later = await save_list(repository, "Last trip", archived_at=ARCHIVED_LATER)
        earlier = await save_list(repository, "Old trip", archived_at=ARCHIVED_EARLIER)
        await set_position(async_connection, earlier, 1)
        await set_position(async_connection, later, 2)

        listed = await repository.list_for_user(USER_ID, TaskListArchiveFilter.ARCHIVED)

        assert ids(listed) == ids([later, earlier])

    async def test_all_returns_both_in_position_order(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        archived = await save_list(repository, "Old trip", archived_at=ARCHIVED_EARLIER)
        active = await save_list(repository, "Groceries")
        await set_position(async_connection, archived, 1)
        await set_position(async_connection, active, 0)

        listed = await repository.list_for_user(USER_ID, TaskListArchiveFilter.ALL)

        assert ids(listed) == ids([active, archived])

    @pytest.mark.parametrize("archived", list(TaskListArchiveFilter))
    async def test_another_users_lists_are_never_listed(
        self,
        repository: SqlTaskListRepository,
        archived: TaskListArchiveFilter,
    ) -> None:
        await save_list(repository, "Theirs", user_id=OTHER_USER_ID)
        await save_list(
            repository,
            "Their old trip",
            user_id=OTHER_USER_ID,
            archived_at=ARCHIVED_EARLIER,
        )

        assert await repository.list_for_user(USER_ID, archived) == []


class TestDelete:
    """Hard-deleting a list."""

    async def test_delete_removes_the_list(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        saved = await save_list(repository, "Groceries")
        assert saved.id is not None

        await repository.delete(saved.id, USER_ID)

        assert await repository.find_by_id(saved.id, USER_ID) is None
        count = await async_connection.execute(_COUNT_BY_ID, {"list_id": saved.id})
        assert count.scalar_one() == 0

    async def test_deleting_another_users_list_is_refused(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        theirs = await save_list(repository, "Theirs", user_id=OTHER_USER_ID)
        assert theirs.id is not None

        with pytest.raises(TaskListNotFoundError):
            await repository.delete(theirs.id, USER_ID)

        count = await async_connection.execute(_COUNT_BY_ID, {"list_id": theirs.id})
        assert count.scalar_one() == 1

    async def test_deleting_a_missing_list_is_refused(
        self, repository: SqlTaskListRepository
    ) -> None:
        with pytest.raises(TaskListNotFoundError):
            await repository.delete(999_999, USER_ID)

    async def test_the_delete_statement_locks_the_list_without_waiting(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """The caller holds the list's tasks by now, so waiting for another
        holder of the list would be a deadlock; the lock must not wait."""
        saved = await save_list(repository, "Groceries")
        assert saved.id is not None

        with recorded_statements(async_connection) as statements:
            await repository.delete(saved.id, USER_ID)

        assert any("FOR UPDATE NOWAIT" in each for each in statements)


@pytest.mark.slow
class TestDeleteABusyList:
    """Another transaction holding the list makes the delete refuse at once."""

    async def test_a_list_held_by_another_transaction_is_busy(
        self, async_engine: AsyncEngine
    ) -> None:
        owner = f"race-{uuid4()}"
        async with async_engine.connect() as conn:
            saved = await SqlTaskListRepository(conn).save(
                TaskList(user_id=owner, name="Racing")
            )
            await conn.commit()
        assert saved.id is not None

        try:
            async with async_engine.connect() as one, async_engine.connect() as two:
                held = await SqlTaskListRepository(one).find_by_id_for_share(
                    saved.id, owner
                )
                assert held is not None

                with pytest.raises(TaskListBusyError) as refused:
                    await bounded(SqlTaskListRepository(two).delete(saved.id, owner))
                await two.rollback()
                await one.rollback()

            assert refused.value.task_list_id == saved.id
        finally:
            async with async_engine.connect() as cleanup:
                await cleanup.execute(
                    text("DELETE FROM task_lists WHERE user_id = :owner"),
                    {"owner": owner},
                )
                await cleanup.commit()

        async with async_engine.connect() as conn:
            remaining = await conn.execute(
                text("SELECT COUNT(*) FROM task_lists WHERE id = :id"), {"id": saved.id}
            )
            assert remaining.scalar_one() == 0


_SELECT_CTID = text("SELECT ctid::text FROM task_lists WHERE id = :list_id")
_SELECT_POSITION_AND_UPDATED_AT = text(
    "SELECT position, updated_at FROM task_lists WHERE id = :list_id"
)


class TestListForUserForUpdate:
    """Every one of the owner's lists, locked, for a move to renumber."""

    async def test_returns_every_list_archived_included_in_stored_order(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        first = await save_list(repository, "First")
        archived = await save_list(repository, "Archived", archived_at=ARCHIVED_EARLIER)
        last = await save_list(repository, "Last")
        # Stored order deliberately against id order: last, archived, first.
        await set_position(async_connection, first, 2)
        await set_position(async_connection, last, 0)

        locked = await repository.list_for_user_for_update(USER_ID)

        assert ids(locked) == [last.id, archived.id, first.id]
        assert [each.is_archived for each in locked] == [False, True, False]

    async def test_locks_the_rows_in_id_order(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """Locked in ``id`` order, which no move changes, so two movers always
        take the locks in the same order and cannot deadlock — and read in a
        statement of its own afterwards, whose snapshot postdates the wait, so
        it sees what the writer it waited on committed."""
        await save_list(repository, "Groceries")

        with recorded_statements(async_connection) as statements:
            await repository.list_for_user_for_update(USER_ID)

        lock, read = statements
        assert "FOR NO KEY UPDATE" in lock
        assert "ORDER BY id" in lock
        assert "FOR NO KEY UPDATE" not in read

    async def test_a_new_list_takes_the_same_locks_before_its_insert(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """So a create and a move serialize, and the bottom the insert computes
        is the one the move left — not one read before it renumbered."""
        await save_list(repository, "Groceries")

        with recorded_statements(async_connection) as statements:
            await save_list(repository, "Packing")

        lock, insert = statements
        assert "FOR NO KEY UPDATE" in lock
        assert "ORDER BY id" in lock
        assert insert.lstrip().startswith("INSERT INTO task_lists")

    async def test_never_returns_another_users_lists(
        self, repository: SqlTaskListRepository
    ) -> None:
        mine = await save_list(repository, "Mine")
        await save_list(repository, "Theirs", user_id=OTHER_USER_ID)

        assert ids(await repository.list_for_user_for_update(USER_ID)) == [mine.id]

    async def test_a_user_with_no_lists_gets_none(
        self, repository: SqlTaskListRepository
    ) -> None:
        await save_list(repository, "Theirs", user_id=OTHER_USER_ID)

        assert await repository.list_for_user_for_update(USER_ID) == []


class TestReposition:
    """Writing a new order: dense positions, the owner's rows only."""

    async def test_numbers_the_lists_densely_in_the_given_order(
        self, repository: SqlTaskListRepository
    ) -> None:
        a = await save_list(repository, "A")
        b = await save_list(repository, "B", archived_at=ARCHIVED_EARLIER)
        c = await save_list(repository, "C")
        assert a.id is not None and b.id is not None and c.id is not None

        await repository.reposition(USER_ID, [c.id, a.id, b.id])

        lists = await repository.list_for_user(USER_ID, TaskListArchiveFilter.ALL)
        assert ids(lists) == [c.id, a.id, b.id]
        assert [each.position for each in lists] == [0, 1, 2]

    async def test_heals_tied_positions(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        a = await save_list(repository, "A")
        b = await save_list(repository, "B")
        assert a.id is not None and b.id is not None
        await set_position(async_connection, b, 0)

        await repository.reposition(USER_ID, [b.id, a.id])

        lists = await repository.list_for_user(USER_ID)
        assert [(each.id, each.position) for each in lists] == [(b.id, 0), (a.id, 1)]

    async def test_leaves_updated_at_alone(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """A reorder is not an edit of the list, so it is not "last changed"."""
        a = await save_list(repository, "A")
        b = await save_list(repository, "B")
        assert a.id is not None and b.id is not None
        result = await async_connection.execute(_BACKDATE, {"list_id": a.id})
        _, backdated_updated_at = result.one()

        await repository.reposition(USER_ID, [b.id, a.id])

        row = await async_connection.execute(
            _SELECT_POSITION_AND_UPDATED_AT, {"list_id": a.id}
        )
        position, updated_at = row.one()
        assert position == 1
        assert updated_at == backdated_updated_at

    async def test_writes_nothing_to_a_list_already_in_place(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """Every UPDATE writes a new row version (a new ``ctid``) even when it
        changes nothing, so an unchanged ``ctid`` proves the row was skipped."""
        a = await save_list(repository, "A")
        b = await save_list(repository, "B")
        c = await save_list(repository, "C")
        assert a.id is not None and b.id is not None and c.id is not None
        before = {
            each.id: (
                await async_connection.execute(_SELECT_CTID, {"list_id": each.id})
            ).scalar_one()
            for each in (a, b, c)
        }

        await repository.reposition(USER_ID, [a.id, c.id, b.id])

        after = {
            list_id: (
                await async_connection.execute(_SELECT_CTID, {"list_id": list_id})
            ).scalar_one()
            for list_id in before
        }
        assert after[a.id] == before[a.id]
        assert after[b.id] != before[b.id]
        assert after[c.id] != before[c.id]

    async def test_never_moves_another_users_list(
        self,
        repository: SqlTaskListRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """Even handed a foreign id, the write is scoped to the acting owner."""
        await save_list(repository, "Their first", user_id=OTHER_USER_ID)
        theirs = await save_list(repository, "Theirs", user_id=OTHER_USER_ID)
        mine = await save_list(repository, "Mine")
        assert theirs.id is not None and mine.id is not None

        await repository.reposition(USER_ID, [theirs.id, mine.id])

        theirs_row = await async_connection.execute(_SELECT_ROW, {"list_id": theirs.id})
        assert theirs_row.one().position == 1
        mine_row = await async_connection.execute(_SELECT_ROW, {"list_id": mine.id})
        assert mine_row.one().position == 1

    async def test_an_empty_order_writes_nothing(
        self, repository: SqlTaskListRepository
    ) -> None:
        mine = await save_list(repository, "Mine")

        await repository.reposition(USER_ID, [])

        assert ids(await repository.list_for_user(USER_ID)) == [mine.id]


class TestAssociatedJournal:
    """A list's associated journal goes through ``save`` and every read.

    Every update caller starts from the locked stored row, so an update writes
    back whatever association that row holds — a rename keeps it.
    """

    async def test_an_insert_stores_the_association_and_reads_it_back(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        journal_id = await insert_journal(async_connection)

        saved = await repository.save(
            TaskList(user_id=USER_ID, name="Packing", associated_journal_id=journal_id)
        )
        assert saved.id is not None

        assert saved.associated_journal_id == journal_id
        assert await stored_association(async_connection, saved) == journal_id
        found = await repository.find_by_id(saved.id, USER_ID)
        assert found is not None
        assert found.associated_journal_id == journal_id

    async def test_a_list_saved_without_one_is_unassociated(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        saved = await save_list(repository, "Packing")

        assert saved.associated_journal_id is None
        assert await stored_association(async_connection, saved) is None

    async def test_an_update_sets_changes_and_clears_it(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        trip = await insert_journal(async_connection, "Trip")
        meeting = await insert_journal(async_connection, "Meeting")
        stored = await save_list(repository, "Packing")

        associated = await repository.save(replace(stored, associated_journal_id=trip))
        assert associated.associated_journal_id == trip
        assert await stored_association(async_connection, stored) == trip

        changed = await repository.save(
            replace(associated, associated_journal_id=meeting)
        )
        assert changed.associated_journal_id == meeting
        assert await stored_association(async_connection, stored) == meeting

        cleared = await repository.save(replace(changed, associated_journal_id=None))
        assert cleared.associated_journal_id is None
        assert await stored_association(async_connection, stored) is None

    async def test_an_update_from_the_stored_row_keeps_it(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        """A rename or archive passes the stored association straight through."""
        journal_id = await insert_journal(async_connection)
        stored = await repository.save(
            TaskList(user_id=USER_ID, name="Packing", associated_journal_id=journal_id)
        )

        renamed = await repository.save(
            replace(stored, name="Packing for the trip", archived_at=ARCHIVED_LATER)
        )

        assert renamed.associated_journal_id == journal_id
        assert await stored_association(async_connection, stored) == journal_id

    async def test_every_read_carries_it(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        journal_id = await insert_journal(async_connection)
        stored = await repository.save(
            TaskList(user_id=USER_ID, name="Packing", associated_journal_id=journal_id)
        )
        assert stored.id is not None
        task_id = await create_list_task(async_connection, task_list_id=stored.id)

        listed = await repository.list_for_user(USER_ID)
        by_ids = await repository.find_by_ids([stored.id], USER_ID)
        for_tasks = await repository.find_for_tasks([task_id], USER_ID)
        for_update = await repository.find_by_id_for_update(stored.id, USER_ID)
        for_share = await repository.find_by_id_for_share(stored.id, USER_ID)
        locked = await repository.list_for_user_for_update(USER_ID)

        assert [task_list.associated_journal_id for task_list in listed] == [journal_id]
        assert by_ids[stored.id].associated_journal_id == journal_id
        assert for_tasks[task_id].associated_journal_id == journal_id
        assert for_update is not None
        assert for_update.associated_journal_id == journal_id
        assert for_share is not None
        assert for_share.associated_journal_id == journal_id
        assert [task_list.associated_journal_id for task_list in locked] == [journal_id]


async def save_associated(
    repository: SqlTaskListRepository,
    name: str,
    journal_id: int,
    *,
    user_id: str = USER_ID,
    archived_at: datetime | None = None,
) -> TaskList:
    """Insert a list associated with a journal, as no service can yet."""
    return await repository.save(
        TaskList(
            user_id=user_id,
            name=name,
            archived_at=archived_at,
            associated_journal_id=journal_id,
        )
    )


class TestUnassociateJournal:
    """A journal delete clears the association of every list the owner has on it.

    A system write: archived lists are cleared too, and nothing outside the
    owner's lists on that journal is touched.
    """

    async def test_it_clears_every_owner_list_on_the_journal(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        trip = await insert_journal(async_connection)
        packing = await save_associated(repository, "Packing", trip)
        shopping = await save_associated(repository, "Shopping", trip)
        assert packing.id is not None
        assert shopping.id is not None

        cleared = await repository.unassociate_journal(trip, USER_ID)

        assert cleared == sorted([packing.id, shopping.id])
        assert await stored_association(async_connection, packing) is None
        assert await stored_association(async_connection, shopping) is None

    async def test_it_moves_updated_at(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        trip = await insert_journal(async_connection)
        packing = await save_associated(repository, "Packing", trip)
        result = await async_connection.execute(_BACKDATE, {"list_id": packing.id})
        _, backdated_updated_at = result.one()
        assert packing.id is not None

        await repository.unassociate_journal(trip, USER_ID)

        found = await repository.find_by_id(packing.id, USER_ID)
        assert found is not None
        assert found.updated_at is not None
        assert found.updated_at > backdated_updated_at

    async def test_a_list_on_another_journal_is_untouched(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        trip = await insert_journal(async_connection, "Trip")
        meeting = await insert_journal(async_connection, "Meeting")
        agenda = await save_associated(repository, "Agenda", meeting)

        cleared = await repository.unassociate_journal(trip, USER_ID)

        assert cleared == []
        assert await stored_association(async_connection, agenda) == meeting

    async def test_an_archived_list_is_cleared_and_stays_archived(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        trip = await insert_journal(async_connection)
        packing = await save_associated(
            repository, "Packing", trip, archived_at=ARCHIVED_EARLIER
        )
        assert packing.id is not None

        cleared = await repository.unassociate_journal(trip, USER_ID)

        assert cleared == [packing.id]
        found = await repository.find_by_id(packing.id, USER_ID)
        assert found is not None
        assert found.associated_journal_id is None
        assert found.archived_at == ARCHIVED_EARLIER

    async def test_another_users_list_is_untouched(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        trip = await insert_journal(async_connection)
        theirs = await save_associated(
            repository, "Their packing", trip, user_id=OTHER_USER_ID
        )

        cleared = await repository.unassociate_journal(trip, USER_ID)

        assert cleared == []
        assert await stored_association(async_connection, theirs) == trip

    async def test_it_locks_the_lists_in_id_order_before_clearing_them(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        """The order list creation and reordering take, so the delete cannot
        hold one of the owner's lists while waiting for another they hold."""
        trip = await insert_journal(async_connection)
        await save_associated(repository, "Packing", trip)

        with recorded_statements(async_connection) as statements:
            await repository.unassociate_journal(trip, USER_ID)

        lock, update = statements
        assert "FOR NO KEY UPDATE" in lock
        assert "ORDER BY id" in lock
        assert update.lstrip().startswith("UPDATE task_lists")

    async def test_the_count_is_the_owners_lists_on_the_journal(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        trip = await insert_journal(async_connection, "Trip")
        meeting = await insert_journal(async_connection, "Meeting")
        await save_associated(repository, "Packing", trip)
        await save_associated(repository, "Snacks", trip, archived_at=ARCHIVED_EARLIER)
        await save_associated(repository, "Agenda", meeting)
        await save_associated(repository, "Theirs", trip, user_id=OTHER_USER_ID)

        assert await repository.count_associated_with_journal(trip, USER_ID) == 2
        assert await repository.count_associated_with_journal(meeting, USER_ID) == 1
        assert await repository.count_associated_with_journal(trip, OTHER_USER_ID) == 1


class TestReassociateJournal:
    """A journal merge moves every list the owner has on the absorbed journal.

    A system write, so archived lists move too; nothing else is touched.
    """

    async def test_it_moves_every_owner_list_to_the_survivor(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        absorbed = await insert_journal(async_connection, "Absorbed")
        survivor = await insert_journal(async_connection, "Survivor")
        packing = await save_associated(repository, "Packing", absorbed)
        archived = await save_associated(
            repository, "Old packing", absorbed, archived_at=ARCHIVED_EARLIER
        )
        assert packing.id is not None
        assert archived.id is not None

        moved = await repository.reassociate_journal(
            source_journal_id=absorbed, target_journal_id=survivor, user_id=USER_ID
        )

        assert moved == sorted([packing.id, archived.id])
        assert await stored_association(async_connection, packing) == survivor
        assert await stored_association(async_connection, archived) == survivor
        found = await repository.find_by_id(archived.id, USER_ID)
        assert found is not None
        assert found.archived_at == ARCHIVED_EARLIER

    async def test_it_locks_the_lists_in_id_order_before_moving_them(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        """As the delete does, so a merge cannot cross a list create or reorder."""
        absorbed = await insert_journal(async_connection, "Absorbed")
        survivor = await insert_journal(async_connection, "Survivor")
        await save_associated(repository, "Packing", absorbed)

        with recorded_statements(async_connection) as statements:
            await repository.reassociate_journal(
                source_journal_id=absorbed, target_journal_id=survivor, user_id=USER_ID
            )

        lock, update = statements
        assert "FOR NO KEY UPDATE" in lock
        assert "ORDER BY id" in lock
        assert update.lstrip().startswith("UPDATE task_lists")

    async def test_lists_on_other_journals_and_other_users_are_untouched(
        self, repository: SqlTaskListRepository, async_connection: AsyncConnection
    ) -> None:
        absorbed = await insert_journal(async_connection, "Absorbed")
        survivor = await insert_journal(async_connection, "Survivor")
        meeting = await insert_journal(async_connection, "Meeting")
        agenda = await save_associated(repository, "Agenda", meeting)
        already = await save_associated(repository, "Already there", survivor)
        theirs = await save_associated(
            repository, "Theirs", absorbed, user_id=OTHER_USER_ID
        )

        moved = await repository.reassociate_journal(
            source_journal_id=absorbed, target_journal_id=survivor, user_id=USER_ID
        )

        assert moved == []
        assert await stored_association(async_connection, agenda) == meeting
        assert await stored_association(async_connection, already) == survivor
        assert await stored_association(async_connection, theirs) == absorbed


class TestDependencyInjection:
    """The repository is reachable through the container, not just importable."""

    async def test_task_provider_supplies_the_sql_adapter(
        self, async_connection: AsyncConnection
    ) -> None:
        container = make_task_container(async_connection)
        try:
            async with container() as request_container:
                repository = await request_container.get(TaskListRepository)

            assert isinstance(repository, SqlTaskListRepository)
        finally:
            await container.close()

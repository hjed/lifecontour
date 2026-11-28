"""Integration tests for creating and reading task lists, against real PostgreSQL.

``TaskListService`` owns the list writes — create, the field update, the
move, archive and unarchive. Create and the update are held to two promises: the list and its event are
written together, and a refused write leaves neither. The update adds a third: a
patch that changes nothing writes nothing and announces nothing. The move
publishes no event at all, and concurrent moves serialize on the owner's lists.
``TaskListReadService`` owns the reads and holds them to owner scoping: another user's list is reported exactly as a
missing one, and never listed.

Owner scoping is asserted against a second owner's real rows, for the reason the
repository tests give: an absent id cannot catch a missing ``user_id`` filter.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    MAX_TASK_LIST_NAME_LENGTH,
    LapseReason,
    TaskIcon,
    TaskList,
    TaskListArchivedError,
    TaskListArchiveFilter,
    TaskListBusyError,
    TaskListDeletion,
    TaskListListing,
    TaskListNotFoundError,
    TaskListValidationError,
    TaskNotFoundError,
    TaskStatus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_list_patch import TaskListPatch
from app.core.tasks.services.task_list_read_service import TaskListReadService
from app.core.tasks.services.task_list_service import TaskListService
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import bounded, overlap
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
    create_list_task,
    linked_contact_ids,
    make_task_container,
    seed_task_list,
    stored_status,
    task_events,
    task_exists,
    task_list_events,
)
from tests.task_list_service_factory import build_task_list_service

pytestmark = pytest.mark.integration

ARCHIVED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
_COUNT_LISTS = "SELECT COUNT(*) FROM task_lists WHERE user_id = :user_id"


def make_service(conn: AsyncConnection) -> TaskListService:
    return build_task_list_service(conn)


def make_read_service(conn: AsyncConnection) -> TaskListReadService:
    return TaskListReadService(
        task_list_repo=SqlTaskListRepository(conn), task_repo=SqlTaskRepository(conn)
    )


class TestCreateTaskList:
    @pytest.mark.asyncio
    async def test_creates_the_list_at_the_bottom_of_the_owners_lists(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_task_list(async_connection, "First")
        await seed_task_list(async_connection, "Archived", archived_at=ARCHIVED_AT)

        created = await make_service(async_connection).create_task_list(
            user_id=USER_ID,
            name="Packing",
            icon=TaskIcon.LUGGAGE,
            transaction=async_connection,
        )

        assert created.id is not None
        assert created.position == 2
        stored = await make_read_service(async_connection).get_task_list(
            user_id=USER_ID, task_list_id=created.id
        )
        assert stored == created
        assert (stored.name, stored.icon, stored.archived_at) == (
            "Packing",
            TaskIcon.LUGGAGE,
            None,
        )

    @pytest.mark.asyncio
    async def test_publishes_exactly_one_created_event_with_the_persisted_list(
        self, async_connection: AsyncConnection
    ) -> None:
        created = await make_service(async_connection).create_task_list(
            user_id=USER_ID,
            name="Packing",
            icon=TaskIcon.LUGGAGE,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        (event,) = await task_list_events(async_connection)
        assert event.event_type == "TaskListCreated"
        assert event.aggregate_id == created.id
        assert event.payload == {
            "task_list_id": created.id,
            "user_id": USER_ID,
            "name": "Packing",
            "icon": "luggage",
            "source": "ui",
            "changed_by": "ui",
        }

    @pytest.mark.asyncio
    async def test_a_list_without_an_icon_is_created_and_announced_with_none(
        self, async_connection: AsyncConnection
    ) -> None:
        created = await make_service(async_connection).create_task_list(
            user_id=USER_ID, name="Errands", icon=None, transaction=async_connection
        )

        assert created.icon is None
        (event,) = await task_list_events(async_connection)
        assert event.payload["icon"] is None
        assert event.payload["source"] == Provenance.SYSTEM.value

    @pytest.mark.asyncio
    async def test_a_refused_create_writes_no_list_and_no_event(
        self, async_connection: AsyncConnection
    ) -> None:
        service = make_service(async_connection)

        with pytest.raises(TaskListValidationError) as refused:
            await service.create_task_list(
                user_id=USER_ID, name="   ", icon=None, transaction=async_connection
            )

        assert refused.value.field == "name"
        assert await count(async_connection, _COUNT_LISTS, {"user_id": USER_ID}) == 0
        assert await task_list_events(async_connection) == []


async def _row(conn: AsyncConnection, task_list_id: int) -> dict[str, Any]:
    """The list's row exactly as stored, bypassing every layer above."""
    row = (
        await conn.execute(
            text("SELECT * FROM task_lists WHERE id = :id"), {"id": task_list_id}
        )
    ).one()
    return dict(row._mapping)


class TestUpdateTaskList:
    """Rename and icon: one patch, one locked read, one write, one event.

    ``updated_at`` is not asserted either way: the fixture runs every statement
    in one transaction, so ``now()`` is the same instant for the seed and the
    update and the timestamp cannot tell a write from a no-op. The stored
    fields and the outbox can.
    """

    @staticmethod
    async def _update(
        conn: AsyncConnection,
        task_list_id: int,
        patch: TaskListPatch,
        *,
        user_id: str = USER_ID,
    ) -> Any:
        return await make_service(conn).update_task_list(
            user_id=user_id,
            task_list_id=task_list_id,
            patch=patch,
            transaction=conn,
        )

    @pytest.mark.asyncio
    async def test_renames_a_list_and_keeps_its_icon(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE
        )
        assert seeded.id is not None

        updated = await self._update(
            async_connection, seeded.id, TaskListPatch(name="Trip packing")
        )

        assert (updated.name, updated.icon) == ("Trip packing", TaskIcon.LUGGAGE)
        stored = await make_read_service(async_connection).get_task_list(
            user_id=USER_ID, task_list_id=seeded.id
        )
        assert stored == updated
        (event,) = await task_list_events(async_connection, task_list_id=seeded.id)
        assert event.event_type == "TaskListUpdated"
        assert event.payload["changed_fields"] == {"name": ["Packing", "Trip packing"]}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("before", "after"),
        [
            (None, TaskIcon.LUGGAGE),
            (TaskIcon.LUGGAGE, TaskIcon.SHOPPING_CART),
            (TaskIcon.LUGGAGE, None),
        ],
        ids=["set", "replace", "clear"],
    )
    async def test_sets_replaces_or_clears_the_icon_and_keeps_the_name(
        self,
        async_connection: AsyncConnection,
        before: TaskIcon | None,
        after: TaskIcon | None,
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing", icon=before)
        assert seeded.id is not None

        updated = await self._update(
            async_connection, seeded.id, TaskListPatch(icon=after)
        )

        assert (updated.name, updated.icon) == ("Packing", after)
        assert (await _row(async_connection, seeded.id))["icon"] == (
            after.value if after is not None else None
        )
        (event,) = await task_list_events(async_connection, task_list_id=seeded.id)
        assert event.payload["changed_fields"] == {
            "icon": [
                before.value if before is not None else None,
                after.value if after is not None else None,
            ]
        }

    @pytest.mark.asyncio
    async def test_name_and_icon_together_are_one_write_and_one_event(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None

        await make_service(async_connection).update_task_list(
            user_id=USER_ID,
            task_list_id=seeded.id,
            patch=TaskListPatch(name="Trip", icon=TaskIcon.LUGGAGE),
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        (event,) = await task_list_events(async_connection)
        assert event.aggregate_id == seeded.id
        assert event.payload == {
            "task_list_id": seeded.id,
            "user_id": USER_ID,
            "changed_fields": {
                "name": ["Packing", "Trip"],
                "icon": [None, "luggage"],
            },
            "source": "ui",
            "changed_by": "ui",
        }

    @pytest.mark.asyncio
    async def test_provenance_defaults_to_system(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None

        await self._update(async_connection, seeded.id, TaskListPatch(name="Trip"))

        (event,) = await task_list_events(async_connection)
        assert (event.payload["source"], event.payload["changed_by"]) == (
            Provenance.SYSTEM.value,
            "system",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "patch",
        [
            TaskListPatch(),
            TaskListPatch(name="Packing"),
            TaskListPatch(icon=TaskIcon.LUGGAGE),
            TaskListPatch(name="Packing", icon=TaskIcon.LUGGAGE),
        ],
        ids=["empty", "same-name", "same-icon", "same-both"],
    )
    async def test_a_patch_that_changes_nothing_publishes_nothing(
        self, async_connection: AsyncConnection, patch: TaskListPatch
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE
        )
        assert seeded.id is not None
        before = await _row(async_connection, seeded.id)

        unchanged = await self._update(async_connection, seeded.id, patch)

        assert unchanged == seeded
        assert await _row(async_connection, seeded.id) == before
        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_clearing_an_icon_that_is_not_set_publishes_nothing(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None

        await self._update(async_connection, seeded.id, TaskListPatch(icon=None))

        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", ["", "   ", "x" * (MAX_TASK_LIST_NAME_LENGTH + 1)])
    async def test_a_refused_name_writes_nothing(
        self, async_connection: AsyncConnection, name: str
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE
        )
        assert seeded.id is not None
        before = await _row(async_connection, seeded.id)

        with pytest.raises(TaskListValidationError) as refused:
            await self._update(
                async_connection,
                seeded.id,
                TaskListPatch(name=name, icon=TaskIcon.SHOPPING_CART),
            )

        assert refused.value.field == "name"
        assert await _row(async_connection, seeded.id) == before
        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_a_missing_list_is_not_found(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(TaskListNotFoundError) as missing:
            await self._update(async_connection, 999_999, TaskListPatch(name="X"))

        assert str(missing.value) == "Task list with ID 999999 not found"
        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_another_users_list_is_refused_as_missing_and_left_alone(
        self, async_connection: AsyncConnection
    ) -> None:
        foreign = await seed_task_list(
            async_connection, "Theirs", user_id=OTHER_USER_ID, icon=TaskIcon.LUGGAGE
        )
        assert foreign.id is not None
        before = await _row(async_connection, foreign.id)

        with pytest.raises(TaskListNotFoundError) as refused:
            await self._update(
                async_connection, foreign.id, TaskListPatch(name="Mine", icon=None)
            )

        assert str(refused.value) == f"Task list with ID {foreign.id} not found"
        assert await _row(async_connection, foreign.id) == before
        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "patch",
        [
            TaskListPatch(name="Renamed"),
            TaskListPatch(icon=TaskIcon.SHOPPING_CART),
            TaskListPatch(icon=None),
            TaskListPatch(name="Packing"),
        ],
        ids=["rename", "set-icon", "clear-icon", "no-op"],
    )
    async def test_an_archived_list_refuses_every_update_and_writes_nothing(
        self, async_connection: AsyncConnection, patch: TaskListPatch
    ) -> None:
        """Even a patch that would change nothing is refused: an archived list
        is read-only, not merely unchanged."""
        seeded = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE, archived_at=ARCHIVED_AT
        )
        assert seeded.id is not None
        before = await _row(async_connection, seeded.id)

        with pytest.raises(TaskListArchivedError) as refused:
            await self._update(async_connection, seeded.id, patch)

        assert refused.value.task_list_id == seeded.id
        assert await _row(async_connection, seeded.id) == before
        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_an_unarchived_list_can_be_renamed_again(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", archived_at=ARCHIVED_AT
        )
        assert seeded.id is not None
        await make_service(async_connection).unarchive_task_list(
            user_id=USER_ID, task_list_id=seeded.id, transaction=async_connection
        )

        renamed = await self._update(
            async_connection, seeded.id, TaskListPatch(name="Trip")
        )

        assert renamed.name == "Trip"


_COUNT_OUTBOX = "SELECT COUNT(*) FROM outbox_events"
_STORED_ORDER = text(
    "SELECT id, position FROM task_lists WHERE user_id = :user_id ORDER BY position, id"
)


async def stored_order(conn: AsyncConnection, user_id: str = USER_ID) -> list[int]:
    rows = await conn.execute(_STORED_ORDER, {"user_id": user_id})
    return [row.id for row in rows]


async def stored_positions(
    conn: AsyncConnection, user_id: str = USER_ID
) -> list[tuple[int, int]]:
    rows = await conn.execute(_STORED_ORDER, {"user_id": user_id})
    return [(row.id, row.position) for row in rows]


def list_ids(task_lists: list[TaskList]) -> list[int | None]:
    return [task_list.id for task_list in task_lists]


async def seed_lists(conn: AsyncConnection, *names: str) -> list[int]:
    seeded = [await seed_task_list(conn, name) for name in names]
    return [each.id for each in seeded if each.id is not None]


class TestMoveTaskList:
    @pytest.mark.asyncio
    async def test_moves_the_list_and_answers_the_active_lists_in_their_new_order(
        self, async_connection: AsyncConnection
    ) -> None:
        a, b, c = await seed_lists(async_connection, "A", "B", "C")

        moved = await make_service(async_connection).move_task_list(
            user_id=USER_ID, task_list_id=a, index=2, transaction=async_connection
        )

        assert list_ids(moved) == [b, c, a]
        assert [each.position for each in moved] == [0, 1, 2]
        assert await stored_positions(async_connection) == [(b, 0), (c, 1), (a, 2)]

    @pytest.mark.asyncio
    async def test_archived_lists_keep_their_place_and_are_not_answered(
        self, async_connection: AsyncConnection
    ) -> None:
        a = (await seed_task_list(async_connection, "A")).id
        archived = (
            await seed_task_list(async_connection, "Gone", archived_at=ARCHIVED_AT)
        ).id
        b, c = await seed_lists(async_connection, "B", "C")

        moved = await make_service(async_connection).move_task_list(
            user_id=USER_ID, task_list_id=c, index=1, transaction=async_connection
        )

        # Index 1 counts active lists only: C lands before B, after the archived.
        assert list_ids(moved) == [a, c, b]
        assert await stored_order(async_connection) == [a, archived, c, b]

    @pytest.mark.asyncio
    async def test_an_index_past_the_end_moves_the_list_to_the_bottom(
        self, async_connection: AsyncConnection
    ) -> None:
        a, b, c = await seed_lists(async_connection, "A", "B", "C")

        moved = await make_service(async_connection).move_task_list(
            user_id=USER_ID, task_list_id=a, index=1_000, transaction=async_connection
        )

        assert list_ids(moved) == [b, c, a]

    @pytest.mark.asyncio
    async def test_moving_a_list_to_its_own_place_changes_nothing(
        self, async_connection: AsyncConnection
    ) -> None:
        a, b, c = await seed_lists(async_connection, "A", "B", "C")

        moved = await make_service(async_connection).move_task_list(
            user_id=USER_ID, task_list_id=b, index=1, transaction=async_connection
        )

        assert list_ids(moved) == [a, b, c]
        assert await stored_positions(async_connection) == [(a, 0), (b, 1), (c, 2)]

    @pytest.mark.asyncio
    async def test_a_move_publishes_no_event(
        self, async_connection: AsyncConnection
    ) -> None:
        """The spec keeps reordering out of history, so nothing is announced."""
        a, _, _ = await seed_lists(async_connection, "A", "B", "C")

        await make_service(async_connection).move_task_list(
            user_id=USER_ID, task_list_id=a, index=2, transaction=async_connection
        )

        assert await count(async_connection, _COUNT_OUTBOX, {}) == 0

    @pytest.mark.asyncio
    async def test_another_users_lists_are_not_renumbered(
        self, async_connection: AsyncConnection
    ) -> None:
        theirs_first = await seed_task_list(
            async_connection, "Theirs 1", user_id=OTHER_USER_ID
        )
        theirs_second = await seed_task_list(
            async_connection, "Theirs 2", user_id=OTHER_USER_ID
        )
        a, _ = await seed_lists(async_connection, "A", "B")
        before = await stored_positions(async_connection, OTHER_USER_ID)

        await make_service(async_connection).move_task_list(
            user_id=USER_ID, task_list_id=a, index=1, transaction=async_connection
        )

        assert before == [(theirs_first.id, 0), (theirs_second.id, 1)]
        assert await stored_positions(async_connection, OTHER_USER_ID) == before

    @pytest.mark.asyncio
    async def test_a_missing_list_is_not_found(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_lists(async_connection, "A")

        with pytest.raises(TaskListNotFoundError) as missing:
            await make_service(async_connection).move_task_list(
                user_id=USER_ID,
                task_list_id=999_999,
                index=0,
                transaction=async_connection,
            )

        assert missing.value.task_list_id == 999_999

    @pytest.mark.asyncio
    async def test_another_users_list_is_not_found_and_not_moved(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_task_list(async_connection, "Theirs 1", user_id=OTHER_USER_ID)
        theirs = await seed_task_list(
            async_connection, "Theirs 2", user_id=OTHER_USER_ID
        )
        assert theirs.id is not None
        mine = await seed_lists(async_connection, "A", "B")
        their_positions = await stored_positions(async_connection, OTHER_USER_ID)
        my_positions = await stored_positions(async_connection)

        with pytest.raises(TaskListNotFoundError) as refused:
            await make_service(async_connection).move_task_list(
                user_id=USER_ID,
                task_list_id=theirs.id,
                index=0,
                transaction=async_connection,
            )

        assert str(refused.value) == f"Task list with ID {theirs.id} not found"
        assert await stored_positions(async_connection, OTHER_USER_ID) == (
            their_positions
        )
        assert await stored_order(async_connection) == mine
        assert await stored_positions(async_connection) == my_positions

    @pytest.mark.asyncio
    async def test_an_archived_list_cannot_be_moved(
        self, async_connection: AsyncConnection
    ) -> None:
        a = (await seed_task_list(async_connection, "A")).id
        archived = await seed_task_list(
            async_connection, "Gone", archived_at=ARCHIVED_AT
        )
        assert archived.id is not None
        before = await stored_positions(async_connection)

        with pytest.raises(TaskListArchivedError) as refused:
            await make_service(async_connection).move_task_list(
                user_id=USER_ID,
                task_list_id=archived.id,
                index=0,
                transaction=async_connection,
            )

        assert refused.value.task_list_id == archived.id
        assert await stored_positions(async_connection) == before
        assert before[0] == (a, 0)


_RACE_LISTS = text(
    "SELECT id FROM task_lists WHERE user_id = :user_id ORDER BY position, id"
)


@asynccontextmanager
async def committed_lists(
    async_engine: AsyncEngine, *names: str
) -> AsyncIterator[tuple[str, list[int]]]:
    """Commit lists for a one-off owner, and delete them afterwards.

    Two transactions can only overlap on rows both can see, which the savepoint
    fixture's rows are not.
    """
    owner = f"reorder-race-{uuid.uuid4()}"
    async with async_engine.begin() as setup:
        repo = SqlTaskListRepository(setup)
        saved = [await repo.save(TaskList(user_id=owner, name=n)) for n in names]
    try:
        yield owner, [each.id for each in saved if each.id is not None]
    finally:
        async with async_engine.begin() as cleanup:
            await cleanup.execute(
                text("DELETE FROM task_lists WHERE user_id = :user_id"),
                {"user_id": owner},
            )


@pytest.mark.integration
class TestConcurrentMoves:
    @pytest.mark.asyncio
    async def test_a_move_during_another_waits_for_it_and_builds_on_its_order(
        self, async_engine: AsyncEngine
    ) -> None:
        """Without the lock the second move reads the order from before the
        first and writes it back, undoing the first move."""
        async with committed_lists(async_engine, "A", "B", "C") as (owner, ids):
            a, b, c = ids

            async def move(list_id: int, index: int) -> Any:
                async def run(connection: AsyncConnection) -> None:
                    await make_service(connection).move_task_list(
                        user_id=owner,
                        task_list_id=list_id,
                        index=index,
                        transaction=connection,
                    )

                return run

            # First: A to the bottom → B, C, A. Second: C to the top → C, B, A.
            await overlap(async_engine, await move(a, 2), await move(c, 0))

            async with async_engine.connect() as check:
                rows = await check.execute(_RACE_LISTS, {"user_id": owner})
                assert [row.id for row in rows] == [c, b, a]


@pytest.mark.integration
class TestConcurrentArchives:
    @pytest.mark.asyncio
    async def test_an_archive_during_another_waits_and_records_nothing(
        self, async_engine: AsyncEngine
    ) -> None:
        """Without the row lock both archives read the list as active, both
        write, and the second overwrites the first instant and publishes a
        second ``(null, ts)`` event."""
        async with committed_lists(async_engine, "Packing") as (owner, ids):
            (list_id,) = ids

            def archive() -> Any:
                async def run(connection: AsyncConnection) -> None:
                    await make_service(connection).archive_task_list(
                        user_id=owner, task_list_id=list_id, transaction=connection
                    )

                return run

            try:
                await overlap(async_engine, archive(), archive())

                async with async_engine.connect() as check:
                    events = (
                        await check.execute(_OWNER_EVENTS, {"user_id": owner})
                    ).all()
                    archived_at = (
                        await check.execute(
                            text("SELECT archived_at FROM task_lists WHERE id = :id"),
                            {"id": list_id},
                        )
                    ).scalar_one()
                assert len(events) == 1
                old, new = json.loads(events[0].event_data)["changed_fields"][
                    "archived_at"
                ]
                assert old is None
                assert new == archived_at.isoformat()
            finally:
                async with async_engine.begin() as cleanup:
                    await cleanup.execute(_DELETE_OWNER_EVENTS, {"user_id": owner})


_OWNER_EVENTS = text(
    "SELECT event_data FROM outbox_events "
    "WHERE event_type = 'TaskListUpdated' "
    "AND CAST(event_data AS jsonb) ->> 'user_id' = :user_id"
)
_DELETE_OWNER_EVENTS = text(
    "DELETE FROM outbox_events WHERE CAST(event_data AS jsonb) ->> 'user_id' = :user_id"
)


@pytest.mark.integration
class TestMovesAndCreatesSerialize:
    """A create racing a move must still land at the bottom, and the move must
    still put its list at the index asked for.

    Both start from tied positions — which concurrent creates have always been
    allowed to leave — because a move then lowers the highest position: from
    ``A=0, B=0, C=0`` it writes ``B=0, C=1, A=2``. A create that read the old
    highest (0) would insert ``D=1`` beside ``C``, and a move that read the
    lists before the create committed would renumber around ``D``; either way
    the order comes out ``B, C, D, A`` instead of ``B, C, A, D``.
    """

    @staticmethod
    async def _tie_positions(async_engine: AsyncEngine, owner: str) -> None:
        async with async_engine.begin() as setup:
            await setup.execute(
                text("UPDATE task_lists SET position = 0 WHERE user_id = :user_id"),
                {"user_id": owner},
            )

    @staticmethod
    def _move(owner: str, list_id: int, index: int) -> Any:
        async def run(connection: AsyncConnection) -> None:
            await make_service(connection).move_task_list(
                user_id=owner,
                task_list_id=list_id,
                index=index,
                transaction=connection,
            )

        return run

    @staticmethod
    def _create(owner: str, name: str) -> Any:
        async def run(connection: AsyncConnection) -> None:
            async with unit_of_work(connection):
                await SqlTaskListRepository(connection).save(
                    TaskList(user_id=owner, name=name)
                )

        return run

    @staticmethod
    async def _order(async_engine: AsyncEngine, owner: str) -> list[str]:
        async with async_engine.connect() as check:
            rows = await check.execute(
                text(
                    "SELECT name FROM task_lists WHERE user_id = :user_id "
                    "ORDER BY position, id"
                ),
                {"user_id": owner},
            )
            return [row.name for row in rows]

    @pytest.mark.asyncio
    async def test_a_create_during_a_move_waits_and_lands_after_the_moved_list(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_lists(async_engine, "A", "B", "C") as (owner, ids):
            await self._tie_positions(async_engine, owner)

            await overlap(
                async_engine,
                self._move(owner, ids[0], 2),
                self._create(owner, "D"),
            )

            assert await self._order(async_engine, owner) == ["B", "C", "A", "D"]

    @pytest.mark.asyncio
    async def test_a_move_during_a_create_waits_and_counts_the_new_list(
        self, async_engine: AsyncEngine
    ) -> None:
        async with committed_lists(async_engine, "A", "B", "C") as (owner, ids):
            await self._tie_positions(async_engine, owner)

            await overlap(
                async_engine,
                self._create(owner, "D"),
                self._move(owner, ids[0], 2),
            )

            assert await self._order(async_engine, owner) == ["B", "C", "A", "D"]


async def _task_row(conn: AsyncConnection, task_id: int) -> dict[str, Any]:
    """A task's row exactly as stored, to prove an archive leaves it alone."""
    row = (
        await conn.execute(text("SELECT * FROM tasks WHERE id = :id"), {"id": task_id})
    ).one()
    return dict(row._mapping)


class TestArchiveTaskList:
    """Archiving: one locked read, one write, one ``TaskListUpdated``.

    The list's tasks are untouched — archiving changes the list, not its
    contents — and archiving an archived list is a no-op that keeps the
    instant it was first archived.
    """

    @staticmethod
    async def _archive(
        conn: AsyncConnection, task_list_id: int, *, user_id: str = USER_ID
    ) -> TaskList:
        return await make_service(conn).archive_task_list(
            user_id=user_id, task_list_id=task_list_id, transaction=conn
        )

    @pytest.mark.asyncio
    async def test_archives_the_list_and_keeps_its_name_icon_and_place(
        self, async_connection: AsyncConnection
    ) -> None:
        await seed_task_list(async_connection, "First")
        seeded = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE
        )
        assert seeded.id is not None

        archived = await self._archive(async_connection, seeded.id)

        assert archived.is_archived
        assert archived.archived_at is not None
        assert archived.archived_at.tzinfo is not None
        assert (archived.name, archived.icon, archived.position) == (
            "Packing",
            TaskIcon.LUGGAGE,
            seeded.position,
        )
        stored = await _row(async_connection, seeded.id)
        assert stored["archived_at"] == archived.archived_at
        assert stored["position"] == seeded.position

    @pytest.mark.asyncio
    async def test_publishes_one_updated_event_carrying_archived_at(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None

        archived = await self._archive(async_connection, seeded.id)

        assert archived.archived_at is not None
        (event,) = await task_list_events(async_connection)
        assert event.event_type == "TaskListUpdated"
        assert event.aggregate_id == seeded.id
        assert event.payload == {
            "task_list_id": seeded.id,
            "user_id": USER_ID,
            "changed_fields": {"archived_at": [None, archived.archived_at.isoformat()]},
            "source": Provenance.SYSTEM.value,
            "changed_by": "system",
        }

    @pytest.mark.asyncio
    async def test_a_list_with_an_open_task_is_archived_and_the_task_untouched(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None
        task_id = await create_list_task(async_connection, task_list_id=seeded.id)
        task_before = await _task_row(async_connection, task_id)

        archived = await self._archive(async_connection, seeded.id)

        assert archived.is_archived
        assert await stored_status(async_connection, task_id) == "not_done"
        assert await _task_row(async_connection, task_id) == task_before
        assert await task_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_archiving_an_archived_list_keeps_its_instant_and_records_nothing(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", archived_at=ARCHIVED_AT
        )
        assert seeded.id is not None
        before = await _row(async_connection, seeded.id)

        again = await self._archive(async_connection, seeded.id)

        assert again.archived_at == ARCHIVED_AT
        assert await _row(async_connection, seeded.id) == before
        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_provenance_is_carried(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None

        await make_service(async_connection).archive_task_list(
            user_id=USER_ID,
            task_list_id=seeded.id,
            transaction=async_connection,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        (event,) = await task_list_events(async_connection)
        assert (event.payload["source"], event.payload["changed_by"]) == ("mcp", "mcp")

    @pytest.mark.asyncio
    async def test_a_missing_list_is_not_found(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(TaskListNotFoundError):
            await self._archive(async_connection, 999_999)

        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_another_users_list_is_refused_as_missing_and_left_alone(
        self, async_connection: AsyncConnection
    ) -> None:
        foreign = await seed_task_list(
            async_connection, "Theirs", user_id=OTHER_USER_ID
        )
        assert foreign.id is not None
        before = await _row(async_connection, foreign.id)

        with pytest.raises(TaskListNotFoundError) as refused:
            await self._archive(async_connection, foreign.id)

        assert str(refused.value) == f"Task list with ID {foreign.id} not found"
        assert await _row(async_connection, foreign.id) == before
        assert await task_list_events(async_connection) == []


class TestUnarchiveTaskList:
    """Unarchiving restores the list: back among the active lists, in its old
    place, and writable again."""

    @staticmethod
    async def _unarchive(
        conn: AsyncConnection, task_list_id: int, *, user_id: str = USER_ID
    ) -> TaskList:
        return await make_service(conn).unarchive_task_list(
            user_id=user_id, task_list_id=task_list_id, transaction=conn
        )

    @pytest.mark.asyncio
    async def test_unarchives_the_list_back_into_its_old_place(
        self, async_connection: AsyncConnection
    ) -> None:
        first = await seed_task_list(async_connection, "First")
        middle = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE, archived_at=ARCHIVED_AT
        )
        last = await seed_task_list(async_connection, "Last")
        assert middle.id is not None

        restored = await self._unarchive(async_connection, middle.id)

        assert not restored.is_archived
        assert (restored.name, restored.icon, restored.position) == (
            "Packing",
            TaskIcon.LUGGAGE,
            middle.position,
        )
        active = await make_read_service(async_connection).list_task_lists(
            user_id=USER_ID,
            listing=TaskListListing(archived=TaskListArchiveFilter.ACTIVE),
        )
        assert [each.task_list.id for each in active.summaries] == [
            first.id,
            middle.id,
            last.id,
        ]
        assert (await _row(async_connection, middle.id))["archived_at"] is None

    @pytest.mark.asyncio
    async def test_publishes_one_updated_event_clearing_archived_at(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", archived_at=ARCHIVED_AT
        )
        assert seeded.id is not None

        await make_service(async_connection).unarchive_task_list(
            user_id=USER_ID,
            task_list_id=seeded.id,
            transaction=async_connection,
            source=Provenance.UI,
            changed_by="ui",
        )

        (event,) = await task_list_events(async_connection)
        assert event.event_type == "TaskListUpdated"
        assert event.payload == {
            "task_list_id": seeded.id,
            "user_id": USER_ID,
            "changed_fields": {"archived_at": [ARCHIVED_AT.isoformat(), None]},
            "source": "ui",
            "changed_by": "ui",
        }

    @pytest.mark.asyncio
    async def test_unarchiving_an_active_list_records_nothing(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None
        before = await _row(async_connection, seeded.id)

        unchanged = await self._unarchive(async_connection, seeded.id)

        assert unchanged == seeded
        assert await _row(async_connection, seeded.id) == before
        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_archive_then_unarchive_round_trips(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None
        await TestArchiveTaskList._archive(async_connection, seeded.id)

        restored = await self._unarchive(async_connection, seeded.id)

        assert not restored.is_archived
        assert restored.position == seeded.position
        archived_event, unarchived_event = await task_list_events(async_connection)
        archived_pair = archived_event.payload["changed_fields"]["archived_at"]
        assert archived_pair[0] is None
        assert unarchived_event.payload["changed_fields"] == {
            "archived_at": [archived_pair[1], None]
        }

    @pytest.mark.asyncio
    async def test_a_missing_list_is_not_found(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(TaskListNotFoundError):
            await self._unarchive(async_connection, 999_999)

        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_another_users_list_is_refused_as_missing_and_left_archived(
        self, async_connection: AsyncConnection
    ) -> None:
        foreign = await seed_task_list(
            async_connection, "Theirs", user_id=OTHER_USER_ID, archived_at=ARCHIVED_AT
        )
        assert foreign.id is not None
        before = await _row(async_connection, foreign.id)

        with pytest.raises(TaskListNotFoundError):
            await self._unarchive(async_connection, foreign.id)

        assert await _row(async_connection, foreign.id) == before
        assert await task_list_events(async_connection) == []


class TestGetTaskList:
    @pytest.mark.asyncio
    async def test_reads_back_an_owned_list(
        self, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Groceries", icon=TaskIcon.SHOPPING_CART
        )
        assert seeded.id is not None

        found = await make_read_service(async_connection).get_task_list(
            user_id=USER_ID, task_list_id=seeded.id
        )

        assert found == seeded

    @pytest.mark.asyncio
    async def test_a_missing_list_is_not_found(
        self, async_connection: AsyncConnection
    ) -> None:
        read_service = make_read_service(async_connection)

        with pytest.raises(TaskListNotFoundError) as missing:
            await read_service.get_task_list(user_id=USER_ID, task_list_id=999_999)

        assert missing.value.task_list_id == 999_999

    @pytest.mark.asyncio
    async def test_another_users_list_is_reported_exactly_as_a_missing_one(
        self, async_connection: AsyncConnection
    ) -> None:
        foreign = await seed_task_list(
            async_connection, "Theirs", user_id=OTHER_USER_ID
        )
        assert foreign.id is not None

        read_service = make_read_service(async_connection)

        with pytest.raises(TaskListNotFoundError) as refused:
            await read_service.get_task_list(user_id=USER_ID, task_list_id=foreign.id)

        # The same words a missing id gets: nothing says the list exists.
        assert str(refused.value) == f"Task list with ID {foreign.id} not found"


class TestListTaskLists:
    @pytest.mark.asyncio
    async def test_each_filter_returns_its_lists_in_the_repository_order(
        self, async_connection: AsyncConnection
    ) -> None:
        first = await seed_task_list(async_connection, "First")
        archived = await seed_task_list(
            async_connection, "Archived", archived_at=ARCHIVED_AT
        )
        second = await seed_task_list(async_connection, "Second")
        service = make_read_service(async_connection)

        async def names(archived_filter: TaskListArchiveFilter) -> list[str]:
            lists = await service.list_task_lists(
                user_id=USER_ID, listing=TaskListListing(archived=archived_filter)
            )
            return [each.task_list.name for each in lists.summaries]

        assert await names(TaskListArchiveFilter.ACTIVE) == [first.name, second.name]
        assert await names(TaskListArchiveFilter.ARCHIVED) == [archived.name]
        assert await names(TaskListArchiveFilter.ALL) == [
            first.name,
            archived.name,
            second.name,
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("archived_filter", list(TaskListArchiveFilter))
    async def test_another_users_lists_are_never_returned(
        self,
        async_connection: AsyncConnection,
        archived_filter: TaskListArchiveFilter,
    ) -> None:
        await seed_task_list(async_connection, "Theirs", user_id=OTHER_USER_ID)
        await seed_task_list(
            async_connection,
            "Theirs archived",
            user_id=OTHER_USER_ID,
            archived_at=ARCHIVED_AT,
        )

        lists = await make_read_service(async_connection).list_task_lists(
            user_id=USER_ID, listing=TaskListListing(archived=archived_filter)
        )

        assert lists.summaries == ()
        assert lists.total == 0


class TestWiring:
    @pytest.mark.asyncio
    async def test_the_container_provides_both_services(
        self, async_connection: AsyncConnection
    ) -> None:
        container = make_task_container(async_connection)
        try:
            async with container() as request_container:
                service = await request_container.get(TaskListService)
                read_service = await request_container.get(TaskListReadService)

            assert isinstance(service, TaskListService)
            assert isinstance(read_service, TaskListReadService)
        finally:
            await container.close()


# --------------------------------------------------------------------------- #
# Deleting a list
# --------------------------------------------------------------------------- #


async def _delete(
    conn: AsyncConnection,
    task_list_id: int,
    *,
    user_id: str = USER_ID,
    source: Provenance = Provenance.UI,
    changed_by: str = "ui",
) -> TaskListDeletion:
    return await make_service(conn).delete_task_list(
        user_id=user_id,
        task_list_id=task_list_id,
        transaction=conn,
        source=source,
        changed_by=changed_by,
    )


async def _list_exists(conn: AsyncConnection, task_list_id: int) -> bool:
    return (
        await count(
            conn,
            "SELECT COUNT(*) FROM task_lists WHERE id = :id",
            {"id": task_list_id},
        )
        == 1
    )


async def _seeded_list(
    conn: AsyncConnection, name: str = "Packing", **kwargs: Any
) -> int:
    seeded = await seed_task_list(conn, name, **kwargs)
    assert seeded.id is not None
    return seeded.id


class TestDeleteTaskList:
    @pytest.mark.asyncio
    async def test_an_empty_list_is_deleted_and_announced_once(
        self, async_connection: AsyncConnection
    ) -> None:
        list_id = await _seeded_list(async_connection)

        deletion = await _delete(async_connection, list_id)

        assert deletion == TaskListDeletion(
            task_list_id=list_id, deleted_task_ids=(), kept_task_ids=()
        )
        assert not await _list_exists(async_connection, list_id)
        (event,) = await task_list_events(async_connection, task_list_id=list_id)
        assert event.event_type == "TaskListDeleted"
        assert event.payload == {
            "task_list_id": list_id,
            "user_id": USER_ID,
            "name": "Packing",
            "deleted_task_count": 0,
            "kept_task_count": 0,
            "source": "ui",
            "changed_by": "ui",
        }

    @pytest.mark.asyncio
    async def test_tasks_are_deleted_or_kept_and_each_is_announced(
        self, async_connection: AsyncConnection, journal_repository: Any
    ) -> None:
        list_id = await _seeded_list(async_connection)
        creating_id = await create_journal(journal_repository, title="Arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        open_task = await create_list_task(async_connection, task_list_id=list_id)
        done_task = await create_list_task(
            async_connection, task_list_id=list_id, position=1, status=TaskStatus.DONE
        )
        kept = await create_list_task(
            async_connection,
            task_list_id=list_id,
            position=2,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        deletion = await _delete(
            async_connection, list_id, source=Provenance.MCP, changed_by="mcp"
        )

        assert deletion.deleted_task_ids == (open_task, done_task)
        assert deletion.kept_task_ids == (kept,)
        assert not await task_exists(async_connection, open_task)
        assert not await task_exists(async_connection, done_task)
        assert await task_exists(async_connection, kept)
        events = await task_events(async_connection)
        assert [(e.event_type, e.aggregate_id) for e in events] == [
            ("TaskDeleted", open_task),
            ("TaskDeleted", done_task),
            ("TaskListMembershipChanged", kept),
        ]
        assert events[2].payload["changed_fields"] == {"task_list_id": [list_id, None]}
        assert {e.payload["source"] for e in events} == {"mcp"}
        (list_event,) = await task_list_events(async_connection, task_list_id=list_id)
        assert (
            list_event.payload["deleted_task_count"],
            list_event.payload["kept_task_count"],
        ) == (2, 1)

    @pytest.mark.asyncio
    async def test_a_kept_task_whose_journal_has_passed_reads_as_lapsed(
        self,
        async_connection: AsyncConnection,
        journal_repository: Any,
        read_service: TaskReadService,
    ) -> None:
        """Lapse is derived on read, so leaving the list is all it takes."""
        list_id = await _seeded_list(async_connection)
        creating_id = await create_journal(
            journal_repository, title="Arose", days_offset=-10
        )
        due_id = await create_journal(journal_repository, title="Due", days_offset=-3)
        kept = await create_list_task(
            async_connection,
            task_list_id=list_id,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        await _delete(async_connection, list_id)

        model = await read_service.read_model(USER_ID, kept)
        assert model.task.task_list_id is None
        assert model.lapse_reason == LapseReason.DATE_PASSED

    @pytest.mark.asyncio
    async def test_an_archived_list_is_refused_and_nothing_changes(
        self, async_connection: AsyncConnection
    ) -> None:
        list_id = await _seeded_list(async_connection, archived_at=ARCHIVED_AT)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        with pytest.raises(TaskListArchivedError):
            await _delete(async_connection, list_id)

        assert await _list_exists(async_connection, list_id)
        assert await task_exists(async_connection, task_id)
        assert await task_list_events(async_connection) == []
        assert await task_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_a_missing_or_foreign_list_is_not_found_and_nothing_changes(
        self, async_connection: AsyncConnection
    ) -> None:
        theirs = await _seeded_list(async_connection, "Theirs", user_id=OTHER_USER_ID)
        their_task = await create_list_task(
            async_connection, task_list_id=theirs, user_id=OTHER_USER_ID
        )

        with pytest.raises(TaskListNotFoundError):
            await _delete(async_connection, theirs)
        with pytest.raises(TaskListNotFoundError):
            await _delete(async_connection, 999_999)

        assert await _list_exists(async_connection, theirs)
        assert await task_exists(async_connection, their_task)
        assert await task_list_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_the_owners_other_lists_keep_their_order(
        self, async_connection: AsyncConnection
    ) -> None:
        first, middle, last = await seed_lists(async_connection, "A", "B", "C")

        await _delete(async_connection, middle)

        assert await stored_order(async_connection) == [first, last]


def _race_owner() -> str:
    """A one-off owner, so committed rows can be cleaned up by owner."""
    return f"delete-race-{uuid.uuid4()}"


async def _cleanup_owner(async_engine: AsyncEngine, owner: str) -> None:
    async with async_engine.begin() as cleanup:
        await cleanup.execute(_DELETE_OWNER_EVENTS, {"user_id": owner})
        for table in ("tasks", "task_lists", "journals", "contacts"):
            await cleanup.execute(
                text(f"DELETE FROM {table} WHERE user_id = :user_id"),  # noqa: S608
                {"user_id": owner},
            )


def _task_service(conn: AsyncConnection) -> TaskService:
    return TaskService(
        task_repo=SqlTaskRepository(conn),
        task_list_repo=SqlTaskListRepository(conn),
        journal_repo=SqlJournalRepository(conn),
        contact_repo=SqlContactRepository(conn),
        date_resolver=JournalDateResolver(
            user_settings_repo=SqlUserSettingsRepository(conn)
        ),
        event_publisher=OutboxEventPublisher(conn),
    )


@pytest.mark.integration
@pytest.mark.slow
class TestConcurrentDeletes:
    """A delete queues against every other write on its list and never
    deadlocks; whichever runs second sees what the first left."""

    @staticmethod
    async def _seed(
        async_engine: AsyncEngine, owner: str, task_count: int
    ) -> tuple[int, list[int]]:
        async with async_engine.begin() as setup:
            list_id = await _seeded_list(setup, "Racing", user_id=owner)
            ids = [
                await create_list_task(
                    setup, task_list_id=list_id, position=index, user_id=owner
                )
                for index in range(task_count)
            ]
        return list_id, ids

    @staticmethod
    def _deleting(owner: str, list_id: int) -> Any:
        async def run(connection: AsyncConnection) -> None:
            await _delete(connection, list_id, user_id=owner)

        return run

    @pytest.mark.asyncio
    async def test_a_status_edit_during_the_delete_waits_then_finds_no_task(
        self, async_engine: AsyncEngine
    ) -> None:
        owner = _race_owner()
        try:
            list_id, (task_id,) = await self._seed(async_engine, owner, 1)
            outcome: list[BaseException] = []

            async def edit(connection: AsyncConnection) -> None:
                try:
                    await _task_service(connection).set_status(
                        user_id=owner,
                        task_id=task_id,
                        status=TaskStatus.DONE,
                        transaction=connection,
                    )
                except TaskNotFoundError as error:
                    outcome.append(error)

            await overlap(async_engine, self._deleting(owner, list_id), edit)

            assert len(outcome) == 1
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_delete_during_a_status_edit_waits_then_deletes(
        self, async_engine: AsyncEngine
    ) -> None:
        owner = _race_owner()
        try:
            list_id, (task_id,) = await self._seed(async_engine, owner, 1)

            async def edit(connection: AsyncConnection) -> None:
                await _task_service(connection).set_status(
                    user_id=owner,
                    task_id=task_id,
                    status=TaskStatus.DONE,
                    transaction=connection,
                )

            await overlap(async_engine, edit, self._deleting(owner, list_id))

            async with async_engine.connect() as check:
                assert not await _list_exists(check, list_id)
                assert not await task_exists(check, task_id)
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_create_during_the_delete_waits_then_finds_no_list(
        self, async_engine: AsyncEngine
    ) -> None:
        owner = _race_owner()
        try:
            list_id, _ = await self._seed(async_engine, owner, 0)
            outcome: list[BaseException] = []

            async def create(connection: AsyncConnection) -> None:
                try:
                    await _task_service(connection).create_list_task(
                        user_id=owner,
                        task_list_id=list_id,
                        text="too late",
                        transaction=connection,
                    )
                except TaskListNotFoundError as error:
                    outcome.append(error)

            await overlap(async_engine, self._deleting(owner, list_id), create)

            assert len(outcome) == 1
            async with async_engine.connect() as check:
                assert (
                    await count(
                        check,
                        "SELECT COUNT(*) FROM tasks WHERE user_id = :user_id",
                        {"user_id": owner},
                    )
                    == 0
                )
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_delete_during_a_reorder_waits_then_deletes(
        self, async_engine: AsyncEngine
    ) -> None:
        owner = _race_owner()
        try:
            list_id, (first, second) = await self._seed(async_engine, owner, 2)

            async def reorder(connection: AsyncConnection) -> None:
                await _task_service(connection).reorder_task(
                    user_id=owner,
                    task_id=first,
                    after_task_id=second,
                    transaction=connection,
                )

            await overlap(async_engine, reorder, self._deleting(owner, list_id))

            async with async_engine.connect() as check:
                assert not await _list_exists(check, list_id)
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_reorder_during_the_delete_waits_then_finds_no_list(
        self, async_engine: AsyncEngine
    ) -> None:
        owner = _race_owner()
        try:
            list_id, (first, second) = await self._seed(async_engine, owner, 2)
            outcome: list[BaseException] = []

            async def reorder(connection: AsyncConnection) -> None:
                try:
                    await _task_service(connection).reorder_task(
                        user_id=owner,
                        task_id=first,
                        after_task_id=second,
                        transaction=connection,
                    )
                except (TaskNotFoundError, TaskListNotFoundError) as error:
                    outcome.append(error)

            await overlap(async_engine, self._deleting(owner, list_id), reorder)

            assert len(outcome) == 1
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_delete_during_a_move_off_the_list_deletes_without_the_task(
        self, async_engine: AsyncEngine
    ) -> None:
        """A move holds its lists before its task; the delete queues on that
        task, and once the move commits the task is no longer the list's."""
        owner = _race_owner()
        try:
            list_id, (task_id,) = await self._seed(async_engine, owner, 1)
            async with async_engine.begin() as setup:
                target = await _seeded_list(setup, "Elsewhere", user_id=owner)

            async def move(connection: AsyncConnection) -> None:
                await _task_service(connection).move_to_list(
                    user_id=owner,
                    task_id=task_id,
                    task_list_id=target,
                    transaction=connection,
                )

            await overlap(async_engine, move, self._deleting(owner, list_id))

            async with async_engine.connect() as check:
                assert not await _list_exists(check, list_id)
                assert await task_exists(check, task_id)
                assert (
                    await count(
                        check,
                        "SELECT COUNT(*) FROM tasks"
                        " WHERE id = :task_id AND task_list_id = :target",
                        {"task_id": task_id, "target": target},
                    )
                    == 1
                )
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_move_off_the_list_during_the_delete_waits_then_finds_no_task(
        self, async_engine: AsyncEngine
    ) -> None:
        owner = _race_owner()
        try:
            list_id, (task_id,) = await self._seed(async_engine, owner, 1)
            async with async_engine.begin() as setup:
                target = await _seeded_list(setup, "Elsewhere", user_id=owner)
            outcome: list[BaseException] = []

            async def move(connection: AsyncConnection) -> None:
                try:
                    await _task_service(connection).move_to_list(
                        user_id=owner,
                        task_id=task_id,
                        task_list_id=target,
                        transaction=connection,
                    )
                except TaskNotFoundError as error:
                    outcome.append(error)

            await overlap(async_engine, self._deleting(owner, list_id), move)

            assert len(outcome) == 1
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_move_onto_the_list_during_the_delete_waits_then_finds_no_list(
        self, async_engine: AsyncEngine
    ) -> None:
        owner = _race_owner()
        try:
            list_id, _ = await self._seed(async_engine, owner, 0)
            async with async_engine.begin() as setup:
                source = await _seeded_list(setup, "Elsewhere", user_id=owner)
                task_id = await create_list_task(
                    setup, task_list_id=source, position=0, user_id=owner
                )
            outcome: list[BaseException] = []

            async def move(connection: AsyncConnection) -> None:
                try:
                    await _task_service(connection).move_to_list(
                        user_id=owner,
                        task_id=task_id,
                        task_list_id=list_id,
                        transaction=connection,
                    )
                except TaskListNotFoundError as error:
                    outcome.append(error)

            await overlap(async_engine, self._deleting(owner, list_id), move)

            assert len(outcome) == 1
            async with async_engine.connect() as check:
                assert await task_exists(check, task_id)
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_second_delete_waits_then_finds_no_list(
        self, async_engine: AsyncEngine
    ) -> None:
        owner = _race_owner()
        try:
            list_id, _ = await self._seed(async_engine, owner, 1)
            outcome: list[BaseException] = []

            async def again(connection: AsyncConnection) -> None:
                try:
                    await _delete(connection, list_id, user_id=owner)
                except TaskListNotFoundError as error:
                    outcome.append(error)

            await overlap(async_engine, self._deleting(owner, list_id), again)

            assert len(outcome) == 1
            async with async_engine.connect() as check:
                (event,) = (
                    await check.execute(
                        text(
                            "SELECT event_type FROM outbox_events "
                            "WHERE event_type = 'TaskListDeleted' "
                            "AND CAST(event_data AS jsonb) ->> 'user_id' = :user_id"
                        ),
                        {"user_id": owner},
                    )
                ).all()
                assert event.event_type == "TaskListDeleted"
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_delete_waits_for_another_delete_before_locking_the_list(
        self, async_engine: AsyncEngine
    ) -> None:
        """Two deletes of one list must not both hold it ``FOR SHARE``, or each
        one's ``NOWAIT`` refuses on the other's lock and neither deletes. The
        second waits for the first's hold before taking any list lock, then
        finds the list gone."""
        owner = _race_owner()
        try:
            list_id, _ = await self._seed(async_engine, owner, 0)
            outcome: list[BaseException] = []

            async def hold(connection: AsyncConnection) -> None:
                await SqlTaskListRepository(connection).serialize_deletes(list_id)
                await _delete(connection, list_id, user_id=owner)

            async def again(connection: AsyncConnection) -> None:
                try:
                    await _delete(connection, list_id, user_id=owner)
                except TaskListNotFoundError as error:
                    outcome.append(error)

            await overlap(async_engine, hold, again)

            assert len(outcome) == 1
            async with async_engine.connect() as check:
                assert not await _list_exists(check, list_id)
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_link_write_on_a_kept_task_after_the_delete_carries_on(
        self, async_engine: AsyncEngine
    ) -> None:
        """A link write holds its task ``FOR SHARE``, so it waits for the delete
        and then reads the task as the delete left it: journal-only, with its
        list gone. The write goes on as for any journal-only task rather than
        answering 404 for the list it would otherwise have seen."""
        owner = _race_owner()
        try:
            async with async_engine.begin() as setup:
                list_id = await _seeded_list(setup, "Racing", user_id=owner)
                journals = SqlJournalRepository(setup)
                creating_id = await create_journal(journals, user_id=owner)
                due_id = await create_journal(journals, days_offset=7, user_id=owner)
                kept = await create_list_task(
                    setup,
                    task_list_id=list_id,
                    creating_journal_id=creating_id,
                    due_journal_id=due_id,
                    user_id=owner,
                )
                contact_id = await create_contact(setup, user_id=owner)

            async def link(connection: AsyncConnection) -> None:
                await _task_service(connection).link_contact(
                    user_id=owner,
                    task_id=kept,
                    contact_id=contact_id,
                    transaction=connection,
                )

            await overlap(async_engine, self._deleting(owner, list_id), link)

            async with async_engine.connect() as check:
                assert await linked_contact_ids(check, kept) == [contact_id]
                assert await task_exists(check, kept)
        finally:
            await _cleanup_owner(async_engine, owner)

    @pytest.mark.asyncio
    async def test_a_list_held_by_a_task_write_in_flight_is_busy_not_deadlocked(
        self, async_engine: AsyncEngine
    ) -> None:
        """The interleaving the ``NOWAIT`` exists for: another transaction
        holds the list ``FOR SHARE`` — as a task write or reorder does while it
        works — when the delete comes to remove it. The delete refuses at once
        with a retryable conflict, and its own work is undone."""
        owner = _race_owner()
        try:
            list_id, (task_id,) = await self._seed(async_engine, owner, 1)

            async with (
                async_engine.connect() as holder,
                async_engine.connect() as deleter,
            ):
                held = await SqlTaskListRepository(holder).find_by_id_for_share(
                    list_id, owner
                )
                assert held is not None

                with pytest.raises(TaskListBusyError):
                    await bounded(_delete(deleter, list_id, user_id=owner))
                await holder.rollback()

            async with async_engine.connect() as check:
                assert await _list_exists(check, list_id)
                assert await task_exists(check, task_id)
        finally:
            await _cleanup_owner(async_engine, owner)

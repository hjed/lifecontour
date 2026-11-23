"""Unit tests for ``TaskService.move_to_list``: a task joining or changing lists.

The specification's *Moving tasks*: "A list task can be moved to another list;
it joins the bottom" and "A journal-only task can be added to a list. It keeps
its journals and … no longer lapses." Both are one write here, over the
repository's ``add_to_list``, which owns the bottom-of-list position.

What is pinned against mocked ports:

- which repository call is made and which event is published, for a join and
  for a move;
- the **lock order** — a plain read of the task, then the lists in ascending
  id (the source ``FOR SHARE``, the target ``FOR NO KEY UPDATE``), then the
  task row — so no move holds a task while it waits for a list;
- the re-check under the task lock: a task that changed lists after the read
  is refused, writing nothing;
- the same-list no-op, which writes and publishes nothing;
- the refusal order: task, target list, the task's own archived list, the
  archived target — each writing and publishing nothing.

The real database half — bottom position, lapse, concurrency — is in
``tests/integration/tasks/test_task_service_move_to_list_integration.py``.
"""

import datetime
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    Task,
    TaskList,
    TaskListArchivedError,
    TaskListChangedConcurrentlyError,
    TaskListNotFoundError,
    TaskNotFoundError,
)

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.models.events import TaskListMembershipChanged
from app.core.tasks.models.repositories import TaskListRepository, TaskRepository
from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    TASK_ID,
    TASK_LIST_ID,
    USER_ID,
    make_list_task,
    make_task,
    published_events,
)

pytestmark = pytest.mark.unit

ARCHIVED_AT = datetime.datetime(2026, 11, 1, 9, 0, tzinfo=datetime.UTC)
# One list above and one below the task's own, so the ascending lock order is
# exercised in both directions.
HIGHER_LIST_ID = TASK_LIST_ID + 1
LOWER_LIST_ID = TASK_LIST_ID - 1


def make_task_list(task_list_id: int, *, archived: bool = False) -> TaskList:
    return TaskList(
        id=task_list_id,
        user_id=USER_ID,
        name=f"List {task_list_id}",
        position=0,
        archived_at=ARCHIVED_AT if archived else None,
    )


def landed(task: Task, task_list_id: int) -> Task:
    """What ``add_to_list`` hands back: the task at the bottom of the list."""
    return replace(task, task_list_id=task_list_id, position=5)


@pytest.fixture
def task() -> Task:
    """A list task holding both journals; a test swaps in a journal-only one."""
    return make_list_task(
        creating_journal_id=CREATING_JOURNAL_ID, due_journal_id=DUE_JOURNAL_ID
    )


@pytest.fixture
def lists() -> dict[int, TaskList | None]:
    """The user's lists by id; a test removes or archives one."""
    return {
        list_id: make_task_list(list_id)
        for list_id in (LOWER_LIST_ID, TASK_LIST_ID, HIGHER_LIST_ID)
    }


@pytest.fixture
def reread(task: Task) -> dict[int, Task | None]:
    """The task as the plain re-read under the list locks finds it."""
    return {TASK_ID: task}


@pytest.fixture
def locked(task: Task) -> dict[int, Task | None]:
    """The task as the locking read finds it; a test changes it under the move."""
    return {TASK_ID: task}


@pytest.fixture
def order() -> list[tuple[str, int]]:
    """Every lock taken, in order, as ``(kind, id)``."""
    return []


@pytest.fixture
def task_repo(
    task: Task,
    reread: dict[int, Task | None],
    locked: dict[int, Task | None],
    order: list[tuple[str, int]],
) -> AsyncMock:
    repo = AsyncMock(spec=TaskRepository)

    async def peek(task_id: int, _user_id: str) -> Task | None:
        first = ("peek", task_id) not in order
        order.append(("peek", task_id))
        if task_id != TASK_ID:
            return None
        return task if first else reread.get(task_id)

    async def lock_task(task_id: int, _user_id: str) -> Task | None:
        order.append(("task", task_id))
        return locked.get(task_id)

    async def add_to_list(task_id: int, task_list_id: int, _user_id: str) -> Task:
        order.append(("add_to_list", task_list_id))
        return landed(task, task_list_id)

    repo.find_by_id.side_effect = peek
    repo.find_by_id_for_update.side_effect = lock_task
    repo.add_to_list.side_effect = add_to_list
    return repo


@pytest.fixture
def task_list_repo(
    lists: dict[int, TaskList | None], order: list[tuple[str, int]]
) -> AsyncMock:
    repo = AsyncMock(spec=TaskListRepository)

    async def share(task_list_id: int, _user_id: str) -> TaskList | None:
        order.append(("share", task_list_id))
        return lists.get(task_list_id)

    async def update(task_list_id: int, _user_id: str) -> TaskList | None:
        order.append(("update", task_list_id))
        return lists.get(task_list_id)

    repo.find_by_id_for_share.side_effect = share
    repo.find_by_id_for_update.side_effect = update
    return repo


@pytest.fixture
def service(
    task_repo: AsyncMock,
    task_list_repo: AsyncMock,
    mock_settings_repo: AsyncMock,
    mock_event_publisher: AsyncMock,
) -> TaskService:
    return TaskService(
        task_repo=task_repo,
        task_list_repo=task_list_repo,
        journal_repo=AsyncMock(),
        contact_repo=AsyncMock(),
        date_resolver=JournalDateResolver(mock_settings_repo),
        event_publisher=mock_event_publisher,
    )


async def move(
    service: TaskService,
    tx: AsyncMock,
    task_list_id: int,
    *,
    task_id: int = TASK_ID,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
) -> Task:
    return await service.move_to_list(
        user_id=USER_ID,
        task_id=task_id,
        task_list_id=task_list_id,
        transaction=tx,
        source=source,
        changed_by=changed_by,
    )


class TestAMoveBetweenLists:
    @pytest.mark.asyncio
    async def test_the_task_lands_on_the_target_list(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task: Task,
        mock_transaction: AsyncMock,
    ) -> None:
        moved = await move(service, mock_transaction, HIGHER_LIST_ID)

        task_repo.add_to_list.assert_awaited_once_with(TASK_ID, HIGHER_LIST_ID, USER_ID)
        assert moved == landed(task, HIGHER_LIST_ID)

    @pytest.mark.asyncio
    async def test_one_membership_event_names_both_lists(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await move(
            service,
            mock_transaction,
            HIGHER_LIST_ID,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        [event] = published_events(mock_event_publisher)
        assert isinstance(event, TaskListMembershipChanged)
        assert event.aggregate_id == TASK_ID
        assert event.event_data["user_id"] == USER_ID
        assert event.event_data["changed_fields"] == {
            "task_list_id": (TASK_LIST_ID, HIGHER_LIST_ID)
        }
        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"
        assert event.transaction is mock_transaction

    @pytest.mark.asyncio
    async def test_the_event_follows_the_write(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        calls: list[str] = []

        async def record_write(*_: object) -> Task:
            calls.append("write")
            return make_list_task()

        async def record_publish(*_: object) -> None:
            calls.append("publish")

        task_repo.add_to_list.side_effect = record_write
        mock_event_publisher.publish.side_effect = record_publish

        await move(service, mock_transaction, HIGHER_LIST_ID)

        assert calls == ["write", "publish"]


class TestAJournalOnlyTaskJoiningAList:
    @pytest.fixture
    def task(self) -> Task:
        return make_task()

    @pytest.mark.asyncio
    async def test_it_joins_the_list_and_announces_it_from_none(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await move(service, mock_transaction, TASK_LIST_ID)

        task_repo.add_to_list.assert_awaited_once_with(TASK_ID, TASK_LIST_ID, USER_ID)
        [event] = published_events(mock_event_publisher)
        assert event.event_data["changed_fields"] == {
            "task_list_id": (None, TASK_LIST_ID)
        }

    @pytest.mark.asyncio
    async def test_no_source_list_is_read(
        self,
        service: TaskService,
        task_list_repo: AsyncMock,
        order: list[tuple[str, int]],
        mock_transaction: AsyncMock,
    ) -> None:
        await move(service, mock_transaction, TASK_LIST_ID)

        task_list_repo.find_by_id_for_share.assert_not_awaited()
        assert order[:4] == [
            ("peek", TASK_ID),
            ("update", TASK_LIST_ID),
            ("peek", TASK_ID),
            ("task", TASK_ID),
        ]


class TestTheLockOrder:
    """A plain read of the task, both lists in ascending id, then the task row.

    The move takes its target exclusively, so it must not hold a task while it
    waits for one: two crossing moves and a reorder of either list would wait
    on each other in a cycle (each move holding its task, the reorder holding
    the list ``FOR SHARE`` and waiting on a task). Lists first is the order the
    reorders already use. The target is locked for update from the start:
    ``add_to_list`` computes the bottom under that lock, and upgrading a share
    lock later would deadlock two moves onto one list.
    """

    @pytest.mark.asyncio
    async def test_moving_up_locks_the_source_first(
        self,
        service: TaskService,
        order: list[tuple[str, int]],
        mock_transaction: AsyncMock,
    ) -> None:
        await move(service, mock_transaction, HIGHER_LIST_ID)

        assert order == [
            ("peek", TASK_ID),
            ("share", TASK_LIST_ID),
            ("update", HIGHER_LIST_ID),
            ("peek", TASK_ID),
            ("task", TASK_ID),
            ("add_to_list", HIGHER_LIST_ID),
        ]

    @pytest.mark.asyncio
    async def test_moving_down_locks_the_target_first(
        self,
        service: TaskService,
        order: list[tuple[str, int]],
        mock_transaction: AsyncMock,
    ) -> None:
        await move(service, mock_transaction, LOWER_LIST_ID)

        assert order == [
            ("peek", TASK_ID),
            ("update", LOWER_LIST_ID),
            ("share", TASK_LIST_ID),
            ("peek", TASK_ID),
            ("task", TASK_ID),
            ("add_to_list", LOWER_LIST_ID),
        ]


class TestATaskThatChangedUnderTheMove:
    """The lists were chosen from a plain read, so the move checks it twice.

    Another move can take the task elsewhere between the read and the locks.
    The lists this move holds are then the wrong ones, and a lock taken now
    would break the ascending order, so it refuses — 409, read again and retry.

    The first check is a plain re-read **under the list locks, before the task
    lock**. Nothing can put the task onto the target while the move holds it
    exclusively, so if the task is still where it was read, whoever holds the
    task waits at most for a list this move holds shared. Waiting for the task
    when it had already moved onto the target would deadlock against an edit
    holding the task and asking for that list. The second check, under the
    task lock, catches a move off the source in the meantime.
    """

    @pytest.mark.asyncio
    async def test_a_task_already_moved_is_refused_without_waiting_for_it(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task: Task,
        reread: dict[int, Task | None],
        order: list[tuple[str, int]],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        reread[TASK_ID] = replace(task, task_list_id=HIGHER_LIST_ID)

        with pytest.raises(TaskListChangedConcurrentlyError):
            await move(service, mock_transaction, HIGHER_LIST_ID)

        assert ("task", TASK_ID) not in order
        task_repo.add_to_list.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_task_deleted_before_the_re_read_is_not_found(
        self,
        service: TaskService,
        reread: dict[int, Task | None],
        order: list[tuple[str, int]],
        mock_transaction: AsyncMock,
    ) -> None:
        reread[TASK_ID] = None

        with pytest.raises(TaskNotFoundError):
            await move(service, mock_transaction, HIGHER_LIST_ID)

        assert ("task", TASK_ID) not in order

    @pytest.mark.parametrize(
        "now_on",
        [LOWER_LIST_ID, None],
        ids=["moved-to-another-list", "removed-from-its-list"],
    )
    @pytest.mark.asyncio
    async def test_a_task_that_changed_lists_is_refused_and_nothing_written(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task: Task,
        locked: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        now_on: int | None,
    ) -> None:
        locked[TASK_ID] = replace(
            task, task_list_id=now_on, position=None if now_on is None else 0
        )

        with pytest.raises(TaskListChangedConcurrentlyError) as refused:
            await move(service, mock_transaction, HIGHER_LIST_ID)

        assert refused.value.status_code == 409
        task_repo.add_to_list.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_journal_only_task_put_on_a_list_meanwhile_is_refused(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        locked: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        locked[TASK_ID] = replace(make_list_task(), task_list_id=LOWER_LIST_ID)
        task_repo.find_by_id.side_effect = None
        task_repo.find_by_id.return_value = make_task()

        with pytest.raises(TaskListChangedConcurrentlyError):
            await move(service, mock_transaction, HIGHER_LIST_ID)

        task_repo.add_to_list.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_task_deleted_meanwhile_is_not_found(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        locked: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        locked[TASK_ID] = None

        with pytest.raises(TaskNotFoundError):
            await move(service, mock_transaction, HIGHER_LIST_ID)

        task_repo.add_to_list.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_same_list_no_op_re_checks_too(
        self,
        service: TaskService,
        task: Task,
        locked: dict[int, Task | None],
        mock_transaction: AsyncMock,
    ) -> None:
        """It would otherwise answer with a list the task is no longer on."""
        locked[TASK_ID] = replace(task, task_list_id=LOWER_LIST_ID)

        with pytest.raises(TaskListChangedConcurrentlyError):
            await move(service, mock_transaction, TASK_LIST_ID)


class TestMovingToTheListItIsAlreadyOn:
    """A no-op: nothing is written and no change is announced."""

    @pytest.mark.asyncio
    async def test_nothing_is_written_or_published(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task: Task,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        unchanged = await move(service, mock_transaction, TASK_LIST_ID)

        assert unchanged is task
        task_repo.add_to_list.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_list_is_held_with_the_share_lock_only(
        self,
        service: TaskService,
        order: list[tuple[str, int]],
        mock_transaction: AsyncMock,
    ) -> None:
        """No position is computed, so no update lock is needed on the list."""
        await move(service, mock_transaction, TASK_LIST_ID)

        assert order == [
            ("peek", TASK_ID),
            ("share", TASK_LIST_ID),
            ("peek", TASK_ID),
            ("task", TASK_ID),
        ]

    @pytest.mark.asyncio
    async def test_it_is_still_refused_on_an_archived_list(
        self,
        service: TaskService,
        lists: dict[int, TaskList | None],
        mock_transaction: AsyncMock,
    ) -> None:
        lists[TASK_LIST_ID] = make_task_list(TASK_LIST_ID, archived=True)

        with pytest.raises(TaskListArchivedError):
            await move(service, mock_transaction, TASK_LIST_ID)


class TestRefusals:
    """Each refusal writes nothing and publishes nothing."""

    @staticmethod
    def assert_untouched(task_repo: AsyncMock, publisher: AsyncMock) -> None:
        task_repo.add_to_list.assert_not_awaited()
        task_repo.save.assert_not_awaited()
        publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_missing_task_is_not_found_before_any_list_is_read(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            await move(service, mock_transaction, HIGHER_LIST_ID, task_id=TASK_ID + 1)

        task_list_repo.find_by_id_for_share.assert_not_awaited()
        task_list_repo.find_by_id_for_update.assert_not_awaited()
        self.assert_untouched(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_missing_or_foreign_target_list_is_not_found(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        lists: dict[int, TaskList | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Another user's list reads as absent, so the two answers are one."""
        lists[HIGHER_LIST_ID] = None

        with pytest.raises(TaskListNotFoundError) as refused:
            await move(service, mock_transaction, HIGHER_LIST_ID)

        assert refused.value.status_code == 404
        assert str(HIGHER_LIST_ID) in refused.value.message
        self.assert_untouched(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_task_on_an_archived_list_is_refused_naming_that_list(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        lists: dict[int, TaskList | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        lists[TASK_LIST_ID] = make_task_list(TASK_LIST_ID, archived=True)

        with pytest.raises(TaskListArchivedError) as refused:
            await move(service, mock_transaction, HIGHER_LIST_ID)

        assert str(TASK_LIST_ID) in refused.value.message
        assert refused.value.status_code == 409
        self.assert_untouched(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_an_archived_target_is_refused_naming_the_target(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        lists: dict[int, TaskList | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        lists[HIGHER_LIST_ID] = make_task_list(HIGHER_LIST_ID, archived=True)

        with pytest.raises(TaskListArchivedError) as refused:
            await move(service, mock_transaction, HIGHER_LIST_ID)

        assert str(HIGHER_LIST_ID) in refused.value.message
        self.assert_untouched(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_missing_target_outranks_an_archived_source(
        self,
        service: TaskService,
        lists: dict[int, TaskList | None],
        mock_transaction: AsyncMock,
    ) -> None:
        lists[TASK_LIST_ID] = make_task_list(TASK_LIST_ID, archived=True)
        lists[HIGHER_LIST_ID] = None

        with pytest.raises(TaskListNotFoundError):
            await move(service, mock_transaction, HIGHER_LIST_ID)

    @pytest.mark.asyncio
    async def test_an_archived_source_outranks_an_archived_target(
        self,
        service: TaskService,
        lists: dict[int, TaskList | None],
        mock_transaction: AsyncMock,
    ) -> None:
        """Nothing about the target can make the move succeed while the task
        itself is read-only, so the task's own list is the one named."""
        lists[TASK_LIST_ID] = make_task_list(TASK_LIST_ID, archived=True)
        lists[HIGHER_LIST_ID] = make_task_list(HIGHER_LIST_ID, archived=True)

        with pytest.raises(TaskListArchivedError) as refused:
            await move(service, mock_transaction, HIGHER_LIST_ID)

        assert str(TASK_LIST_ID) in refused.value.message


class TestTheTrailWrapper:
    @pytest.mark.asyncio
    async def test_it_forwards_provenance_and_returns_the_trail(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        task_repo.list_intermediate_journal_ids.return_value = [CREATING_JOURNAL_ID]

        moved, trail = await service.move_to_list_with_trail(
            user_id=USER_ID,
            task_id=TASK_ID,
            task_list_id=HIGHER_LIST_ID,
            transaction=mock_transaction,
            source=Provenance.UI,
            changed_by="ui",
        )

        assert moved.task_list_id == HIGHER_LIST_ID
        assert trail == [CREATING_JOURNAL_ID]
        [event] = published_events(mock_event_publisher)
        assert event.event_data["source"] == "ui"
        assert event.event_data["changed_by"] == "ui"

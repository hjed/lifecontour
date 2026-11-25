"""Unit tests for ``TaskService.remove_from_list``: a task leaving its list.

The specification's *Moving tasks*: "A task can be removed from its list only
if it has both a creating and a due journal. It becomes a journal-only task …
A task without both anchors cannot be removed — only moved, cancelled or
deleted."

What is pinned against mocked ports:

- the repository call and the one event, ``TaskListMembershipChanged`` from the
  list to ``None``;
- the **lock order** — a plain read of the task, its list ``FOR SHARE``, then
  the task row — so a removal never holds a task while it waits for a list;
- the re-check under the task lock: a task that changed lists after the read is
  refused, writing nothing;
- the journal-only no-op, which locks, writes and publishes nothing;
- the refusals and their order: task, archived list, changed list, missing
  journals — each writing and publishing nothing.

The real database half — lapse, concurrency — is in
``tests/integration/tasks/test_task_service_remove_from_list_integration.py``.
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
    TaskListRemovalNeedsJournalsError,
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
OTHER_LIST_ID = TASK_LIST_ID + 1


def make_task_list(*, archived: bool = False) -> TaskList:
    return TaskList(
        id=TASK_LIST_ID,
        user_id=USER_ID,
        name="Packing",
        position=0,
        archived_at=ARCHIVED_AT if archived else None,
    )


def left(task: Task) -> Task:
    """What ``remove_from_list`` hands back: the task with no list."""
    return replace(task, task_list_id=None, position=None, due_date=None)


@pytest.fixture
def task() -> Task:
    """A list task holding both journals — the one shape that may leave."""
    return make_list_task(
        creating_journal_id=CREATING_JOURNAL_ID, due_journal_id=DUE_JOURNAL_ID
    )


@pytest.fixture
def locked(task: Task) -> dict[int, Task | None]:
    """The task as the locking read finds it; a test changes it under the call."""
    return {TASK_ID: task}


@pytest.fixture
def reread() -> dict[int, Task | None]:
    """The task as a plain read finds it after the first; empty means unchanged."""
    return {}


@pytest.fixture
def task_list() -> dict[str, TaskList | None]:
    """The list the share lock reads; a test archives or removes it."""
    return {"list": make_task_list()}


@pytest.fixture
def order() -> list[tuple[str, int]]:
    """Every read and lock taken, in order, as ``(kind, id)``."""
    return []


@pytest.fixture
def task_repo(
    task: Task,
    locked: dict[int, Task | None],
    reread: dict[int, Task | None],
    order: list[tuple[str, int]],
) -> AsyncMock:
    repo = AsyncMock(spec=TaskRepository)

    async def peek(task_id: int, _user_id: str) -> Task | None:
        first = all(kind != "peek" for kind, _ in order)
        order.append(("peek", task_id))
        if task_id != TASK_ID:
            return None
        return task if first else reread.get(task_id, task)

    async def lock_task(task_id: int, _user_id: str) -> Task | None:
        order.append(("task", task_id))
        return locked.get(task_id)

    async def remove(task_id: int, _user_id: str) -> Task:
        order.append(("remove_from_list", task_id))
        current = locked[task_id]
        assert current is not None
        return left(current)

    repo.find_by_id.side_effect = peek
    repo.find_by_id_for_update.side_effect = lock_task
    repo.remove_from_list.side_effect = remove
    return repo


@pytest.fixture
def task_list_repo(
    task_list: dict[str, TaskList | None], order: list[tuple[str, int]]
) -> AsyncMock:
    repo = AsyncMock(spec=TaskListRepository)

    async def share(task_list_id: int, _user_id: str) -> TaskList | None:
        order.append(("share", task_list_id))
        return task_list["list"]

    repo.find_by_id_for_share.side_effect = share
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


async def remove(
    service: TaskService,
    tx: AsyncMock,
    *,
    task_id: int = TASK_ID,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
) -> Task:
    return await service.remove_from_list(
        user_id=USER_ID,
        task_id=task_id,
        transaction=tx,
        source=source,
        changed_by=changed_by,
    )


class TestARemoval:
    @pytest.mark.asyncio
    async def test_the_task_leaves_its_list(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task: Task,
        mock_transaction: AsyncMock,
    ) -> None:
        removed = await remove(service, mock_transaction)

        task_repo.remove_from_list.assert_awaited_once_with(TASK_ID, USER_ID)
        assert removed == left(task)
        assert removed.task_list_id is None

    @pytest.mark.asyncio
    async def test_one_membership_event_names_the_list_it_left(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await remove(service, mock_transaction, source=Provenance.MCP, changed_by="mcp")

        [event] = published_events(mock_event_publisher)
        assert isinstance(event, TaskListMembershipChanged)
        assert event.aggregate_id == TASK_ID
        assert event.event_data["user_id"] == USER_ID
        assert event.event_data["changed_fields"] == {
            "task_list_id": (TASK_LIST_ID, None)
        }
        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"
        assert event.transaction is mock_transaction

    @pytest.mark.asyncio
    async def test_the_event_follows_the_write(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        order: list[tuple[str, int]],
        mock_transaction: AsyncMock,
    ) -> None:
        async def record_publish(*_: object) -> None:
            order.append(("publish", TASK_ID))

        mock_event_publisher.publish.side_effect = record_publish

        await remove(service, mock_transaction)

        assert order[-2:] == [("remove_from_list", TASK_ID), ("publish", TASK_ID)]

    @pytest.mark.asyncio
    async def test_the_list_is_share_locked_before_the_task(
        self,
        service: TaskService,
        order: list[tuple[str, int]],
        mock_transaction: AsyncMock,
    ) -> None:
        """List first, as a reorder: a removal never holds a task while it
        waits for a list, so it cannot join a cycle with a move (which holds a
        list exclusively and waits for its task) and a journal delete (which
        holds tasks in id order)."""
        await remove(service, mock_transaction)

        assert order == [
            ("peek", TASK_ID),
            ("share", TASK_LIST_ID),
            ("task", TASK_ID),
            ("remove_from_list", TASK_ID),
        ]

    @pytest.mark.asyncio
    async def test_the_list_is_never_taken_exclusively(
        self,
        service: TaskService,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await remove(service, mock_transaction)

        task_list_repo.find_by_id_for_update.assert_not_awaited()


class TestAJournalOnlyTask:
    """Already off every list: nothing to do, and nothing is done."""

    @pytest.fixture
    def task(self) -> Task:
        return make_task()

    @pytest.mark.asyncio
    async def test_it_is_answered_unchanged(
        self,
        service: TaskService,
        task: Task,
        mock_transaction: AsyncMock,
    ) -> None:
        assert await remove(service, mock_transaction) == task

    @pytest.mark.asyncio
    async def test_nothing_is_locked_written_or_published(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await remove(service, mock_transaction)

        task_repo.find_by_id_for_update.assert_not_awaited()
        task_repo.remove_from_list.assert_not_awaited()
        task_list_repo.find_by_id_for_share.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()


def _assert_nothing_happened(task_repo: AsyncMock, publisher: AsyncMock) -> None:
    task_repo.remove_from_list.assert_not_awaited()
    task_repo.save.assert_not_awaited()
    publisher.publish.assert_not_awaited()


class TestTheRefusals:
    @pytest.mark.asyncio
    async def test_another_users_task_is_not_found(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            await remove(service, mock_transaction, task_id=TASK_ID + 99)

        task_list_repo.find_by_id_for_share.assert_not_awaited()
        _assert_nothing_happened(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_an_archived_list_is_refused(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list: dict[str, TaskList | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        task_list["list"] = make_task_list(archived=True)

        with pytest.raises(TaskListArchivedError):
            await remove(service, mock_transaction)

        task_repo.find_by_id_for_update.assert_not_awaited()
        _assert_nothing_happened(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_task_that_changed_lists_meanwhile_is_refused(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task: Task,
        locked: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        locked[TASK_ID] = replace(task, task_list_id=OTHER_LIST_ID)

        with pytest.raises(TaskListChangedConcurrentlyError):
            await remove(service, mock_transaction)

        _assert_nothing_happened(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_task_removed_meanwhile_is_answered_unchanged(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task: Task,
        locked: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Another removal of the same task won while this one waited: the
        same no-op a removal sent afterwards gets, not a conflict."""
        locked[TASK_ID] = left(task)

        assert await remove(service, mock_transaction) == left(task)

        _assert_nothing_happened(task_repo, mock_event_publisher)

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
            await remove(service, mock_transaction)

        _assert_nothing_happened(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("creating", "due", "missing"),
        [
            (None, None, "creating journal and due journal"),
            (CREATING_JOURNAL_ID, None, "due journal"),
            (None, DUE_JOURNAL_ID, "creating journal"),
        ],
        ids=["neither", "no-due-journal", "no-creating-journal"],
    )
    async def test_a_task_without_both_journals_is_refused(
        self,
        creating: int | None,
        due: int | None,
        missing: str,
        service: TaskService,
        task_repo: AsyncMock,
        locked: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        locked[TASK_ID] = make_list_task(
            creating_journal_id=creating, due_journal_id=due
        )

        with pytest.raises(TaskListRemovalNeedsJournalsError) as refused:
            await remove(service, mock_transaction)

        assert refused.value.status_code == 409
        assert refused.value.task_id == TASK_ID
        assert f"no {missing}" in refused.value.message
        _assert_nothing_happened(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_dated_task_is_refused_too(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        locked: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A due date belongs to a list task: its date would have nowhere to
        go, so it is refused like an undated one."""
        locked[TASK_ID] = make_list_task(
            creating_journal_id=CREATING_JOURNAL_ID,
            due_date=datetime.date(2099, 1, 1),
        )

        with pytest.raises(TaskListRemovalNeedsJournalsError):
            await remove(service, mock_transaction)

        _assert_nothing_happened(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_the_journals_are_judged_under_the_lock_not_from_the_read(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        locked: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A journal delete can detach the due journal between the plain read
        and the lock; the locked row is the one that decides."""
        locked[TASK_ID] = make_list_task(creating_journal_id=CREATING_JOURNAL_ID)

        with pytest.raises(TaskListRemovalNeedsJournalsError):
            await remove(service, mock_transaction)

        _assert_nothing_happened(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_an_archived_list_is_named_before_the_missing_journals(
        self,
        service: TaskService,
        task_list: dict[str, TaskList | None],
        locked: dict[int, Task | None],
        mock_transaction: AsyncMock,
    ) -> None:
        """Nothing about the task can make a write to a frozen list succeed."""
        task_list["list"] = make_task_list(archived=True)
        locked[TASK_ID] = make_list_task()

        with pytest.raises(TaskListArchivedError):
            await remove(service, mock_transaction)


class TestAListDeletedMeanwhile:
    """The list was deleted between the plain read and its share lock.

    A list delete keeps a task holding both journals as a journal-only task
    and deletes any other, so the task is read again to answer for what the
    delete left rather than for the list that went.
    """

    @pytest.fixture
    def task_list(self) -> dict[str, TaskList | None]:
        return {"list": None}

    @pytest.mark.asyncio
    async def test_a_task_it_kept_is_answered_unchanged(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task: Task,
        reread: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The same no-op a removal sent after the delete gets, not a 404 for
        a task that still exists."""
        reread[TASK_ID] = left(task)

        assert await remove(service, mock_transaction) == left(task)

        task_repo.find_by_id_for_update.assert_not_awaited()
        _assert_nothing_happened(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_task_it_deleted_is_not_found(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        reread: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        reread[TASK_ID] = None

        with pytest.raises(TaskNotFoundError):
            await remove(service, mock_transaction)

        _assert_nothing_happened(task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_task_that_joined_another_list_since_is_refused(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task: Task,
        reread: dict[int, Task | None],
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Kept by the delete, then moved onto a list before this read: the
        removal was asked about the list that went, so read again and retry."""
        reread[TASK_ID] = replace(task, task_list_id=TASK_LIST_ID + 1)

        with pytest.raises(TaskListChangedConcurrentlyError):
            await remove(service, mock_transaction)

        _assert_nothing_happened(task_repo, mock_event_publisher)


class TestTheRefusalMessage:
    def test_it_names_what_the_task_can_do_instead(self) -> None:
        """The specification's way out: "only moved, cancelled or deleted"."""
        message = TaskListRemovalNeedsJournalsError(
            TASK_ID, missing_creating=True, missing_due=False
        ).message

        assert "move it to another list, cancel it or delete it" in message

"""Unit tests for reordering a list's open tasks: ``TaskService.reorder_task``
and ``TaskService.reorder_list_tasks``.

The specification's *The list page*: "Open tasks in the user's manual order.
Drag to reorder, with a keyboard equivalent." and *Contacts, events and
history*: every new mutation appears in task history; "reordering does not".

- ``reorder_task`` is the list page's single move: one open task to the top, or
  directly after another open task on its list.
- ``reorder_list_tasks`` is the agent's: a block of open tasks, in the order
  given, at the top or directly after / before one anchor.

What is pinned here, against mocked ports: each refusal and the order they are
checked in, the delegation to the repository, the answer (the open tasks in
their new order, each with its trail), that nothing is published, and that the
list is held with the **share** lock — the one every task write takes, which is
what keeps a reorder from deadlocking against them. The SQL and the races are
covered by the integration suites.
"""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.tasks import (
    Task,
    TaskList,
    TaskListArchivedError,
    TaskListNotFoundError,
    TaskNotFoundError,
    TaskStatus,
    TaskValidationError,
)

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.models.repositories import TaskListRepository, TaskRepository
from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    INTERMEDIATE_JOURNAL_ID,
    TASK_ID,
    TASK_LIST_ID,
    USER_ID,
    make_list_task,
    make_task,
)

pytestmark = pytest.mark.unit

ANCHOR_ID = 8
THIRD_ID = 9
OTHER_LIST_ID = 100


def task_list(*, archived: bool = False) -> TaskList:
    """The list the tasks are on."""
    from datetime import UTC, datetime

    return TaskList(
        id=TASK_LIST_ID,
        user_id=USER_ID,
        name="Packing",
        position=0,
        archived_at=datetime(2026, 11, 1, tzinfo=UTC) if archived else None,
    )


def on_list(
    task_id: int,
    status: TaskStatus = TaskStatus.NOT_DONE,
    *,
    task_list_id: int = TASK_LIST_ID,
) -> Task:
    """An open (by default) task on the list."""
    task = make_list_task(status, task_id=task_id)
    if task_list_id == TASK_LIST_ID:
        return task
    return Task(
        id=task.id,
        user_id=task.user_id,
        text=task.text,
        task_list_id=task_list_id,
        position=0,
        status=status,
    )


@pytest.fixture
def stored() -> dict[int, Task]:
    """The tasks the plain read finds, by id; a test replaces entries."""
    return {
        TASK_ID: on_list(TASK_ID),
        ANCHOR_ID: on_list(ANCHOR_ID),
        THIRD_ID: on_list(THIRD_ID),
    }


@pytest.fixture
def task_repo(stored: dict[int, Task]) -> AsyncMock:
    """Spec'd on the port, so a renamed method fails rather than passing."""
    repo = AsyncMock(spec=TaskRepository)

    async def find_by_id(task_id: int, user_id: str) -> Task | None:
        assert user_id == USER_ID
        return stored.get(task_id)

    async def open_on_list(task_list_id: int, user_id: str) -> list[Task]:
        return [
            each
            for each in stored.values()
            if each.task_list_id == task_list_id and each.status is TaskStatus.NOT_DONE
        ]

    repo.find_by_id.side_effect = find_by_id
    repo.find_open_tasks_on_list.side_effect = open_on_list
    new_order = [stored[ANCHOR_ID], stored[TASK_ID], stored[THIRD_ID]]
    repo.move_within_list.return_value = new_order
    repo.arrange_open_tasks.return_value = new_order
    repo.list_intermediate_journal_ids_for_tasks.return_value = {
        TASK_ID: [INTERMEDIATE_JOURNAL_ID]
    }
    return repo


@pytest.fixture
def task_list_repo() -> AsyncMock:
    repo = AsyncMock(spec=TaskListRepository)
    repo.find_by_id_for_share.return_value = task_list()
    return repo


@pytest.fixture
def service(
    task_repo: AsyncMock,
    task_list_repo: AsyncMock,
    mock_journal_repo: AsyncMock,
    mock_contact_repo: AsyncMock,
    mock_settings_repo: AsyncMock,
    mock_event_publisher: AsyncMock,
) -> TaskService:
    return TaskService(
        task_repo=task_repo,
        task_list_repo=task_list_repo,
        journal_repo=mock_journal_repo,
        contact_repo=mock_contact_repo,
        date_resolver=JournalDateResolver(mock_settings_repo),
        event_publisher=mock_event_publisher,
    )


def assert_nothing_moved(task_repo: AsyncMock) -> None:
    task_repo.move_within_list.assert_not_awaited()
    task_repo.arrange_open_tasks.assert_not_awaited()
    task_repo.save.assert_not_awaited()


class TestReorderTask:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("after", [ANCHOR_ID, None], ids=["after", "top"])
    async def test_it_moves_through_the_repository_and_answers_the_new_order(
        self,
        after: int | None,
        service: TaskService,
        task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        answer = await service.reorder_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            after_task_id=after,
            transaction=mock_transaction,
        )

        task_repo.move_within_list.assert_awaited_once_with(
            TASK_ID, USER_ID, after_task_id=after
        )
        assert [(task.id, trail) for task, trail in answer] == [
            (ANCHOR_ID, []),
            (TASK_ID, [INTERMEDIATE_JOURNAL_ID]),
            (THIRD_ID, []),
        ]
        task_repo.list_intermediate_journal_ids_for_tasks.assert_awaited_once_with(
            [ANCHOR_ID, TASK_ID, THIRD_ID], USER_ID
        )
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_list_is_held_with_the_share_lock_and_no_task_is_locked(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await service.reorder_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            after_task_id=ANCHOR_ID,
            transaction=mock_transaction,
        )

        task_list_repo.find_by_id_for_share.assert_awaited_once_with(
            TASK_LIST_ID, USER_ID
        )
        task_list_repo.find_by_id_for_update.assert_not_awaited()
        task_repo.find_by_id_for_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_task_cannot_follow_itself_and_nothing_is_read(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskValidationError) as refused:
            await service.reorder_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                after_task_id=TASK_ID,
                transaction=mock_transaction,
            )

        assert refused.value.field == "after_task_id"
        task_repo.find_by_id.assert_not_awaited()
        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    async def test_an_unknown_task_is_not_found(
        self,
        service: TaskService,
        stored: dict[int, Task],
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        del stored[TASK_ID]

        with pytest.raises(TaskNotFoundError, match=str(TASK_ID)):
            await service.reorder_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                after_task_id=None,
                transaction=mock_transaction,
            )

        task_list_repo.find_by_id_for_share.assert_not_awaited()
        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    async def test_a_journal_only_task_has_no_order_to_change(
        self,
        service: TaskService,
        stored: dict[int, Task],
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        stored[TASK_ID] = make_task()

        with pytest.raises(TaskValidationError) as refused:
            await service.reorder_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                after_task_id=None,
                transaction=mock_transaction,
            )

        assert refused.value.field == "task_id"
        assert refused.value.status_code == 400
        task_list_repo.find_by_id_for_share.assert_not_awaited()
        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    async def test_an_unknown_anchor_is_not_found_before_the_list_is_read(
        self,
        service: TaskService,
        stored: dict[int, Task],
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        del stored[ANCHOR_ID]
        task_list_repo.find_by_id_for_share.return_value = task_list(archived=True)

        with pytest.raises(TaskNotFoundError, match=str(ANCHOR_ID)):
            await service.reorder_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                after_task_id=ANCHOR_ID,
                transaction=mock_transaction,
            )

        task_list_repo.find_by_id_for_share.assert_not_awaited()
        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    async def test_an_archived_list_comes_before_the_closed_task(
        self,
        service: TaskService,
        stored: dict[int, Task],
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        stored[TASK_ID] = on_list(TASK_ID, TaskStatus.DONE)
        task_list_repo.find_by_id_for_share.return_value = task_list(archived=True)

        with pytest.raises(TaskListArchivedError):
            await service.reorder_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                after_task_id=None,
                transaction=mock_transaction,
            )

        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_closed_task_is_refused(
        self,
        status: TaskStatus,
        service: TaskService,
        stored: dict[int, Task],
        task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        stored[TASK_ID] = on_list(TASK_ID, status)

        with pytest.raises(TaskValidationError) as refused:
            await service.reorder_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                after_task_id=None,
                transaction=mock_transaction,
            )

        assert refused.value.field == "task_id"
        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "anchor",
        [
            on_list(ANCHOR_ID, TaskStatus.DONE),
            on_list(ANCHOR_ID, task_list_id=OTHER_LIST_ID),
            Task(
                id=ANCHOR_ID,
                user_id=USER_ID,
                text="journal-only",
                creating_journal_id=CREATING_JOURNAL_ID,
                due_journal_id=DUE_JOURNAL_ID,
            ),
        ],
        ids=["closed", "another-list", "journal-only"],
    )
    async def test_an_anchor_that_is_not_open_on_the_same_list_is_refused(
        self,
        anchor: Task,
        service: TaskService,
        stored: dict[int, Task],
        task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        stored[ANCHOR_ID] = anchor

        with pytest.raises(TaskValidationError) as refused:
            await service.reorder_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                after_task_id=ANCHOR_ID,
                transaction=mock_transaction,
            )

        assert refused.value.field == "after_task_id"
        assert_nothing_moved(task_repo)


class TestReorderListTasks:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("after", "before"),
        [(None, None), (THIRD_ID, None), (None, THIRD_ID)],
        ids=["top", "after", "before"],
    )
    async def test_it_arranges_through_the_repository_and_answers_the_new_order(
        self,
        after: int | None,
        before: int | None,
        service: TaskService,
        task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        answer = await service.reorder_list_tasks(
            user_id=USER_ID,
            task_list_id=TASK_LIST_ID,
            task_ids=[ANCHOR_ID, TASK_ID],
            after_task_id=after,
            before_task_id=before,
            transaction=mock_transaction,
        )

        task_repo.arrange_open_tasks.assert_awaited_once_with(
            TASK_LIST_ID,
            USER_ID,
            task_ids=[ANCHOR_ID, TASK_ID],
            after_task_id=after,
            before_task_id=before,
        )
        assert [(task.id, trail) for task, trail in answer] == [
            (ANCHOR_ID, []),
            (TASK_ID, [INTERMEDIATE_JOURNAL_ID]),
            (THIRD_ID, []),
        ]
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_list_is_held_with_the_share_lock_and_no_task_is_locked(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await service.reorder_list_tasks(
            user_id=USER_ID,
            task_list_id=TASK_LIST_ID,
            task_ids=[TASK_ID],
            transaction=mock_transaction,
        )

        task_list_repo.find_by_id_for_share.assert_awaited_once_with(
            TASK_LIST_ID, USER_ID
        )
        task_list_repo.find_by_id_for_update.assert_not_awaited()
        task_repo.find_by_id_for_update.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("task_ids", "after", "before", "field"),
        [
            ([], None, None, "task_ids"),
            ([TASK_ID, ANCHOR_ID, TASK_ID], None, None, "task_ids"),
            ([TASK_ID], ANCHOR_ID, THIRD_ID, "before_task_id"),
            ([TASK_ID, ANCHOR_ID], ANCHOR_ID, None, "after_task_id"),
            ([TASK_ID, ANCHOR_ID], None, ANCHOR_ID, "before_task_id"),
        ],
        ids=["empty", "duplicate", "both-anchors", "after-in-block", "before-in-block"],
    )
    async def test_a_malformed_arrangement_is_refused_before_anything_is_read(
        self,
        task_ids: list[int],
        after: int | None,
        before: int | None,
        field: str,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskValidationError) as refused:
            await service.reorder_list_tasks(
                user_id=USER_ID,
                task_list_id=TASK_LIST_ID,
                task_ids=task_ids,
                after_task_id=after,
                before_task_id=before,
                transaction=mock_transaction,
            )

        assert refused.value.field == field
        assert refused.value.status_code == 400
        task_list_repo.find_by_id_for_share.assert_not_awaited()
        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    async def test_an_unknown_list_is_not_found(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        task_list_repo.find_by_id_for_share.return_value = None

        with pytest.raises(TaskListNotFoundError, match=str(TASK_LIST_ID)):
            await service.reorder_list_tasks(
                user_id=USER_ID,
                task_list_id=TASK_LIST_ID,
                task_ids=[TASK_ID],
                transaction=mock_transaction,
            )

        task_repo.find_open_tasks_on_list.assert_not_awaited()
        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    async def test_an_archived_list_comes_before_the_named_tasks_are_checked(
        self,
        service: TaskService,
        task_repo: AsyncMock,
        task_list_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        task_list_repo.find_by_id_for_share.return_value = task_list(archived=True)

        with pytest.raises(TaskListArchivedError):
            await service.reorder_list_tasks(
                user_id=USER_ID,
                task_list_id=TASK_LIST_ID,
                task_ids=[12345],
                transaction=mock_transaction,
            )

        task_repo.find_open_tasks_on_list.assert_not_awaited()
        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    async def test_named_tasks_that_are_not_open_on_the_list_are_named(
        self,
        service: TaskService,
        stored: dict[int, Task],
        task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Closed, on another list or not the user's at all — one answer, so an
        id of someone else's reads exactly as an id on another list."""
        stored[ANCHOR_ID] = on_list(ANCHOR_ID, TaskStatus.DONE)
        stored[THIRD_ID] = on_list(THIRD_ID, task_list_id=OTHER_LIST_ID)

        with pytest.raises(TaskValidationError) as refused:
            await service.reorder_list_tasks(
                user_id=USER_ID,
                task_list_id=TASK_LIST_ID,
                task_ids=[TASK_ID, ANCHOR_ID, THIRD_ID, 12345],
                transaction=mock_transaction,
            )

        assert refused.value.field == "task_ids"
        for named in (ANCHOR_ID, THIRD_ID, 12345):
            assert str(named) in refused.value.message
        assert_nothing_moved(task_repo)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["after_task_id", "before_task_id"])
    async def test_an_anchor_that_is_not_open_on_the_list_is_refused(
        self,
        field: str,
        service: TaskService,
        stored: dict[int, Task],
        task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        stored[THIRD_ID] = on_list(THIRD_ID, TaskStatus.CANCELLED)

        with pytest.raises(TaskValidationError) as refused:
            await service.reorder_list_tasks(
                user_id=USER_ID,
                task_list_id=TASK_LIST_ID,
                task_ids=[TASK_ID],
                transaction=mock_transaction,
                **{field: THIRD_ID},
            )

        assert refused.value.field == field
        assert_nothing_moved(task_repo)

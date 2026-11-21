"""Unit tests for the task list read service's listing and its open counts.

The listing answers each list with its open-task count: Phase 14's per-list
counts, read in one statement for the whole listing, with a list that has no
open tasks reported as zero rather than left out.
"""

from unittest.mock import AsyncMock

from core_shared.models.tasks import TaskList, TaskListArchiveFilter, TaskListSummary

from app.core.tasks.services.task_list_read_service import TaskListReadService
from tests.unit.tasks.task_doubles import USER_ID


def task_list(task_list_id: int, name: str) -> TaskList:
    return TaskList(id=task_list_id, user_id=USER_ID, name=name, position=0)


def service(
    lists: list[TaskList], counts: dict[int, int]
) -> tuple[TaskListReadService, AsyncMock, AsyncMock]:
    task_list_repo = AsyncMock()
    task_list_repo.list_for_user.return_value = lists
    task_repo = AsyncMock()
    task_repo.count_open_tasks_by_list.return_value = counts
    return (
        TaskListReadService(task_list_repo=task_list_repo, task_repo=task_repo),
        task_list_repo,
        task_repo,
    )


class TestTheListingCarriesOpenCounts:
    async def test_each_list_carries_its_count_and_an_empty_one_zero(self) -> None:
        packing, shopping = task_list(1, "Packing"), task_list(2, "Shopping")
        read_service, _, _ = service([packing, shopping], {1: 3})

        listing = await read_service.list_task_lists(
            user_id=USER_ID, archived=TaskListArchiveFilter.ACTIVE
        )

        assert listing == [
            TaskListSummary(task_list=packing, open_task_count=3),
            TaskListSummary(task_list=shopping, open_task_count=0),
        ]

    async def test_the_counts_are_one_owner_scoped_read_for_the_whole_listing(
        self,
    ) -> None:
        read_service, task_list_repo, task_repo = service(
            [task_list(1, "Packing"), task_list(2, "Shopping")], {}
        )

        await read_service.list_task_lists(
            user_id=USER_ID, archived=TaskListArchiveFilter.ALL
        )

        task_list_repo.list_for_user.assert_awaited_once_with(
            USER_ID, TaskListArchiveFilter.ALL
        )
        task_repo.count_open_tasks_by_list.assert_awaited_once_with([1, 2], USER_ID)

    async def test_no_lists_asks_for_no_counts(self) -> None:
        read_service, _, task_repo = service([], {})

        listing = await read_service.list_task_lists(
            user_id=USER_ID, archived=TaskListArchiveFilter.ARCHIVED
        )

        assert listing == []
        task_repo.count_open_tasks_by_list.assert_not_awaited()

"""Unit tests for the task list read service's listing and its open counts.

The listing answers each list with its open-task count: Phase 14's per-list
counts, read in one statement for the listed page, with a list that has no
open tasks reported as zero rather than left out. The page's total is the
repository's, whatever the page holds.
"""

from unittest.mock import AsyncMock

from core_shared.models.tasks import (
    TaskList,
    TaskListArchiveFilter,
    TaskListListing,
    TaskListPage,
    TaskListPageWindow,
    TaskListSummary,
    TaskListSummaryPage,
)

from app.core.tasks.services.task_list_read_service import TaskListReadService
from tests.unit.tasks.task_doubles import USER_ID


def task_list(task_list_id: int, name: str) -> TaskList:
    return TaskList(id=task_list_id, user_id=USER_ID, name=name, position=0)


def service(
    lists: list[TaskList], counts: dict[int, int], *, total: int | None = None
) -> tuple[TaskListReadService, AsyncMock, AsyncMock]:
    task_list_repo = AsyncMock()
    task_list_repo.list_for_user.return_value = TaskListPage(
        task_lists=tuple(lists), total=len(lists) if total is None else total
    )
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
            user_id=USER_ID,
            listing=TaskListListing(archived=TaskListArchiveFilter.ACTIVE),
        )

        assert listing == TaskListSummaryPage(
            summaries=(
                TaskListSummary(task_list=packing, open_task_count=3),
                TaskListSummary(task_list=shopping, open_task_count=0),
            ),
            total=2,
        )

    async def test_the_counts_are_one_owner_scoped_read_for_the_listed_page(
        self,
    ) -> None:
        asked = TaskListListing(
            archived=TaskListArchiveFilter.ARCHIVED,
            name_contains="trip",
            page=TaskListPageWindow(limit=2, offset=2),
        )
        read_service, task_list_repo, task_repo = service(
            [task_list(7, "Bali trip"), task_list(4, "Snow trip")], {}, total=9
        )

        listing = await read_service.list_task_lists(user_id=USER_ID, listing=asked)

        task_list_repo.list_for_user.assert_awaited_once_with(USER_ID, asked)
        task_repo.count_open_tasks_by_list.assert_awaited_once_with([7, 4], USER_ID)
        assert listing.total == 9

    async def test_an_empty_page_asks_for_no_counts_and_keeps_the_total(
        self,
    ) -> None:
        read_service, _, task_repo = service([], {}, total=5)

        listing = await read_service.list_task_lists(
            user_id=USER_ID,
            listing=TaskListListing(
                archived=TaskListArchiveFilter.ARCHIVED,
                page=TaskListPageWindow(limit=20, offset=20),
            ),
        )

        assert listing == TaskListSummaryPage(summaries=(), total=5)
        task_repo.count_open_tasks_by_list.assert_not_awaited()

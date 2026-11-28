"""Reading task lists back for their owner.

Separate from :class:`TaskListService` for the reason ``TaskReadService`` is
separate from ``TaskService``: a read needs no transaction, lock or event, and a
caller that only reads a list should not be handed the ability to change one.

Every read is owner-scoped in the repository, so another user's list is
reported exactly as a missing one.
"""

from core_shared.models.tasks import (
    TaskList,
    TaskListListing,
    TaskListNotFoundError,
    TaskListSummary,
    TaskListSummaryPage,
)

from app.core.tasks.models.repositories import TaskListRepository, TaskRepository


class TaskListReadService:
    """Reads one list, or a listing of the owner's lists."""

    def __init__(
        self, task_list_repo: TaskListRepository, task_repo: TaskRepository
    ) -> None:
        self.task_list_repo = task_list_repo
        # For the listing's open-task counts, which are task rows.
        self.task_repo = task_repo

    async def get_task_list(self, *, user_id: str, task_list_id: int) -> TaskList:
        """Return one of the user's lists.

        Raises:
            TaskListNotFoundError: No such list, or it belongs to someone else.
        """
        found = await self.task_list_repo.find_by_id(task_list_id, user_id)
        if found is None:
            raise TaskListNotFoundError(task_list_id)
        return found

    async def list_task_lists(
        self, *, user_id: str, listing: TaskListListing
    ) -> TaskListSummaryPage:
        """Return the user's lists for one listing, each with its open-task
        count, in the order the repository defines for its archived filter:
        manual order for ``ACTIVE`` and ``ALL``, most-recently-archived first
        for ``ARCHIVED``.

        The counts are one owner-scoped statement for the listed page, and a
        list with no open tasks — absent from the counts — reads as zero. The
        total is every list the listing matches, across pages.
        """
        page = await self.task_list_repo.list_for_user(user_id, listing)
        if not page.task_lists:
            return TaskListSummaryPage(summaries=(), total=page.total)
        # A listed list is persisted, so its id is always set.
        list_ids = [task_list.id for task_list in page.task_lists if task_list.id]
        counts = await self.task_repo.count_open_tasks_by_list(list_ids, user_id)
        return TaskListSummaryPage(
            summaries=tuple(
                TaskListSummary(
                    task_list=task_list,
                    open_task_count=counts.get(task_list.id or 0, 0),
                )
                for task_list in page.task_lists
            ),
            total=page.total,
        )

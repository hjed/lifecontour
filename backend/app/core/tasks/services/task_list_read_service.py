"""Reading task lists back for their owner.

Separate from :class:`TaskListService` for the reason ``TaskReadService`` is
separate from ``TaskService``: a read needs no transaction, lock or event, and a
caller that only reads a list should not be handed the ability to change one.

Every read is owner-scoped in the repository, so another user's list is
reported exactly as a missing one.
"""

from core_shared.models.tasks import (
    TaskList,
    TaskListArchiveFilter,
    TaskListNotFoundError,
)

from app.core.tasks.models.repositories import TaskListRepository


class TaskListReadService:
    """Reads one list, or the owner's lists by archived state."""

    def __init__(self, task_list_repo: TaskListRepository) -> None:
        self.task_list_repo = task_list_repo

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
        self, *, user_id: str, archived: TaskListArchiveFilter
    ) -> list[TaskList]:
        """Return the user's lists for one archived filter, in the order the
        repository defines for it: manual order for ``ACTIVE`` and ``ALL``,
        most-recently-archived first for ``ARCHIVED``.
        """
        return await self.task_list_repo.list_for_user(user_id, archived)

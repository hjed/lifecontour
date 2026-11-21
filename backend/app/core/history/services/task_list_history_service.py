"""Read service for a task list's field-level history.

Authorised by :class:`OwnerScopedHistory`, the rule ``TaskHistoryService``
uses: the owner on the history rows first, the live list row as the fallback
for a list whose events have not been projected yet. Lists are going to be
hard-deleted, and their history has to outlive the row.
"""

from core_shared.models.tasks import TaskListNotFoundError

from app.core.history.models import FieldHistoryEntry, FieldHistoryRepository
from app.core.history.services.owner_scoped_history import OwnerScopedHistory
from app.core.tasks.models.repositories import TaskListRepository

_TASK_LIST_ROOT_TYPE = "task_list"


class TaskListHistoryService:
    """Paginated, owner-scoped read access to a task list's change history."""

    def __init__(
        self,
        history_repo: FieldHistoryRepository,
        task_list_repo: TaskListRepository,
    ) -> None:
        self._task_list_repo = task_list_repo
        self._history = OwnerScopedHistory(
            history_repo,
            root_type=_TASK_LIST_ROOT_TYPE,
            owns_live_row=self._owns_list,
            not_found=TaskListNotFoundError,
        )

    async def get_task_list_history(
        self, task_list_id: int, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[FieldHistoryEntry]:
        """Get paginated history for a list (most recent first).

        Raises:
            TaskListNotFoundError: The list is unknown, or is not this user's —
                one answer, so a refusal cannot probe for other users' lists.
        """
        return await self._history.read(task_list_id, user_id, limit, offset)

    async def get_task_list_history_count(self, task_list_id: int, user_id: str) -> int:
        """Get the total number of history entries for a list, authorised as the read."""
        return await self._history.count(task_list_id, user_id)

    async def _owns_list(self, task_list_id: int, user_id: str) -> bool:
        return await self._task_list_repo.find_by_id(task_list_id, user_id) is not None

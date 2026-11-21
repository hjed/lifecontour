"""Read service for a task's field-level history.

Mirrors :class:`JournalHistoryService` — the same paginated read through the
same entity-agnostic repository, resolved by the registered ``"task"``
aggregation strategy — with one addition that is the whole reason this file
exists rather than another method on the journal service.

**It authorises the read itself.** Everywhere else in this system, a history
endpoint loads the aggregate, compares ``user_id`` and then asks for the rows;
the journal controller does exactly that before calling
``get_journal_history``. A task is **hard-deleted**, so that pattern has nothing
to load: ``TaskService.delete_task`` removes the row and the ``TaskDeleted``
event projects a ``__deleted__`` marker, which under the ordinary pattern would
be written to a surface nobody could ever be authorised to read. Putting the
resolution here (through ``OwnerScopedHistory``) rather than in the two callers also means the endpoint and the
MCP tool cannot answer the question differently.
"""

from core_shared.models.tasks.exceptions import TaskNotFoundError

from app.core.history.models import FieldHistoryEntry, FieldHistoryRepository
from app.core.history.services.owner_scoped_history import OwnerScopedHistory
from app.core.tasks.models.repositories import TaskRepository

_TASK_ROOT_TYPE = "task"


class TaskHistoryService:
    """Paginated, owner-scoped read access to a task's change history.

    The authorisation lives in :class:`OwnerScopedHistory` — the owner on the
    history rows first, the live task row as the fallback for a task whose
    events have not been projected yet — shared with the task-list read.
    """

    def __init__(
        self,
        history_repo: FieldHistoryRepository,
        task_repo: TaskRepository,
    ):
        self.history_repo = history_repo
        self.task_repo = task_repo
        self._history = OwnerScopedHistory(
            history_repo,
            root_type=_TASK_ROOT_TYPE,
            owns_live_row=self._owns_task,
            not_found=TaskNotFoundError,
        )

    async def get_task_history(
        self, task_id: int, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[FieldHistoryEntry]:
        """Get paginated history for a task (most recent first).

        Raises:
            TaskNotFoundError: The task is unknown, or is not this user's. The
                two are the same answer everywhere in this domain, so a
                rejection here cannot be used to probe for other users' tasks.
        """
        return await self._history.read(task_id, user_id, limit, offset)

    async def get_task_history_count(self, task_id: int, user_id: str) -> int:
        """Get the total number of history entries for a task.

        Authorised identically to the read, because a count is a disclosure too:
        how much history a task has is information about that task.
        """
        return await self._history.count(task_id, user_id)

    async def _owns_task(self, task_id: int, user_id: str) -> bool:
        return await self.task_repo.find_by_id(task_id, user_id) is not None

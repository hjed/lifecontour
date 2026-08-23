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
resolution here rather than in the two callers also means the endpoint and the
MCP tool cannot answer the question differently.
"""

from core_shared.models.tasks.exceptions import TaskNotFoundError

from app.core.history.models import FieldHistoryEntry, FieldHistoryRepository
from app.core.tasks.models.repositories import TaskRepository

_TASK_ROOT_TYPE = "task"


class TaskHistoryService:
    """Paginated, owner-scoped read access to a task's change history."""

    def __init__(
        self,
        history_repo: FieldHistoryRepository,
        task_repo: TaskRepository,
    ):
        self.history_repo = history_repo
        self.task_repo = task_repo

    async def get_task_history(
        self, task_id: int, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[FieldHistoryEntry]:
        """Get paginated history for a task (most recent first).

        Raises:
            TaskNotFoundError: The task is unknown, or is not this user's. The
                two are the same answer everywhere in this domain, so a
                rejection here cannot be used to probe for other users' tasks.
        """
        await self._require_owned(task_id, user_id)
        return await self.history_repo.get_history_for_aggregate(
            _TASK_ROOT_TYPE, task_id, limit, offset
        )

    async def get_task_history_count(self, task_id: int, user_id: str) -> int:
        """Get the total number of history entries for a task.

        Authorised identically to the read, because a count is a disclosure too:
        how much history a task has is information about that task.
        """
        await self._require_owned(task_id, user_id)
        return await self.history_repo.get_history_for_aggregate_count(
            _TASK_ROOT_TYPE, task_id
        )

    async def _require_owned(self, task_id: int, user_id: str) -> None:
        """Resolve whose history this is, or refuse.

        **The history rows answer first, and the task row is only a fallback.**
        The order is what makes a deleted task readable: its rows carry the
        owner (``field_history.user_id``, stamped from the event payload — see
        ``_owner_for`` in the history service), and asking the ``tasks`` table
        first would refuse the very case this surface was built for.

        ``get_history_owner`` returning ``None`` is **not** a refusal. It means
        no row carries an owner, which happens for a task whose events have not
        been projected yet — projection is asynchronous, so a task created
        moments ago is in exactly that state, and answering 404 would tell the
        user their new task does not exist. The live row settles it, through the
        owner-scoped ``find_by_id`` rather than a comparison written again here.

        Nothing is read before this returns. A service that fetched the rows and
        then decided is one careless refactor away from returning them.
        """
        owner = await self.history_repo.get_history_owner(_TASK_ROOT_TYPE, task_id)
        if owner is not None:
            if owner != user_id:
                raise TaskNotFoundError(task_id)
            return
        if await self.task_repo.find_by_id(task_id, user_id) is None:
            raise TaskNotFoundError(task_id)

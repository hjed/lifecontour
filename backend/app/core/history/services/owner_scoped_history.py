"""The one rule for reading the history of an aggregate that is hard-deleted.

Tasks are removed outright and leave a ``__deleted__`` marker behind, and task
lists will be too once they can be deleted, so neither read can authorise by
loading the aggregate as the journal read does: after a delete there is nothing
to load.
Their rows carry the owner instead (``field_history.user_id``, stamped by
``HistoryService._owner_for``). This class is the single place that turns that
into an answer, so the task and the task-list reads — and the REST and MCP
callers of each — cannot disagree about whose history it is.
"""

from collections.abc import Awaitable, Callable

from app.core.history.models import FieldHistoryEntry, FieldHistoryRepository

LiveRowCheck = Callable[[int, str], Awaitable[bool]]
"""``(entity_id, user_id) -> bool``: does this user own a live row with that id."""

NotFound = Callable[[int], Exception]
"""Builds the domain's not-found error for an id."""


class OwnerScopedHistory:
    """Paginated history for one aggregate root, readable only by its owner."""

    def __init__(
        self,
        history_repo: FieldHistoryRepository,
        *,
        root_type: str,
        owns_live_row: LiveRowCheck,
        not_found: NotFound,
    ) -> None:
        self._history_repo = history_repo
        self._root_type = root_type
        self._owns_live_row = owns_live_row
        self._not_found = not_found

    async def read(
        self, entity_id: int, user_id: str, limit: int, offset: int
    ) -> list[FieldHistoryEntry]:
        """One page of the root's history, most recent first."""
        await self._require_owned(entity_id, user_id)
        return await self._history_repo.get_history_for_aggregate(
            self._root_type, entity_id, limit, offset
        )

    async def count(self, entity_id: int, user_id: str) -> int:
        """The total, authorised exactly as the read: a count is a disclosure."""
        await self._require_owned(entity_id, user_id)
        return await self._history_repo.get_history_for_aggregate_count(
            self._root_type, entity_id
        )

    async def _require_owned(self, entity_id: int, user_id: str) -> None:
        """Resolve whose history this is, or refuse.

        **The history rows answer first, and the live row is only a fallback.**
        The order is what makes a deleted aggregate readable: asking its table
        first would refuse the very case this exists for.

        ``get_history_owner`` returning ``None`` is **not** a refusal. It means
        no row carries an owner yet — projection is asynchronous, so something
        created moments ago is in exactly that state, and answering "not found"
        would tell the user it does not exist. The owner-scoped live row settles
        it instead.

        Nothing is read before this returns. A service that fetched the rows and
        then decided is one careless refactor away from returning them.
        """
        owner = await self._history_repo.get_history_owner(self._root_type, entity_id)
        if owner is not None:
            if owner != user_id:
                raise self._not_found(entity_id)
            return
        if not await self._owns_live_row(entity_id, user_id):
            raise self._not_found(entity_id)

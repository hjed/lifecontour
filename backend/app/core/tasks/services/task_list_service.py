"""Writing task lists: the service every list write passes through.

Each write is a ``@transactional`` unit of work that changes the list and
publishes its domain event on the same connection, so the two commit or roll
back together. Reads live in :class:`TaskListReadService`, which takes no event
publisher and opens no unit of work — the same split ``TaskService`` and
``TaskReadService`` make.

Creation, the field update (rename, set or clear the icon) and reordering exist
so far; archive extends this class. Every write locks what it reads inside its
unit of work before writing: the field update its one list with
``find_by_id_for_update``, a move all the owner's lists. Reordering is the one
write that publishes no event: the specification keeps it out of history.
"""

from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    TaskIcon,
    TaskList,
    TaskListArchivedError,
    TaskListArchiveFilter,
    TaskListNotFoundError,
    reorder_task_lists,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.repositories import TaskListRepository
from app.core.tasks.models.task_list_events import (
    TaskListCreated,
    TaskListFieldChange,
    TaskListUpdated,
)
from app.core.tasks.services.task_list_patch import TaskListPatch
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional


class TaskListService:
    """Creates, changes and reorders task lists for their owner.

    Every write but a move announces itself.
    """

    def __init__(
        self,
        task_list_repo: TaskListRepository,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.task_list_repo = task_list_repo
        self.event_publisher = event_publisher

    @transactional
    async def create_task_list(
        self,
        *,
        user_id: str,
        name: str,
        icon: TaskIcon | None,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> TaskList:
        """Create a list at the bottom of the owner's lists.

        The entity refuses a blank or over-long name before anything is
        written, so a refused create leaves neither a row nor an event. The
        event is built from the list *as persisted*, after the repository has
        assigned its id and position.

        Raises:
            TaskListValidationError: The name is blank or too long.
        """
        created = await self.task_list_repo.save(
            TaskList(user_id=user_id, name=name, icon=icon)
        )
        assert created.id is not None, "Task list ID must be set after save"

        await self.event_publisher.publish(
            TaskListCreated(
                task_list_id=created.id,
                user_id=created.user_id,
                name=created.name,
                icon=created.icon,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return created

    @transactional
    async def update_task_list(
        self,
        *,
        user_id: str,
        task_list_id: int,
        patch: TaskListPatch,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> TaskList:
        """Rename a list, set or clear its icon, or both, as one change.

        **The read takes a row lock** and the patch is applied to the list as
        read under it, so two overlapping updates serialise and neither can
        put back a field only the other one changed.

        **Only what actually moved is written and announced.** A patch naming
        values the list already has — or naming nothing — is a no-op: nothing
        is saved and no event is published. Otherwise one ``TaskListUpdated``
        carries ``changed_fields`` for exactly the fields that differ, after
        the save, so it announces a change that finished.

        The patch is applied with one ``replace``, which re-runs the entity's
        validation, so a refused name is refused before anything is written.

        Raises:
            TaskListValidationError: The new name is blank or too long.
            TaskListNotFoundError: The list does not exist or is not the acting
                user's; the two are indistinguishable by design.
        """
        stored = await self.task_list_repo.find_by_id_for_update(task_list_id, user_id)
        if stored is None:
            raise TaskListNotFoundError(task_list_id)

        changed_fields = _changed_fields(stored, patch)
        if not changed_fields:
            return stored

        saved = await self.task_list_repo.save(patch.applied_to(stored))

        await self.event_publisher.publish(
            TaskListUpdated(
                task_list_id=task_list_id,
                user_id=user_id,
                changed_fields=changed_fields,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return saved

    @transactional
    async def move_task_list(
        self,
        *,
        user_id: str,
        task_list_id: int,
        index: int,
        transaction: AsyncConnection,
    ) -> list[TaskList]:
        """Move one of the owner's lists to a new place among their active lists.

        Every one of the owner's lists is locked first, so a concurrent move
        waits and then builds on this one's order rather than writing back the
        order it read before. ``index`` counts active lists only, the view a
        person reorders; archived lists keep their place relative to their
        neighbours, and an index past the end moves the list to the bottom (see
        :func:`reorder_task_lists`). Every list is then renumbered densely.

        Publishes no event: reordering is not part of a list's history.

        Returns:
            The owner's active lists in their new order.

        Raises:
            TaskListNotFoundError: No such list, or it belongs to someone else.
            TaskListArchivedError: The list is archived, and so read-only.
        """
        locked = await self.task_list_repo.list_for_user_for_update(user_id)
        moved = next((each for each in locked if each.id == task_list_id), None)
        if moved is None:
            raise TaskListNotFoundError(task_list_id)
        if moved.is_archived:
            raise TaskListArchivedError(task_list_id)

        await self.task_list_repo.reposition(
            user_id, reorder_task_lists(locked, task_list_id, index)
        )
        return await self.task_list_repo.list_for_user(
            user_id, TaskListArchiveFilter.ACTIVE
        )


def _wire(value: object) -> str | None:
    """A field value as the event payload carries it: a plain string or null.

    ``TaskIcon`` is checked first: it is a ``StrEnum``, so it is also a ``str``,
    and the payload must hold the bare key rather than the member.
    """
    if isinstance(value, TaskIcon):
        return value.value
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"No wire form for a task list field value: {value!r}")


def _changed_fields(
    stored: TaskList, patch: TaskListPatch
) -> dict[str, TaskListFieldChange]:
    """``{field: (old, new)}`` for each patched field whose value differs."""
    return {
        field: (_wire(old), _wire(new))
        for field, new in patch.changes().items()
        if (old := getattr(stored, field)) != new
    }

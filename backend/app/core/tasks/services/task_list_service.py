"""Writing task lists: the service every list write passes through.

Each write is a ``@transactional`` unit of work that changes the list and
publishes its domain event on the same connection, so the two commit or roll
back together. Reads live in :class:`TaskListReadService`, which takes no event
publisher and opens no unit of work — the same split ``TaskService`` and
``TaskReadService`` make.

Creation and the field update (rename, set or clear the icon) exist so far.
Reorder and archive extend this class, and every write reads with
``find_by_id_for_update`` inside its unit of work before writing.
"""

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskIcon, TaskList, TaskListNotFoundError
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
    """Creates and changes task lists for their owner, announcing each write."""

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

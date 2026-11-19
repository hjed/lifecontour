"""Writing task lists: the service every list write passes through.

Each write is a ``@transactional`` unit of work that changes the list and
publishes its domain event on the same connection, so the two commit or roll
back together. Reads live in :class:`TaskListReadService`, which takes no event
publisher and opens no unit of work — the same split ``TaskService`` and
``TaskReadService`` make.

Only creation exists so far. Rename, icon, reorder and archive extend this
class, and every one of them reads with ``find_by_id_for_update`` inside its
unit of work before writing.
"""

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskIcon, TaskList
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.repositories import TaskListRepository
from app.core.tasks.models.task_list_events import TaskListCreated
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional


class TaskListService:
    """Creates task lists for their owner and announces each one."""

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

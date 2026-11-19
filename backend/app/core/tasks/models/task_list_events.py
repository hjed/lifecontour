"""Domain events for task lists.

A list is its own aggregate — keyed by the list id, not a task id — so its
events live here rather than in :mod:`app.core.tasks.models.events`. That module
is read by ``tests/task_event_inventory.py``, which requires every event defined
in it to be projected into *task* history; a list event there would either be
filed under a task id or fail that inventory. List history gets its own
projection, under its own ``entity_type``, when it is built.

Until then no stream consumer subscribes to these types (pinned by
``tests/unit/infrastructure/events/test_task_list_event_subscriptions.py``):
they are written to the outbox and relayed, and every consumer acknowledges and
skips them.

Payloads are plain dictionaries, for the reasons given in the task events
module, and the shape is guarded by a whole-key assertion in
``tests/unit/tasks/test_task_list_events.py``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskIcon
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.events import DomainEvent

TASK_LIST_CREATED = "TaskListCreated"

#: Every event type a task list publishes. Extended by each class added here, so
#: a consumer that comes to subscribe to list events — the list history
#: projection first — has one definition to read rather than its own copy.
TASK_LIST_EVENT_TYPES: frozenset[str] = frozenset({TASK_LIST_CREATED})


@dataclass(frozen=True)
class TaskListCreated(DomainEvent):
    """Event raised when a task list is created.

    The payload carries what a "created" history line and a search document
    need — the name and icon as persisted — plus the owner, provenance and
    actor every domain event carries. **Position is deliberately absent**:
    reordering publishes no event, so a position recorded here would go on
    reading as current after it stopped being so. Archive state is absent
    because a new list is never archived.
    """

    def __init__(
        self,
        task_list_id: int,
        user_id: str,
        name: str,
        icon: TaskIcon | None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"task_list_created_{task_list_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=task_list_id,
            event_type=TASK_LIST_CREATED,
            event_data={
                "task_list_id": task_list_id,
                "user_id": user_id,
                "name": name,
                "icon": icon.value if icon is not None else None,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )

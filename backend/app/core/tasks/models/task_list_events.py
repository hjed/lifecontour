"""Domain events for task lists.

A list is its own aggregate — keyed by the list id, not a task id — so its
events live here rather than in :mod:`app.core.tasks.models.events`. That module
is read by ``tests/task_event_inventory.py``, which requires every event defined
in it to be projected into *task* history; a list event there would either be
filed under a task id or fail that inventory.

**List history is projected from these events** (ITER21-001 Phase 7): the
``history-projection`` group subscribes to ``TASK_LIST_EVENT_TYPES`` and files
their rows under ``entity_type='task_list'`` — ``__created__`` carrying the
name, then ``name``, ``icon`` and ``archived_at`` pairs as ``changed_fields``
names them, and ``__deleted__`` carrying the name the list had when it was
deleted. No other consumer subscribes yet; both facts are pinned by
``tests/unit/infrastructure/events/test_task_list_event_subscriptions.py``.

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
TASK_LIST_UPDATED = "TaskListUpdated"
TASK_LIST_DELETED = "TaskListDeleted"

#: Every event type a task list publishes. Extended by each class added here, so
#: a consumer that comes to subscribe to list events — the list history
#: projection first — has one definition to read rather than its own copy.
TASK_LIST_EVENT_TYPES: frozenset[str] = frozenset(
    {TASK_LIST_CREATED, TASK_LIST_UPDATED, TASK_LIST_DELETED}
)


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


#: One field's change, ``(old, new)`` positionally, as JSON-ready scalars: text
#: for a name, an icon or an instant, an integer for a journal id.
type TaskListFieldChange = tuple[str | int | None, str | int | None]


@dataclass(frozen=True)
class TaskListUpdated(DomainEvent):
    """Event raised when a list's own fields change: its name, its icon,
    whether it is archived, or the journal it is associated with.

    **One event for one write**, carrying ``changed_fields`` in the
    ``{field: (old, new)}`` shape every updated-event in this codebase uses, so
    a request that renames a list and changes its icon announces one change.
    Archiving and unarchiving are another key of this type rather than a type
    of their own: ``archived_at``, an ISO instant or ``None`` — ``(None, ts)``
    archives and ``(ts, None)`` unarchives. So is the journal association:
    ``associated_journal_id``, a journal id or ``None``. A journal delete
    publishes ``(deleted, None)`` for each list it leaves unassociated.

    **Only what actually moved is named**: the service compares each requested
    value with the stored one, and a write that changes nothing publishes
    nothing. The pairs are positional — the history projection reads
    ``change[0]`` as old and ``change[1]`` as new — and hold plain strings
    (``TaskIcon.value``), integer journal ids or ``None``, because the payload
    is a wire format.
    """

    def __init__(
        self,
        task_list_id: int,
        user_id: str,
        changed_fields: dict[str, TaskListFieldChange],
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"task_list_updated_{task_list_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=task_list_id,
            event_type=TASK_LIST_UPDATED,
            event_data={
                "task_list_id": task_list_id,
                "user_id": user_id,
                "changed_fields": changed_fields,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class TaskListDeleted(DomainEvent):
    """Event raised when a task list is hard-deleted.

    **The event outlives the row.** Once the list is gone this is the only
    record that it existed, so it carries what a "deleted" history line needs —
    the owner, which a list-scoped history read authorises on, and the name the
    list had — rather than leaving a reader to look either up.

    The counts say what happened to the list's tasks: ``deleted_task_count``
    went with it, ``kept_task_count`` stayed as journal-only tasks. Each of
    those tasks announces itself too, before this event, so the counts are a
    summary rather than the record.
    """

    def __init__(
        self,
        task_list_id: int,
        user_id: str,
        name: str,
        deleted_task_count: int,
        kept_task_count: int,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"task_list_deleted_{task_list_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=task_list_id,
            event_type=TASK_LIST_DELETED,
            event_data={
                "task_list_id": task_list_id,
                "user_id": user_id,
                "name": name,
                "deleted_task_count": deleted_task_count,
                "kept_task_count": kept_task_count,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )

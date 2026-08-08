"""Domain events for the tasks domain.

The specification makes tasks first-class domain entities: they "emit domain
events through the same transactional outbox and stream that contacts and
journals use, and those events project into field history exactly as contact and
journal events do", each carrying provenance and the actor.

This module holds the first two of that set — creation and hard deletion. The
rest (text updated, status changed, due journal retargeted, journal and contact
linked/unlinked) land in later phases, and the history projection that reads
these payloads lands after them.

**Payloads are plain dictionaries, deliberately.** There are typed payload
models in :mod:`core_shared.models.outbox_events`, but that dispatch map exists
so *integration workers* can parse **inbound sync** payloads (``contact.``,
``journal_event.*``, ``immich_album.``, ``journal_review.``). No core domain
event is in it — ``JournalCreated``, ``JournalTagAssigned`` and
``ContactCreated`` are all absent — and no worker consumes task events. Adding a
model here would advertise a consumer that does not exist. What guards the shape
instead is a whole-key assertion in ``tests/unit/tasks/test_task_events.py``.

**The** ``DomainEvent`` **base below is a third copy**, matching the identical
ones in :mod:`app.core.journal.models.events` and
:mod:`app.core.contacts.models.events`. Nothing forces it: the publisher types
against the structural ``DomainEventProtocol``. Extracting one shared base is a
real improvement, but it would edit three domains in a single change — the shape
of diff this iteration's calibration rules single out as the expensive kind — so
it is recorded here as known duplication rather than repeated silently.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class DomainEvent:
    """Base domain event with transaction support.

    ``transaction`` is part of the shape ``DomainEventProtocol`` requires and is
    carried for that conformance. It does **not** route the write:
    ``OutboxEventPublisher`` inserts on the connection it was constructed with
    and never reads this field. What actually puts an event in the same
    transaction as its write is that the DI container hands the publisher and
    the repositories the same request connection.
    """

    event_id: str
    occurred_at: datetime
    aggregate_id: int
    event_type: str
    event_data: dict[str, Any]
    transaction: AsyncConnection | None = None


@dataclass(frozen=True)
class TaskCreated(DomainEvent):
    """Event raised when a task is created.

    The aggregate is the **task**, keyed by its integer id. The history
    projection writes rows under that id into ``field_history.entity_id``, an
    ``Integer`` column, so aggregating under anything else — the due journal,
    say — would file a task's history against another entity.

    The payload carries the task as it was persisted: its text, its status and
    both anchors. It does **not** carry contact ids. A task may be created with
    contacts, but whether that also publishes a contact-linked event is the
    completeness question the contact-link phase settles, and answering it here
    by smuggling the ids into this payload would decide it early and in the
    wrong place.
    """

    def __init__(
        self,
        task_id: int,
        user_id: str,
        text: str,
        status: TaskStatus,
        creating_journal_id: int,
        due_journal_id: int,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"task_created_{task_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=task_id,
            event_type="TaskCreated",
            event_data={
                "task_id": task_id,
                "user_id": user_id,
                "text": text,
                "status": status.value,
                "creating_journal_id": creating_journal_id,
                "due_journal_id": due_journal_id,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class TaskDeleted(DomainEvent):
    """Event raised when a task is hard-deleted.

    **Deliberately minimal.** ``TaskService.delete_task`` reads nothing before
    deleting — one owner-scoped statement either removes a row or reports it
    absent — and that is a standing decision of this domain, because a read
    would add a round trip and a second way for the two to disagree. Enriching
    this payload with the task's text or anchors would undo it for the sake of a
    nicer history line, so the event says only that the task is gone.
    ``JournalDeleted`` carries no title either, for the same reason its
    projection needs a marker rather than a value.

    ``user_id`` is here because the task row is not: a task-scoped history read
    must resolve a hard-deleted task's history without it, so ownership has to
    travel on the event.
    """

    def __init__(
        self,
        task_id: int,
        user_id: str,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"task_deleted_{task_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=task_id,
            event_type="TaskDeleted",
            event_data={
                "task_id": task_id,
                "user_id": user_id,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )

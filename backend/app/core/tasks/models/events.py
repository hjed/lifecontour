"""Domain events for the tasks domain.

The specification makes tasks first-class domain entities: they "emit domain
events through the same transactional outbox and stream that contacts and
journals use, and those events project into field history exactly as contact and
journal events do", each carrying provenance and the actor.

This module holds creation, change, due-journal retargeting and hard deletion.
The rest (journal and contact linked/unlinked) land in later phases, and the
history projection that reads these payloads lands after them.

**A task's text and status changes share one event**, ``TaskUpdated``, carrying
``changed_fields`` — not one event type per field. The phase that added it was
worded as though there would be two, and this is the deliberate divergence: a
single ``PATCH`` may reword a task *and* complete it, which is one write in one
unit of work, and two events would announce two things where one happened.
``JournalUpdated``, ``ContactUpdated``, ``RouteUpdated`` and ``GearItemUpdated``
all take this shape, and ``HistoryService._rows_from_changed_fields`` fans a
``changed_fields`` dict out into one ``field_history`` row per field — so the
user still reads a distinct "text" line and a distinct "status" line in their
history, which is the whole of what per-field event types would have bought.

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
class TaskUpdated(DomainEvent):
    """Event raised when a task's text, status, or both change.

    **One event for one write**, carrying ``changed_fields`` in the
    ``{field: (old, new)}`` shape every other updated-event in this codebase
    uses. ``TaskService.update_task`` owns both fields precisely because a
    ``PATCH`` may carry both and JSON:API says a request is one change; the
    event follows that, rather than splitting a single unit of work into two
    announcements. See the module docstring for why this diverges from the
    phase's "event classes" wording.

    **Only what actually moved is named.** Setting a task's text to the text it
    already has puts no ``text`` key here, so a subscriber never has to tell a
    real change from a resent value, and "every write publishes exactly one
    event" stays true without "…except when nothing changed" attached to it.

    **The pairs are ``(old, new)``, positionally.**
    ``HistoryService._rows_from_changed_fields`` guards
    ``len(change) == 2`` and then reads ``change[0]`` as the old value and
    ``change[1]`` as the new one — it never looks at a key name — so the order
    is the contract. Values must be JSON-serialisable scalars, because they
    reach that projection through ``outbox_events.event_data`` and a Redis
    stream: the caller passes ``TaskStatus.value``, not the enum member. **Not
    because ``json.dumps`` would refuse the member** — ``TaskStatus`` is a
    ``StrEnum`` and serialises identically, a correction to what this paragraph
    said before — but because the payload is a wire format, and a member in it
    hands an in-process subscriber a domain type where one reading the event
    back out of Redis gets a bare string. The tuples arrive there as lists,
    which is what the guard already expects.
    """

    def __init__(
        self,
        task_id: int,
        user_id: str,
        changed_fields: dict[str, Any],
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"task_updated_{task_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=task_id,
            event_type="TaskUpdated",
            event_data={
                "task_id": task_id,
                "user_id": user_id,
                "changed_fields": changed_fields,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class TaskDueJournalRetargeted(DomainEvent):
    """Event raised when a task's due journal moves to a different journal.

    **One event, not two.** A retarget does two things — it moves the due anchor
    and retains the journal being left as an *intermediate* journal, the model's
    one automatic link — but they are a single write in a single unit of work.
    So the auto-link travels in this payload rather than as a second event, and
    "every task write path publishes exactly one event" stays true for now with
    no exception attached to it. The phase that gives manual attach and detach
    their own event type is required to publish the derived link as that same
    type, so the exception is **deferred rather than avoided** — and the
    ordering that phase inherits is the write order
    :meth:`TaskService.retarget_due_journal` already has: the intermediate link
    first, then the anchor move, so a consumer reading the pair renders the trail
    in the order it happened.

    **The payload names two facts about that link, not one.**
    ``auto_linked_journal_id`` is the journal retained, and
    ``auto_link_created`` says whether a row was actually written for it.
    The second is reachable rather than theoretical: **a retarget only ever adds
    an intermediate link and never removes one**, so a journal can be both the
    due anchor and an intermediate link, and a task retargeted A→B→A→C finds A
    still attached when it leaves it the second time. Links *are* removable —
    :meth:`TaskService.detach_intermediate_journal` removes one on request, a
    journal merge collapses the redundant ones, and deleting a journal cascades
    — but none of those is a retarget, so none of them is what puts this branch
    on the reachable side. Without the flag the projection would write "linked A"
    into the user's history twice for one link. The two cannot disagree with
    ``changed_fields["due_journal_id"][0]``, because both come from the same
    argument; the id is named separately so a consumer reads a link as a link
    rather than by indexing into a field change, and so the phase that replaces
    it has one key to remove.

    **``changed_fields`` is built here, unlike** ``TaskUpdated``\\ **'s.** That
    event is handed a dict because its caller decides, field by field, what
    moved. Retargeting decides nothing of the sort: it always lands the task
    *not done*, so whether that is a *change* follows from the status it started
    in. Putting the rule here keeps one definition of it, and keeps a
    "not done → not done" line out of the user's history on every ordinary
    deferral — while a reopen, which the specification singles out as rarely
    what the user meant, reaches the stream rather than only the task row.
    """

    def __init__(
        self,
        task_id: int,
        user_id: str,
        previous_due_journal_id: int,
        due_journal_id: int,
        previous_status: TaskStatus,
        auto_link_created: bool,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        changed_fields: dict[str, Any] = {
            "due_journal_id": (previous_due_journal_id, due_journal_id)
        }
        if previous_status is not TaskStatus.NOT_DONE:
            # ``.value`` puts a plain ``str`` in the payload rather than a
            # ``TaskStatus``. **Not to keep ``json.dumps`` happy** — ``TaskStatus``
            # is a ``StrEnum``, so it serialises to the same ``"done"`` either
            # way, and the claim written the other way round elsewhere in this
            # module is wrong. The reason is that the payload is a wire format: a
            # member reaching it would hand an in-process subscriber a domain type
            # where one reading the same event back out of Redis gets a bare
            # string, which is exactly the difference this module exists to keep
            # invisible.
            changed_fields["status"] = (
                previous_status.value,
                TaskStatus.NOT_DONE.value,
            )
        super().__init__(
            event_id=f"task_due_journal_retargeted_{task_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=task_id,
            event_type="TaskDueJournalRetargeted",
            event_data={
                "task_id": task_id,
                "user_id": user_id,
                "changed_fields": changed_fields,
                "auto_linked_journal_id": previous_due_journal_id,
                "auto_link_created": auto_link_created,
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

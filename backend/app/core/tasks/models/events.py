"""Domain events for the tasks domain.

The specification makes tasks first-class domain entities: they "emit domain
events through the same transactional outbox and stream that contacts and
journals use, and those events project into field history exactly as contact and
journal events do", each carrying provenance and the actor.

This module holds creation, every change to the task's own fields — text, status
and contact membership — due-journal retargeting, intermediate journal links and
hard deletion. That is the full event set the specification names. The history
projection that reads these payloads lands in a later phase.

**A task's text, status and contact changes share one event**, ``TaskUpdated``,
carrying ``changed_fields`` — not one event type per field. The phases that added
them were each worded as though there would be two classes, and this is the
deliberate divergence: a single ``PATCH`` may reword a task *and* complete it,
which is one write in one unit of work, and two events would announce two things
where one happened. ``JournalUpdated``, ``ContactUpdated``, ``RouteUpdated`` and
``GearItemUpdated`` all take this shape, and
``HistoryService._rows_from_changed_fields`` fans a ``changed_fields`` dict out
into one ``field_history`` row per field — so the user still reads a distinct
"text" line, a distinct "status" line and a distinct line per person in their
history, which is the whole of what per-field event types would have bought.

**Contact membership is a field, and journal links are not** — an asymmetry
worth stating, because the two look alike from a distance. A journal link has
structure to carry: :class:`TaskJournalLinked` has an ``origin``, because two
different writes cause the same fact, and it is half of the ordered pair a
retarget publishes. A contact link has neither. The specification calls it *"a
plain reference"* carrying no relationship type, role or attendance status, and
it has exactly one cause — somebody asking for it — since a create announces its
own contacts here and a contact delete cascades without anyone acting on the
task. There is nothing a dedicated type would carry that a ``changed_fields``
entry does not.

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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection


def contact_field_name(contact_id: int) -> str:
    """The ``changed_fields`` key a contact's membership is recorded under.

    One key **per contact** rather than a shared ``"contacts"`` field, following
    the collection prefixes ``journal_write_service`` already uses for nested
    rows (``plan:doc``, ``abseil:pitch``). The reason is the projection's dedup:
    history rows are written ``ON CONFLICT (event_id, entity_type, entity_id,
    field_name) DO NOTHING``, so two people sharing a field name would collide on
    all four columns and the second would be discarded as a redelivery of the
    first — one of them silently missing from the user's own history.

    A function rather than an f-string at the two call sites, because the
    service builds these keys and the projection will later have to recognise
    them, and a format that lives in two places is one that can drift.
    """
    return f"contact:{contact_id}"


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

    The payload carries the task as it was persisted: its text, its status, both
    anchors and **the people it was created with**.

    ``contact_ids`` answers the question the phase that wrote this class left
    open — whether a create naming contacts publishes one event or two. It
    publishes **one**, because a create is one write and because contact
    membership is a field of the task rather than an aggregate of its own (see
    the module docstring). Leaving it out was the alternative, and it would put a
    later unlink's "removed Sarah" line in a history with no "added Sarah" line
    anywhere before it.

    The value is the ids a link row was actually **written** for, in the order
    the caller named them — ``TaskService._link_contacts``' return, not the
    request's list. On a create the two coincide, since a new task has no links
    to collide with; taking the written set anyway keeps this event saying what
    happened rather than what was asked for, which is what every other payload
    here does.

    **It has no default**, unlike every other optional argument on these events.
    There is no safe one: ``[]`` is correct for the ordinary create and a lie for
    the one that named people, and the failure would be silent — a task with
    three people on it whose own creation event says nobody was involved.
    :class:`TaskJournalLinked`'s ``origin`` has no default for the same reason.
    """

    def __init__(
        self,
        task_id: int,
        user_id: str,
        text: str,
        status: TaskStatus,
        creating_journal_id: int,
        due_journal_id: int,
        contact_ids: Sequence[int],
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
                # Copied into a ``list`` rather than stored as handed over: the
                # payload is a wire format, and a caller's tuple would serialise
                # to the same JSON while handing an in-process subscriber a type
                # a reader coming back through Redis never sees.
                "contact_ids": list(contact_ids),
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class TaskUpdated(DomainEvent):
    """Event raised when a field of the task changes.

    Three kinds of change reach this one type: a reword, a status move, and a
    contact being linked or unlinked. They arrive from different write paths —
    :meth:`TaskService.update_task` owns text and status, and
    :meth:`TaskService.link_contact` / :meth:`~TaskService.unlink_contact` own
    membership — but each is one write announcing one event.

    **One event for one write**, carrying ``changed_fields`` in the
    ``{field: (old, new)}`` shape every other updated-event in this codebase
    uses. ``TaskService.update_task`` owns text and status precisely because a
    ``PATCH`` may carry both and JSON:API says a request is one change; the
    event follows that, rather than splitting a single unit of work into two
    announcements. See the module docstring for why this diverges from the
    phases' "event classes" wording, twice.

    **Contact membership is written as** ``{contact_field_name(id): (None, id)}``
    for a link and ``{...: (id, None)}`` for an unlink — the shape
    ``JournalTagAssigned`` already projects, where the absent side is the state
    the link did not have. The direction is carried by *position* alone, since
    ``_rows_from_changed_fields`` never reads the key, so a pair built the wrong
    way round renders a link as a removal in somebody's own history with nothing
    downstream able to notice. No contact name travels: the service holds an id,
    and reading a name would add a query to a method that performs none — and
    would fail on exactly the contact a user had just deleted, which is the one
    :meth:`~TaskService.unlink_contact` is most likely to be called about.

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

    **One of the two events a retarget publishes.** A retarget does two things —
    it moves the due anchor and retains the journal being left as an
    *intermediate* journal, the model's one automatic link — and this announces
    only the anchor move. The link is a :class:`TaskJournalLinked` of its own,
    the same type a manual attach publishes, carrying
    ``origin=TaskJournalLinkOrigin.RETARGET``.

    **The link goes out first, and this event second**, because
    :meth:`TaskService.retarget_due_journal` writes the link before it moves the
    anchor and each event is published directly after the write it announces. A
    consumer reading the pair therefore renders the trail in the order it
    happened. Pinned by
    ``test_the_link_and_the_move_are_published_in_that_order`` and, over the
    stored rows a consumer actually reads, by
    ``test_the_link_and_the_move_are_appended_in_that_order``.

    **The two keys that used to stand in for that link are gone.** While the link
    type did not exist, this payload carried ``auto_linked_journal_id`` (the
    journal retained) and ``auto_link_created`` (whether a row was written for
    it). The first is now the link event's ``journal_id``. The second is now the
    difference between publishing a link event and publishing none — which is the
    same fact expressed where a consumer can act on it, since a retarget only
    ever *adds* an intermediate link and never removes one, so a task retargeted
    A→B→A→C finds A still attached when it leaves it the second time and must not
    have "linked A" written into its history twice.

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
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


class TaskJournalLinkOrigin(StrEnum):
    """Why an intermediate-journal link exists.

    Two writes produce the same fact about a task — a person attached a journal
    it was discussed in, or a retarget retained the journal it has just left, the
    model's one automatic link — so both publish :class:`TaskJournalLinked` and
    this says which happened.

    **This is not provenance, and the difference is the point.** ``source``
    records *who acted*; a retarget is something the user did, so a link derived
    from one performed in the browser is ``Provenance.UI``. ``SYSTEM`` is for a
    write no person triggered, such as an integration sync. What is derived is
    the link's *cause*, and naming it here lets a consumer separate the two
    without being told the wrong thing about the actor.

    Lives beside the events rather than in ``core_shared.models.tasks``: it is
    payload vocabulary, not part of the task model, and nothing outside this
    backend reads it.
    """

    MANUAL = "manual"
    RETARGET = "retarget"


@dataclass(frozen=True)
class TaskJournalLinked(DomainEvent):
    """Event raised when a journal becomes one of a task's intermediate links.

    The specification's *"journal linked or unlinked"*. Only *intermediate*
    journals are linked this way, so the name needs no qualifier: the creating
    anchor is set once and never changes, and the due anchor moves by retargeting
    — which publishes :class:`TaskDueJournalRetargeted` for the move and this for
    the journal it retains.

    **Published only when a row was actually written.**
    ``add_intermediate_journal`` is idempotent, and a retarget only ever adds a
    link, so a task retargeted A→B→A→C leaves A a second time while A is still
    linked from the first departure. Announcing that would write the same link
    into the user's history twice, so the service publishes nothing when the
    repository reports no row was created. This is where the previous phase's
    ``auto_link_created`` flag went: the same fact, expressed as whether the
    event exists.

    **No journal title travels.** The service holds an id, and reading a title
    would add a query to a method that deliberately performs none.
    ``JournalTagAssigned`` projects as ``old_value=None, new_value=<the thing
    linked>``, a shape an id satisfies.

    **``event_id`` names the journal as well as the task**, unlike every other
    event here. Those are about the task, so two of a kind are separated by the
    clock; two links are not, because one task can gain several journals — and
    the history projection writes ``ON CONFLICT DO NOTHING`` over ``event_id``,
    so a collision would drop one link as a redelivery of the other.
    """

    def __init__(
        self,
        task_id: int,
        user_id: str,
        journal_id: int,
        origin: TaskJournalLinkOrigin,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"task_journal_linked_{task_id}_{journal_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=task_id,
            event_type="TaskJournalLinked",
            event_data={
                "task_id": task_id,
                "user_id": user_id,
                "journal_id": journal_id,
                # ``.value`` for the reason the status pairs carry it: the
                # payload is a wire format, and a ``StrEnum`` member in it hands
                # an in-process subscriber a domain type where a reader coming
                # back through Redis gets a bare string.
                "origin": origin.value,
                "source": source.value,
                "changed_by": changed_by,
            },
            transaction=transaction,
        )


@dataclass(frozen=True)
class TaskJournalUnlinked(DomainEvent):
    """Event raised when an intermediate-journal link is removed from a task.

    **No ``origin``**, unlike its counterpart. That event has two causes and has
    to name one; this has exactly one — a user asking for the link to go —
    because the other two ways a link row disappears announce nothing at all: a
    journal merge collapsing redundant links, which belongs to the phase that
    gives the merge its task-scoped events, and a journal delete cascading, which
    removes the row without anybody acting on the task. A key with one possible
    value would advertise a second case that does not exist.

    **Published only when a row was actually removed**, so a detach of a link
    that was not there is silent, as is the refusal a detach of an anchor raises.
    """

    def __init__(
        self,
        task_id: int,
        user_id: str,
        journal_id: int,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
        transaction: AsyncConnection | None = None,
    ):
        now = datetime.now(tz=UTC)
        super().__init__(
            event_id=f"task_journal_unlinked_{task_id}_{journal_id}_{now.isoformat()}",
            occurred_at=now,
            aggregate_id=task_id,
            event_type="TaskJournalUnlinked",
            event_data={
                "task_id": task_id,
                "user_id": user_id,
                "journal_id": journal_id,
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

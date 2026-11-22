"""The tasks domain's service layer, where the core invariants live.

The specification calls the task invariants *absolute* and requires them at
**every** entry point, MCP included. They are therefore enforced here rather than
in a controller: REST and MCP are both thin callers of this service, so neither
can drift from the other or forget a rule.

What this layer owns, and why it cannot live anywhere else:

- **both anchors exist and belong to the acting user** — needs journal data, so
  the repository (which knows only tasks) cannot check it;
- **the due journal is future-dated** — needs the user's configured timezone as
  well, and is judged with the journal domain's
  :mod:`~app.core.journal.services.journal_date_resolver`, never re-derived here;
- **referenced contacts exist** — needs the contact domain.

What it deliberately does not own: the entity's own rules (non-empty text, both
anchor ids present) stay on :class:`~core_shared.models.tasks.Task`, and task
ownership stays in the owner-scoped repository.

**Invariant 4 is a write-time rule.** The future-dated check happens at the
moment a due journal is set — on creation *and* on every retarget — and at no
other time. Nothing re-validates it on read, which is exactly what makes a
*lapsed* task — one whose due journal has since passed — reachable rather than
unloadable, and retargeting the way it is brought back.
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from core_shared.models.history import Provenance
from core_shared.models.journals import JournalNotFoundError
from core_shared.models.tasks import (
    Task,
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskJournalAnchor,
    TaskJournalIsAnchorError,
    TaskListNotFoundError,
    TaskListTaskClosedError,
    TaskListTaskNotDueInJournalError,
    TaskNotFoundError,
    TaskReopenNotAcknowledgedError,
    TaskStatus,
    TaskStatusTransitionError,
    TaskValidationError,
    ensure_due_date_allowed,
    is_status_transition_allowed,
)
from sqlalchemy.exc import IntegrityError

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.services.journal_date_resolver import (
    is_future_dated,
    journal_date,
    today_in,
)
from app.core.tasks.models.events import (
    TaskCreated,
    TaskDeleted,
    TaskDueJournalRetargeted,
    TaskJournalLinked,
    TaskJournalLinkOrigin,
    TaskJournalUnlinked,
    TaskUpdated,
    contact_field_name,
)
from app.infrastructure.unit_of_work import savepoint, transactional
from app.shared.patch import UNSET, Unset

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from core_shared.models.journals import Journal
    from core_shared.models.tasks import TaskIcon
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.core.contacts.models.repositories import ContactRepository
    from app.core.journal.models.repositories import JournalRepository
    from app.core.journal.services.journal_date_resolver import JournalDateResolver
    from app.core.tasks.models.repositories import (
        TaskListRepository,
        TaskRepository,
    )
    from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


def _ordered_unique(values: Iterable[int]) -> list[int]:
    """``values`` with duplicates dropped, keeping first-mention order."""
    return list(dict.fromkeys(values))


# The anchor columns, as the violated constraint names them. Matching on the
# column rather than on PostgreSQL's generated constraint name keeps this from
# depending on how an unnamed foreign key happens to be named; the column is a
# name migration 0105 chose.
_ANCHOR_COLUMNS: tuple[tuple[TaskJournalAnchor, str], ...] = (
    ("creating", "creating_journal_id"),
    ("due", "due_journal_id"),
)


# The foreign key an intermediate link takes on the journal it names. Matched in
# full rather than by its column, because ``journal_id`` on its own also appears
# in the table's *primary key* violations.
_INTERMEDIATE_JOURNAL_FK = "task_intermediate_journals_journal_id_fkey"


def _driver_message(error: IntegrityError) -> str:
    """The database's own message, without the statement SQLAlchemy appends.

    This distinction is the whole of the matching below. ``str(error)`` includes
    the failing ``INSERT``, whose column list names **both** anchors, so any
    match against it reports whichever the loop tests first — a bug that passes
    every test built on a hand-written error and fails against a real one.
    """
    return str(error.orig) if error.orig is not None else ""


def _violated_anchor(error: IntegrityError) -> TaskJournalAnchor | None:
    """Which anchor a foreign-key violation is about, if it is about one."""
    message = _driver_message(error)
    for anchor, column in _ANCHOR_COLUMNS:
        if column in message:
            return anchor
    return None


def _refuse_anchor_role(task: Task, task_id: int, journal_id: int) -> None:
    """Refuse a journal that is already one of the task's two anchors.

    Both directions of the intermediate-link surface share this: an anchor
    cannot be attached (it is already linked, in a role a link row cannot
    express) and cannot be detached (it is a column, so there is no row to
    remove). One rule, checked in one place, so the two surfaces cannot drift.

    Invariant 6 lets a task have the *same* journal in both roles, so the order
    below is a decision rather than an accident: the **creating** anchor is
    reported, because it is the one that can never be moved and is therefore the
    more useful half to tell the caller about.

    ``task_id`` is passed in rather than read off the entity: the caller looked
    the task up by that id, so it is known to be an ``int`` there and would need
    a redundant narrowing check here.
    """
    # ``None`` for a list task's missing anchor, which equals no journal id.
    roles: tuple[tuple[TaskJournalAnchor, int | None], ...] = (
        ("creating", task.creating_journal_id),
        ("due", task.due_journal_id),
    )
    for anchor, anchor_journal_id in roles:
        if anchor_journal_id == journal_id:
            raise TaskJournalIsAnchorError(task_id, journal_id, anchor)


def _check_arrangement(task_ids: Sequence[int], anchors: dict[str, int | None]) -> None:
    """Refuse a block that is malformed whatever the list holds.

    Checked before anything is read, so these answers never depend on the
    list's state: an empty or repeating block, both anchors, or an anchor
    inside the block.
    """
    if not task_ids:
        raise TaskValidationError("task_ids", "name at least one task")
    seen: set[int] = set()
    for named in task_ids:
        if named in seen:
            raise TaskValidationError("task_ids", f"task {named} is named twice")
        seen.add(named)
    given = [field for field, anchor in anchors.items() if anchor is not None]
    if len(given) > 1:
        raise TaskValidationError(
            "before_task_id", "give after_task_id or before_task_id, not both"
        )
    for field in given:
        if anchors[field] in seen:
            raise TaskValidationError(
                field, f"task {anchors[field]} is in the block it would anchor"
            )


class TaskService:
    """Creates tasks, edits them, retargets them, links their people, deletes them.

    Every operation enforces the specification's rules here rather than at a
    surface: the core invariants on creation, the status transition matrix on a
    status change, the entity's text rule on an edit, the invariants again on a
    retarget — because a due journal is being set for a second time — contact
    existence on a link, and owner scoping throughout. REST and MCP are thin
    callers of each.

    It also **announces what it did**. Tasks are first-class domain entities, so
    a write publishes its domain event through the transactional outbox in the
    same unit of work as the write itself: the two commit together or neither
    does, and a rejected write publishes nothing. Provenance comes from the
    caller, so the UI, an AI agent over MCP and an internal caller stay
    distinguishable in a task's history.

    **A task on an archived list is read-only**, as the list is: every write
    below refuses one with ``TaskListArchivedError`` (409) through
    :meth:`_hold_list_writable`, the one place it consults
    :meth:`~core_shared.models.tasks.TaskList.ensure_writable`. The list is held
    ``FOR SHARE`` after the task has been read or locked — **the task, then its
    list** — so an archive cannot land between the check and the write, and
    writes to different tasks on one list never wait for each other.
    """

    def __init__(
        self,
        task_repo: TaskRepository,
        task_list_repo: TaskListRepository,
        journal_repo: JournalRepository,
        contact_repo: ContactRepository,
        date_resolver: JournalDateResolver,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.task_repo = task_repo
        self.task_list_repo = task_list_repo
        self.journal_repo = journal_repo
        self.contact_repo = contact_repo
        self.date_resolver = date_resolver
        self.event_publisher = event_publisher

    @transactional
    async def create_task(
        self,
        *,
        user_id: str,
        creating_journal_id: int,
        due_journal_id: int,
        text: str,
        transaction: AsyncConnection,
        contact_ids: Sequence[int] | None = None,
        now: datetime.datetime | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> Task:
        """Create a task anchored to two of the user's journals.

        The creating journal is the journal the task is created *from* — the
        caller supplies it from context, never as a user's separate choice — and
        the due journal is the future moment the commitment matters. The two may
        be the same journal.

        Everything is validated before anything is written, so a rejected create
        leaves no partial task behind.

        Publishes :class:`~app.core.tasks.models.events.TaskCreated` through the
        transactional outbox **in this unit of work**, so the event and the task
        commit together or not at all. A rejected create therefore publishes
        nothing — the activity-history specification's *integrity by
        construction*: history cannot record a change that did not occur.

        Args:
            user_id: The acting user; both journals must be theirs
            creating_journal_id: The journal the commitment arose in
            due_journal_id: The future-dated journal it is due in
            text: The commitment, as plain text
            transaction: The request connection; the unit of work commits here
            contact_ids: Optional contacts to reference; duplicates are ignored
            now: The instant "today" is derived from, defaulting to the real
                clock. **Never bind this from client input.** It exists so a
                test can stand either side of a local midnight — there is no
                clock-freezing library in this repo — and a request that could
                set it would make invariant 4 opt-out for any caller. Controllers
                and MCP tools must not accept it, and their request schemas must
                not carry a field of this name.
            source: Where the create came from, recorded on the event. Defaults
                to ``SYSTEM`` rather than to a surface, so a caller that forgets
                to say is never mistaken for a user acting in the UI.
            changed_by: The actor, as the other domains write it — the literal
                ``"ui"`` or ``"mcp"`` rather than a user id, which the payload
                already carries.

        Returns:
            The persisted task, carrying its database-assigned id.

        Raises:
            TaskValidationError: When the text is empty or an anchor id is absent.
            TaskAnchorJournalNotFoundError: When either anchor does not exist or
                is not the acting user's.
            TaskDueJournalNotFutureError: When the due journal's date is not
                after today in the user's timezone.
            ContactNotFoundError: When a referenced contact does not exist.
        """
        # The entity's own rules first: they need no I/O, so a bad request costs
        # no queries.
        task = Task(
            user_id=user_id,
            text=text,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
        )

        due_journal = await self._resolve_anchors(
            user_id, creating_journal_id, due_journal_id
        )
        await self._require_future_dated(user_id, due_journal_id, due_journal, now)
        contacts = await self._resolve_contacts(contact_ids, user_id=user_id)

        created = await self._save(task)
        # This path only ever makes a journal-only task, so both anchors are
        # set; a saved row without one is a broken invariant, not a list task.
        created.require_anchor("creating")
        created.require_anchor("due")
        await self._link_and_announce_created(
            created,
            contacts,
            transaction=transaction,
            source=source,
            changed_by=changed_by,
        )
        return created

    @transactional
    async def create_list_task(
        self,
        *,
        user_id: str,
        task_list_id: int,
        text: str,
        transaction: AsyncConnection,
        due_date: datetime.date | None = None,
        due_journal_id: int | None = None,
        contact_ids: Sequence[int] | None = None,
        now: datetime.datetime | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> Task:
        """Create a task on one of the user's lists, at the bottom of it.

        The task has no creating journal and is undated, due on ``due_date``
        (today or later in the user's timezone), or due in ``due_journal_id``
        (dated in the future, the rule a journal-only task's due journal
        follows) — never both, which is spec *Core invariant* 4 and the
        entity's own refusal. It joins the bottom of the list, closed tasks
        included.

        **Lock order: the due journal, then the list, then the new row.** A due
        journal is read ``FOR KEY SHARE`` first — the lock the insert's foreign
        key would take anyway — because a retarget holds journals before its
        task and list, and a journal delete holds the journal before its tasks;
        taking the journal *after* the list would let a create close a cycle
        with them. The list is then read ``FOR NO KEY UPDATE`` — not the share
        lock the other task writes take through :meth:`_hold_list_writable` —
        because the insert computes the list's bottom under that same lock.
        Taking share first and update second would be a lock upgrade, and two
        creates on one list would each wait for the other's share lock. Holding
        the update lock also holds off an archive, which takes the same lock,
        and serialises creates so each computes the bottom once.

        A journal delete racing the create is therefore settled by the journal
        row: one that got there first makes the create wait and then find no
        journal; a create that got there first makes the delete wait, and its
        detach then finds the new task and unlinks it (it becomes undated).

        Refusals come in this order, and a refused create writes and publishes
        nothing: the entity's own rules (no I/O), the list not found, the due
        journal not found, a contact not found, the list archived, then the due
        date before today or the due journal not in the future. An archived
        list comes before the dates because correcting a date would not make
        the create succeed.

        Publishes :class:`~app.core.tasks.models.events.TaskCreated`, carrying
        the list, the due date and the due journal, in this unit of work.

        Args:
            user_id: The acting user; the list, the due journal and contacts
                must be theirs
            task_list_id: The list to create the task on
            text: The commitment, as plain text
            transaction: The request connection; the unit of work commits here
            due_date: The day it is due, or ``None``
            due_journal_id: The future journal it is due in, or ``None``
            contact_ids: Optional contacts to reference; duplicates are ignored
            now: The instant "today" is derived from, defaulting to the real
                clock. **Never bind this from client input**, for the reason
                :meth:`create_task` gives.
            source: Where the create came from, recorded on the event
            changed_by: The actor, ``"ui"`` or ``"mcp"`` as the other domains
                write it

        Returns:
            The persisted task, carrying its id and its position on the list.

        Raises:
            TaskValidationError: When the text is empty.
            TaskListNotFoundError: When the list does not exist or is not the
                acting user's.
            TaskAnchorJournalNotFoundError: When the due journal does not exist
                or is not the acting user's (anchor ``"due"``).
            ContactNotFoundError: When a referenced contact does not exist.
            TaskListArchivedError: When the list is archived.
            TaskDueDateInPastError: When the due date is before today in the
                user's timezone.
            TaskDueJournalNotFutureError: When the due journal's date is not
                after today in the user's timezone.
        """
        task = Task(
            user_id=user_id,
            text=text,
            task_list_id=task_list_id,
            due_date=due_date,
            due_journal_id=due_journal_id,
        )

        due_journal = (
            None
            if due_journal_id is None
            else await self._lock_due_journal(user_id, due_journal_id)
        )
        task_list = await self.task_list_repo.find_by_id_for_update(
            task_list_id, user_id
        )
        if task_list is None:
            raise TaskListNotFoundError(task_list_id)
        if due_journal_id is not None and due_journal is None:
            raise TaskAnchorJournalNotFoundError("due", due_journal_id)
        contacts = await self._resolve_contacts(contact_ids, user_id=user_id)
        task_list.ensure_writable()
        if due_date is not None:
            await self._require_due_date_allowed(user_id, due_date, now)
        if due_journal_id is not None and due_journal is not None:
            await self._require_future_dated(user_id, due_journal_id, due_journal, now)

        created = await self._save(task)
        await self._link_and_announce_created(
            created,
            contacts,
            transaction=transaction,
            source=source,
            changed_by=changed_by,
        )
        return created

    async def _link_and_announce_created(
        self,
        created: Task,
        contacts: Sequence[int],
        *,
        transaction: AsyncConnection,
        source: Provenance,
        changed_by: str,
    ) -> None:
        """Link a new task's contacts, then publish its ``TaskCreated``.

        Last, and deliberately: the event announces a create that finished,
        links included, following the journal tag service's ordering. It reads
        the *persisted* task because the id it carries exists only after the
        save, and that id is what the history projection files rows under.

        ``linked`` rather than ``contacts``: the payload names the ids a row was
        actually written for, as every other event here names what happened
        rather than what was asked for. The two coincide on a create — a new
        task has no links to collide with — which is exactly why taking the
        written set costs nothing and stops mattering only if that ever changes.
        """
        assert created.id is not None, "Task ID must be set after save"
        linked = await self._link_contacts(
            created.id, contacts, created.user_id, transaction
        )
        await self.event_publisher.publish(
            TaskCreated(
                task_id=created.id,
                user_id=created.user_id,
                text=created.text,
                status=created.status,
                task_list_id=created.task_list_id,
                due_date=created.due_date,
                creating_journal_id=created.creating_journal_id,
                due_journal_id=created.due_journal_id,
                contact_ids=linked,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )

    @transactional
    async def create_list_task_with_trail(
        self,
        *,
        user_id: str,
        task_list_id: int,
        text: str,
        transaction: AsyncConnection,
        due_date: datetime.date | None = None,
        due_journal_id: int | None = None,
        contact_ids: Sequence[int] | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> tuple[Task, list[int]]:
        """:meth:`create_list_task`, and the journals the new task has passed through.

        Empty in practice, and read rather than assumed for the reason
        :meth:`create_task_with_trail` gives. ``source`` and ``changed_by`` are
        forwarded, never defaulted here.
        """
        created = await self.create_list_task(
            user_id=user_id,
            task_list_id=task_list_id,
            text=text,
            transaction=transaction,
            due_date=due_date,
            due_journal_id=due_journal_id,
            contact_ids=contact_ids,
            source=source,
            changed_by=changed_by,
        )
        return created, await self._trail_within_unit_of_work(created, user_id)

    @transactional
    async def update_task(
        self,
        *,
        user_id: str,
        task_id: int,
        transaction: AsyncConnection,
        text: str | None = None,
        status: TaskStatus | None = None,
        flagged: bool | None = None,
        icon: TaskIcon | None | Unset = UNSET,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> Task:
        """Change one of the user's tasks: its text, status, flag or icon.

        **One method owns every field** because a ``PATCH`` may carry several,
        and JSON:API says a request is one change. Applying them as two calls would
        be two units of work and two read-decide-write sequences, so a client
        that reworded and completed a task in one request could have half of it
        applied. Here it is one read, one decision and one write.

        **No journal is involved**, for any field. The due journal is not read,
        which is what keeps a *lapsed* task both completable and editable: the
        future-dated rule is a write-time rule about *setting* a due journal, and
        re-applying it here would make exactly the tasks a user most needs to
        tidy up the ones they cannot.

        A call that changes nothing is a no-op: nothing is written, so
        ``updated_at`` does not move, **no event is published** and no change is
        recorded that did not happen. That covers the status, text, flag or icon a
        task already has (clearing an icon it does not have included), and — for
        a caller that is not a JSON:API surface — naming nothing.

        **One write publishes one** ``TaskUpdated``, carrying ``changed_fields``
        for whichever fields moved. Not one event per field: a ``PATCH`` may
        reword a task and complete it, and that is a single unit of work, so
        splitting it into two announcements would report two changes where one
        happened. The pairs are what the method already decided — the old value
        comes from the locking read, which is the only place it still exists
        once the row is saved — so the payload names a change the service made
        rather than a field the caller mentioned.

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to change
            transaction: The request connection; the unit of work commits here
            text: The new text, or ``None`` to leave it alone. Validated by the
                entity rather than here, so there is one definition of an
                acceptable task rather than two that can drift apart.
            status: The status to move to, or ``None`` to leave it alone
            flagged: Flag or unflag the task, or ``None`` to leave it alone. A
                task is always one or the other, so there is no third value.
            icon: An icon from the fixed set, ``None`` to **clear** it, or
                ``UNSET`` (the default) to leave it alone — the one argument
                where ``None`` is a value rather than "not named", because an
                icon is optional on the task.
            source: Where the change came from, recorded on the event
            changed_by: The actor, as the other domains write it

        Returns:
            The changed task — or the unchanged one, when nothing differed.

        **The read takes a row lock**, because this method decides from what it
        read and then writes that decision back. Without the lock two
        overlapping calls both read the old status, both find their transition
        allowed, and the later write wins — so cancelling a task while somebody
        else marks it done leaves it *done*, which is precisely the transition
        the matrix refuses. Raised by review on Phase 6's pull request. The lock
        lasts until the enclosing unit of work commits, so the second call waits
        and then decides against the state the first one actually wrote.

        Raises:
            TaskValidationError: When the new text is empty or blank.
            TaskNotFoundError: When the task does not exist or is not the acting
                user's. The two are indistinguishable by design.
            TaskStatusTransitionError: When the transition is refused — that is,
                when it would leave *cancelled*, which only retargeting does.
            TaskListArchivedError: When the task is on an archived list —
                setting a value it already has included.
        """
        task = await self.task_repo.find_by_id_for_update(task_id, user_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # Before the no-op comparison: an archived list's task is not writable,
        # which includes being "written" to the value it already has.
        await self._hold_list_writable(task.task_list_id, task_id, user_id)

        updated = task
        # Built as the decisions are made rather than by diffing the two tasks
        # afterwards: the decision is where a change is distinguished from a
        # resent value, and recovering that from a before/after comparison would
        # be a second implementation of the same rule.
        changed_fields: dict[str, Any] = {}

        # The entity's own rule first, as on creation: a blank text is wrong
        # outright, while a refused transition depends on state the caller may
        # not have known. ``replace`` re-runs ``__post_init__``, so the check is
        # the entity's rather than a second copy of it living here.
        if text is not None and text != task.text:
            updated = replace(updated, text=text)
            changed_fields["text"] = (task.text, text)

        if status is not None and status != task.status:
            if not is_status_transition_allowed(task.status, status):
                raise TaskStatusTransitionError(task.status, status)
            updated = replace(updated, status=status)
            # ``.value`` because the payload is a wire format and should carry a
            # plain ``str``. Not because ``json.dumps`` would refuse the member:
            # ``TaskStatus`` is a ``StrEnum`` and serialises to the same
            # ``"done"``, so the comment that used to stand here was wrong.
            changed_fields["status"] = (task.status.value, status.value)

        # Flag and icon apply to every task, journal-only ones included, and in
        # any status: nothing here reads a journal or a list rule. Neither moves
        # the task — ``save`` never writes list membership or position.
        if flagged is not None and flagged != task.flagged:
            updated = replace(updated, flagged=flagged)
            changed_fields["flagged"] = (task.flagged, flagged)

        if not isinstance(icon, Unset) and icon != task.icon:
            updated = replace(updated, icon=icon)
            # The plain key, as ``TaskListUpdated`` carries a list's icon.
            changed_fields["icon"] = (
                None if task.icon is None else task.icon.value,
                None if icon is None else icon.value,
            )

        if updated is task:
            return task

        saved = await self.task_repo.save(updated)

        # After the save, so the event announces a change that finished. The
        # ids come from the arguments rather than off the saved row: unlike a
        # create, both were known before the write, and ``Task.id`` is optional
        # on the entity because an unsaved one has none.
        await self.event_publisher.publish(
            TaskUpdated(
                task_id=task_id,
                user_id=user_id,
                changed_fields=changed_fields,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return saved

    @transactional
    async def link_contact(
        self,
        *,
        user_id: str,
        task_id: int,
        contact_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> bool:
        """Link a contact to one of the user's tasks.

        A task-contact link is a **plain reference**: the specification is
        explicit that it carries no relationship type, no role and no attendance
        status, and nothing anywhere parses contacts out of the task text. There
        is correspondingly nothing to pass but the two ids.

        **Editable in any status.** No status is read and none is written, so a
        done or cancelled task takes a link exactly as an open one does — which
        is what the specification means by *"task text and contact links can be
        edited at any time, in any status"*.

        **Idempotent.** Linking a contact that is already linked succeeds and
        writes nothing; the return value is the only way to tell the two apart,
        and a surface is free to ignore it.

        **Publishes a** :class:`~app.core.tasks.models.events.TaskUpdated`
        **when a row was written**, carrying the membership change in
        ``changed_fields`` — not an event type of its own. Contact membership is
        a field of the task, and a plain reference has nothing a dedicated type
        would carry; see the events module for why journal links went the other
        way. The idempotent repeat above publishes **nothing**, because no row
        moved and announcing it would put a second "added Sarah" line in the
        user's history for a link that did not change.

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to link
            contact_id: The contact to reference
            transaction: The request connection; the unit of work commits here
            source: Where the link was asked for, recorded on the event.
                Defaults to ``SYSTEM`` rather than to a surface, so a caller
                that forgets to say is never mistaken for a person acting in the
                browser.
            changed_by: The actor, as the other domains write it — the literal
                ``"ui"`` or ``"mcp"`` rather than a user id, which the payload
                already carries.

        Returns:
            ``True`` when a link row was created, ``False`` when it was already
            there.

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's. The two are indistinguishable by design.
            ContactNotFoundError: When the contact does not exist or is not the
                acting user's. The two are indistinguishable by design.
            TaskListArchivedError: When the task is on an archived list —
                linking a contact it already has included.
        """
        contacts = await self._resolve_contacts([contact_id], user_id=user_id)
        # After the contact, so a request that was already wrong keeps its 404.
        await self._require_writable_task(task_id, user_id)
        created = await self._link_contacts(task_id, contacts, user_id, transaction)
        linked = contact_id in created
        if linked:
            await self._publish_contact_change(
                task_id=task_id,
                user_id=user_id,
                change=(None, contact_id),
                contact_id=contact_id,
                transaction=transaction,
                source=source,
                changed_by=changed_by,
            )
        return linked

    @transactional
    async def unlink_contact(
        self,
        *,
        user_id: str,
        task_id: int,
        contact_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> bool:
        """Remove a contact link from one of the user's tasks.

        **The contact is not required to still exist**, which is the deliberate
        asymmetry with :meth:`link_contact`. ``task_contacts.contact_id``
        cascades, so a deleted contact's links are already gone; demanding the
        contact here would make the one call a user might reach for while
        tidying up fail on exactly the contact they had just removed.

        Idempotent for the same reason ``DELETE`` is: unlinking a contact that
        is not linked changes nothing and says so.

        **Publishes a** :class:`~app.core.tasks.models.events.TaskUpdated`
        **when a row was removed**, carrying the same ``changed_fields`` key the
        link does with the pair the other way round — ``(contact_id, None)``.
        The direction is positional, because
        ``HistoryService._rows_from_changed_fields`` reads ``change[0]`` as the
        old value and never looks at the key. Nothing is published when there was
        no row to remove.

        No contact name is read to decorate the event, which is what keeps the
        asymmetry above intact: a display name would need the very lookup this
        method declines to perform, and would fail on exactly the contact
        somebody had just deleted.

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to unlink
            contact_id: The contact to stop referencing
            transaction: The request connection; the unit of work commits here
            source: Where the removal was asked for; defaults to ``SYSTEM``
            changed_by: The actor recorded on the event

        Returns:
            ``True`` when a link row was removed, ``False`` when there was none.

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's.
            TaskListArchivedError: When the task is on an archived list.
        """
        await self._require_writable_task(task_id, user_id)
        removed = await self.task_repo.remove_contact(task_id, contact_id, user_id)
        if removed:
            await self._publish_contact_change(
                task_id=task_id,
                user_id=user_id,
                change=(contact_id, None),
                contact_id=contact_id,
                transaction=transaction,
                source=source,
                changed_by=changed_by,
            )
        return removed

    async def _publish_contact_change(
        self,
        *,
        task_id: int,
        user_id: str,
        contact_id: int,
        change: tuple[int | None, int | None],
        transaction: AsyncConnection,
        source: Provenance,
        changed_by: str,
    ) -> None:
        """Announce a contact joining or leaving a task, in the field vocabulary.

        Shared by the two callers because the only thing that differs between
        them is which way round the pair goes, and a second copy of the key
        construction is a second place for the two to disagree about what a
        contact's field is called. The pair is the caller's, because *it* is the
        one that knows whether a row appeared or vanished.
        """
        await self.event_publisher.publish(
            TaskUpdated(
                task_id=task_id,
                user_id=user_id,
                changed_fields={contact_field_name(contact_id): change},
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )

    @transactional
    async def attach_intermediate_journal(
        self,
        *,
        user_id: str,
        task_id: int,
        journal_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> bool:
        """Link one of the user's journals to a task as an intermediate journal.

        An intermediate journal is one the task was *"discussed, revisited, or
        previously due"* in. This is the **explicit** half of that: nothing
        anywhere infers a link from where the user happened to be when they
        edited a task, so a link exists only because somebody asked for it here
        or because :meth:`retarget_due_journal` retained a previous due journal —
        the model's one automatic link.

        **The journal must be the acting user's**, which is enforced by the same
        owner-scoped read the anchors go through, so a journal belonging to
        somebody else is indistinguishable from one that never existed.

        **An anchor is not an intermediate link.** A journal that is already the
        task's creating or due journal is refused: it is already linked, in a
        role this table cannot express. The check costs nothing extra — the task
        has been read already — and its order relative to the journal read is
        unobservable, because an anchor is by construction a real journal of the
        caller's (the anchor columns are ``ON DELETE RESTRICT`` foreign keys that
        creation and retargeting both resolve owner-scoped).

        **Idempotent.** Attaching a journal that is already attached succeeds and
        writes nothing. There is no "is it already linked?" read: de-duplication
        is ``task_intermediate_journals``' composite primary key, so nothing can
        slip into a window between the question and the answer. Phase 7 made the
        same choice for the automatic link.

        **A ``TaskJournalLinked`` is published only when a row was written**, so
        the repeat above announces nothing. The event carries
        ``origin=MANUAL``, distinguishing a link the user asked for from the one
        :meth:`retarget_due_journal` derives, and it goes out *after* the write
        so it announces something that happened.

        **Editable in any status**, like a contact link. No status is read and
        none is written, so a done or cancelled task takes a link exactly as an
        open one does.

        **The task is read without a lock**, unlike :meth:`set_status` and
        :meth:`retarget_due_journal`. Those decide a *rule* from the status they
        read and write that decision back, which an interleaving can corrupt. The
        only state that can move underneath this method is a concurrent retarget
        making this journal the due anchor after the check — and the resulting
        shape, a due anchor that is also an intermediate link, is one
        :meth:`retarget_due_journal` produces on its own and Phase 7 explicitly
        declined to clean up ("nothing is ever unlinked, including a link that
        has become redundant"). A lock would narrow a window onto an outcome that
        is legitimate either side of it. It would also have to be ordered against
        journal merge the way :meth:`retarget_due_journal` now is — journal locks
        first, ascending, then the task row — which is real machinery to buy
        nothing observable.

        Args:
            user_id: The acting user; the task and the journal must be theirs
            task_id: The task to link
            journal_id: The journal it was discussed or revisited in
            transaction: The request connection; the unit of work commits here
            source: Where the link was asked for; defaults to ``SYSTEM`` so a
                caller that says nothing is never mistaken for a person
            changed_by: The actor recorded on the event

        Returns:
            ``True`` when a link row was created, ``False`` when it was already
            there.

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's. The two are indistinguishable by design.
            JournalNotFoundError: When the journal does not exist or is not the
                acting user's — the journal domain's own error, so the answer
                names the journal rather than describing it as a task anchor,
                which it is not.
            TaskJournalIsAnchorError: When the journal is already the task's
                creating or due journal.
            TaskListArchivedError: When the task is on an archived list.
        """
        task = await self._require_writable_task(task_id, user_id)
        await self._require_owned_journal(user_id, journal_id)
        _refuse_anchor_role(task, task_id, journal_id)

        try:
            created = await self.task_repo.add_intermediate_journal(
                task_id, journal_id, user_id
            )
        except IntegrityError as error:
            # The same race as ``_save``, one table over: the journal was proved
            # to exist a statement ago, and a delete since then must still read
            # as the 404 promised above rather than as a raw integrity error
            # rendered to the caller as a 500. No ``SAVEPOINT`` is needed, unlike
            # the batched contact insert: one journal is named per call, so the
            # violation can only be about that one and nothing has to run against
            # the aborted transaction to work out which.
            #
            # Matched on the *foreign key's* name rather than on the bare column,
            # which review caught: ``journal_id`` alone also appears in a primary
            # key violation's ``Key (task_id, journal_id)=(…) already exists``,
            # so a duplicate would have been reported to the caller as a missing
            # journal. Unreachable while the insert is ``ON CONFLICT DO NOTHING``
            # — which is exactly the kind of "safe today" the ``str(error)`` bug
            # in Phase 4 also was.
            if _INTERMEDIATE_JOURNAL_FK not in _driver_message(error):
                raise
            raise JournalNotFoundError(journal_id) from error

        # Only when a row was written. The insert is idempotent, so a repeat
        # changes nothing, and announcing it would put a second "linked this
        # journal" line in the user's history for a link that did not move.
        if created:
            await self.event_publisher.publish(
                TaskJournalLinked(
                    task_id=task_id,
                    user_id=user_id,
                    journal_id=journal_id,
                    origin=TaskJournalLinkOrigin.MANUAL,
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )
        return created

    @transactional
    async def detach_intermediate_journal(
        self,
        *,
        user_id: str,
        task_id: int,
        journal_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> bool:
        """Remove an intermediate-journal link from one of the user's tasks.

        **The journal is not required to still exist**, which is the deliberate
        asymmetry with :meth:`attach_intermediate_journal` and the same one
        :meth:`unlink_contact` carries. ``task_intermediate_journals.journal_id``
        cascades, so a deleted journal's links are already gone — the
        specification's *"deleting a journal that is only an intermediate link is
        permitted; the intermediate link is removed"* — and demanding the journal
        here would fail exactly the call a user reaches for while tidying up.

        **An anchor role cannot be removed this way**, and the refusal is
        explicit rather than a silent no-op. The repository would answer ``False``
        for an anchor with no link row, and a caller would read that as *"it was
        not attached"* rather than *"that link cannot be removed at all"*. The
        creating journal never changes; the due journal is replaced by
        retargeting.

        **The refusal is about the missing row, not about the anchor**, which is
        the correction a review of this phase forced. Refusing on the anchor
        alone made a legitimately reachable link permanently unremovable: attach
        a journal, then retarget the task *onto* it, and the row this surface
        wrote is still there while the journal has since become the due anchor —
        a shape :meth:`retarget_due_journal` deliberately leaves alone ("nothing
        is ever unlinked, including a link that has become redundant"). Refusing
        there would contradict the specification's *"intermediate links can be
        removed"* for a link the user created through this very method. So the
        delete runs first and the refusal applies only when it removed nothing:
        the anchor column is never touched either way, and the caller who
        genuinely meant *"stop this task being due here"* still gets told to
        retarget. The refusal path writes nothing — a ``DELETE`` matching no rows
        is not a write.

        **Idempotent for every journal except an anchor, and that exception is
        real rather than pedantic.** Detaching an ordinary journal twice is safe:
        the second call changes nothing and answers ``False``. But a journal that
        holds *both* roles answers ``True`` the first time and raises the second,
        because once the row is gone the method can no longer tell a retry from a
        caller asking to unlink the due journal — the two are the same request.
        So a client that retries after a timeout on **that one shape** can see a
        409 for a call that already succeeded.

        The alternative was to answer ``False`` there instead, and it was
        rejected: it would drop the *"attempting it is a clear error"* the phase's
        third acceptance criterion asks for, in order to serve a retry of a state
        reachable only by attaching a journal and then retargeting onto it.
        Distinguishing the two would need to record that a link once existed,
        which is a row this model does not have. Recorded here rather than
        smoothed over, because "idempotent" without the carve-out is what a
        caller would otherwise build a retry on.

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to unlink
            journal_id: The intermediate journal to stop referencing
            transaction: The request connection; the unit of work commits here
            source: Where the removal was asked for; defaults to ``SYSTEM``
            changed_by: The actor recorded on the event

        Returns:
            ``True`` when a link row was removed, ``False`` when there was none.

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's.
            TaskJournalIsAnchorError: When the journal is the task's creating or
                due journal **and** there is no intermediate link to remove.
            TaskListArchivedError: When the task is on an archived list.
        """
        task = await self._require_writable_task(task_id, user_id)

        removed = await self.task_repo.remove_intermediate_journal(
            task_id, journal_id, user_id
        )
        if not removed:
            _refuse_anchor_role(task, task_id, journal_id)
            return removed

        # Reached only when a row actually went, which is why it sits after the
        # refusal rather than beside the delete: a ``DELETE`` matching no rows is
        # not a write, whether the caller is retrying or naming an anchor.
        await self.event_publisher.publish(
            TaskJournalUnlinked(
                task_id=task_id,
                user_id=user_id,
                journal_id=journal_id,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return removed

    @transactional
    async def set_status(
        self,
        *,
        user_id: str,
        task_id: int,
        status: TaskStatus,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> Task:
        """Move one of the user's tasks to ``status``, changing nothing else.

        A thin delegation to :meth:`update_task`, deliberately. A status change
        arrives on its own from the MCP tool and beside a text edit from the
        endpoint; two implementations of the transition matrix would be two
        places for it to drift, and only one of them would be the one a given
        caller hit. Kept as a named method because "set the status" is a
        distinct intent an AI client needs a tool for, and because it is the
        signature Phase 6 shipped.

        See :meth:`update_task` for the rules, the row lock, the no-op and the
        ``TaskUpdated`` it publishes. Provenance is **forwarded** rather than
        defaulted here: this method publishes nothing itself, so dropping these
        two would still change the status and still publish an event, filing an
        AI agent's decision to cancel somebody's commitment under "system".

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to move
            status: The status to move it to
            transaction: The request connection; the unit of work commits here
            source: Where the change came from, recorded on the event
            changed_by: The actor, as the other domains write it

        Returns:
            The task in its new status — or unchanged, when it was already there.

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's. The two are indistinguishable by design.
            TaskStatusTransitionError: When the transition is refused — that is,
                when it would leave *cancelled*, which only retargeting does.
        """
        return await self.update_task(
            user_id=user_id,
            task_id=task_id,
            status=status,
            transaction=transaction,
            source=source,
            changed_by=changed_by,
        )

    @transactional
    async def delete_task(
        self,
        *,
        user_id: str,
        task_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> None:
        """Hard-delete one of the user's tasks.

        **The exception, not the ordinary action.** The specification keeps hard
        deletion "for genuine mistakes" and puts cancelling in its place for
        everything else, because a cancelled task stays part of the record of
        what the user committed to. Nothing here can enforce that preference —
        the surfaces carry it, in what they say — but it is why this method is
        deliberately plain and why neither surface leads with it.

        **The links go with the row and nothing else does.** Both link tables
        cascade from ``task_id``, so one statement removes the task and its
        intermediate-journal and contact links; the journals and contacts they
        pointed at are untouched. Walking those tables here instead could leave
        half of them behind, and would give this method the power to delete rows
        another domain owns.

        **No read precedes it.** Unlike :meth:`update_task` this decides nothing
        from what it read: the single owner-scoped statement either removes a row
        or does not, and reports which. A locking read would add a round trip and
        a second way for the two to disagree.

        **The archived-list refusal comes after the statement**, for the same
        reason: the ``DELETE`` answers which list the task was on, and a task on
        an archived list is refused *then*, by raising — which rolls the unit of
        work back and puts the row and its links back with it. That holds while
        the refusal propagates out of the outermost unit of work, as every
        caller of this method lets it; a caller that caught it inside a wider
        unit would commit the delete.

        The published event is a *marker*
        for the same reason — naming the task's text in it would have bought
        exactly the read this method exists without.

        **The event outlives the row.** Everything else about a task can be
        recovered by reading the task; once it is hard-deleted, this event is the
        only record that it existed, which is why it carries ``user_id``: a
        task-scoped history read has to answer "is this yours?" with no row left
        to ask.

        Args:
            user_id: The acting user; a task belonging to anyone else is not
                found, exactly as one that never existed is not
            task_id: The task to delete
            transaction: The request connection; the unit of work commits here
            source: Where the deletion came from, recorded on the event
            changed_by: The actor, as the other domains write it

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's. Reporting success for a task that was not there would
                tell a caller a commitment is gone when it may still be sitting
                on somebody's journal. A refused delete publishes nothing, so a
                repeated one cannot write a second deletion into history.
            TaskListArchivedError: When the task is on an archived list. The
                statement has run by then; raising is what undoes it.
        """
        task_list_id = await self.task_repo.delete(task_id, user_id)
        await self._hold_list_writable(task_list_id, task_id, user_id)

        await self.event_publisher.publish(
            TaskDeleted(
                task_id=task_id,
                user_id=user_id,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )

    @transactional
    async def retarget_due_journal(
        self,
        *,
        user_id: str,
        task_id: int,
        due_journal_id: int,
        transaction: AsyncConnection,
        acknowledge_reopen: bool = False,
        now: datetime.datetime | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> Task:
        """Move one of the user's tasks onto a new due journal.

        This is how a deadline is extended, and it is the **only** way a
        cancelled or a done task is reopened: retargeting always leaves the task
        *not done*. It is also the operation
        :class:`~core_shared.models.tasks.TaskStatusTransitionError` names when
        it refuses to let a status call leave *cancelled*.

        Two things happen together, in one unit of work:

        - the new journal becomes the due journal, and the task becomes *not
          done* whatever it was before;
        - the **previous due journal is retained as an intermediate journal**.
          This is the model's one automatic link, and it exists so the trail of a
          repeatedly-deferred task stays visible on the journals it passed
          through. De-duplication is
          :meth:`~app.core.tasks.models.repositories.TaskRepository.add_intermediate_journal`'s
          idempotence rather than a read-then-add, which would leave a window for
          a concurrent add between the question and the answer.

        **The rules are revalidated here, whatever the task's status.** A due
        journal is being *set*, so invariant 4 applies exactly as it does on
        creation: the journal must exist, be the acting user's, and be dated
        after today in their timezone. The journal the task is *leaving* is not
        judged — which is what makes a lapsed task resurrectable.

        **The creating journal cannot be reached from here.** There is no
        parameter for it, which is how the specification's "set once and never
        changes" is enforced: not by a check that could be forgotten, but by
        there being nothing to pass.

        Asking for the journal the task is already due in is a **no-op**: nothing
        is being set, so nothing is validated, nothing is written, ``updated_at``
        does not move, **no event is published** and no acknowledgement is
        needed. This mirrors :meth:`set_status`'s same-status no-op.

        **This publishes two events, one behind each write**, and it is the only
        task operation that publishes more than one:

        - a :class:`~app.core.tasks.models.events.TaskJournalLinked` for the
          retained journal — the same type a manual attach publishes, marked
          ``origin=RETARGET`` — and **only when a link row was actually
          written**, since the add is idempotent and a task returning to a
          journal it has already left finds it still attached;
        - a ``TaskDueJournalRetargeted`` after the save, carrying the due-journal
          pair and — for a task that was *done* or *cancelled* — the reopen, so
          the status change reaches the event stream rather than only the task
          row.

        The order is the write order, link before anchor, because each publish
        sits directly behind its own write rather than beside the other's.

        **The read takes a row lock**, for the reason Phase 6 found on
        :meth:`set_status` and this method inherits: it decides from the status
        it read — whether an acknowledgement was required — and writes that
        decision back. Without the lock, a retarget that began while the task was
        not done would go on to reopen a task somebody has since marked done,
        with no acknowledgement at all.

        **The journals are locked before the task row, which is what stops this
        deadlocking against a journal merge.**
        :meth:`~app.core.tasks.models.repositories.TaskAnchorRepository.repoint_journal_links`
        and its caller take the journals ``FOR UPDATE`` in ascending id order and
        write the task rows after; this method used to do the reverse, so
        retargeting a task while a merge absorbed the journal it was due in
        aborted one of the two. It now acquires the same rows in the same order,
        so the two queue.

        Getting there needs three reads where there were two, because the
        journal a task is *leaving* is not knowable until the task has been read:

        1. a **peek** — :meth:`~…TaskRepository.find_by_id`, no lock — which
           names the two journals and answers the same-journal no-op, the one
           path that reads no journal and takes no lock of any kind;
        2. the **ordered locking read** of both journals, through
           :meth:`_lock_retarget_journals`, taking exactly the ``FOR KEY SHARE``
           the writes below would take anyway — earlier, and low id to high;
        3. the **locking read of the task**, from which every rule below is
           decided. The peek decides nothing else: it is a snapshot from before
           the journal locks were waited on, so the status, the previous due
           journal and even the task's existence are all read again here.

        **Two residual windows, both stated rather than papered over.**

        *A third writer between the peek and the task lock.* If step 3 reports a
        different due journal — a merge re-pointed it onto a survivor, say — the
        journal now being left is not one of the two step 2 locked, so the link
        insert takes its own ``FOR KEY SHARE`` on it after the task lock. Locking
        it explicitly at that point was tried and removed: the foreign key
        acquires the very same lock at the very same place in the order, so the
        extra statements bought nothing. This needs a *third* concurrent
        operation rather than the pair the phase is about, and it is the same
        family as the creation deadlock below.

        *The same-journal no-op is decided from the peek*, because it must be:
        deciding it under the task lock means either taking that lock first — the
        inversion — or taking journal locks for a call that writes nothing, which
        the phase's own criterion forbids. A no-op writes nothing, so what it
        returns is a read, and every read is a snapshot: a merge committing a
        moment after a *locked* no-op returned would leave the caller holding the
        same stale journal id. The lock would narrow the window, not close it.

        The one ordering this does **not** close at all is against task
        *creation*, and no ordering can: an insert takes its foreign-key locks in
        declaration order rather than by id. See ``_lock_journals``.

        Args:
            user_id: The acting user; the task and the journal must be theirs
            task_id: The task to retarget
            due_journal_id: The future-dated journal it should now be due in
            transaction: The request connection; the unit of work commits here
            acknowledge_reopen: The caller's confirmation that reopening a *done*
                task is intended. Ignored for any other status, which needs no
                confirmation — reopening a cancelled task is the documented way
                out of cancelled.
            now: The instant "today" is derived from, defaulting to the real
                clock. **Never bind this from client input**, for the reason
                :meth:`create_task` gives: a request that could set it would make
                invariant 4 opt-out for any caller.
            source: Where the retarget came from, recorded on the event
            changed_by: The actor, as the other domains write it

        Returns:
            The task on its new due journal and not done — or unchanged, when it
            was already due in that journal.

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's. The two are indistinguishable by design.
            TaskAnchorJournalNotFoundError: When the new due journal does not
                exist or is not the acting user's.
            TaskDueJournalNotFutureError: When the new due journal's date is not
                after today in the user's timezone.
            TaskReopenNotAcknowledgedError: When the task is *done* and the
                caller has not acknowledged that retargeting reopens it.
            TaskListTaskClosedError: When the task is on a list and done or
                cancelled: a list task's date change never reopens it.
            TaskListTaskNotDueInJournalError: When the task is on a list and
                has no due journal to leave — undated, due on a date, or
                detached by a journal delete this retarget waited on.
            TaskListArchivedError: When the task is on an archived list —
                retargeting onto the journal it is already due in included.
        """
        # A read that takes no lock, and decides nothing. It is here to name the
        # journals — the one being left is not knowable any other way — and to
        # answer the same-journal no-op, which writes nothing and so needs
        # neither a journal nor a row lock.
        peeked = await self.task_repo.find_by_id(task_id, user_id)
        if peeked is None:
            raise TaskNotFoundError(task_id)
        # Refused here, before the no-op answer and the anchor narrowing below,
        # so an archived list's task is refused whatever it was asked to do. A
        # plain read, not the share lock: taking that lock here would put the
        # list ahead of the task row, against the order every other write keeps.
        # The lock — the guard an archive cannot slip past — follows the task's.
        await self._refuse_if_list_archived(peeked.task_list_id, task_id, user_id)
        if peeked.due_journal_id == due_journal_id:
            return peeked

        # Retargeting applies the journal-only rules. A list task that has a due
        # journal reaches it too; one that is undated or due on a date has no
        # journal to leave, and is refused before any lock is taken.
        if peeked.due_journal_id is None:
            raise TaskListTaskNotDueInJournalError(task_id)
        journals = await self._lock_retarget_journals(
            user_id, peeked.due_journal_id, due_journal_id
        )

        # Only now the task row, and every rule below is decided from *this*
        # read rather than from the peek above.
        task = await self.task_repo.find_by_id_for_update(task_id, user_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        # Journals, then the task, then its list: the list it is on *now*, held
        # until the unit of work ends.
        await self._hold_list_writable(task.task_list_id, task_id, user_id)

        # The journal actually being left, which is the one linked and announced
        # below. It comes from here rather than from the peek even though they
        # almost always agree — see the docstring's third read.
        previous_due_journal_id = task.due_journal_id
        # A journal delete that committed while this waited on the journal's
        # lock has detached the task: refused as the peek's check would have.
        if previous_due_journal_id is None:
            raise TaskListTaskNotDueInJournalError(task_id)
        if previous_due_journal_id == due_journal_id:
            return task
        # A retarget leaves the task not done, and a list task's date change
        # never changes its status, so a closed list task is refused rather
        # than reopened — whatever the acknowledgement says. Decided from the
        # locked read, and before the journal checks, since no journal would
        # make it succeed. Temporary: lifted when a list task's due journal can
        # be changed under list rules.
        if task.task_list_id is not None and task.status is not TaskStatus.NOT_DONE:
            raise TaskListTaskClosedError(task_id, task.status)

        if due_journal_id not in journals:
            raise TaskAnchorJournalNotFoundError("due", due_journal_id)
        await self._require_future_dated(
            user_id, due_journal_id, journals[due_journal_id], now
        )

        # Last, and deliberately: the acknowledgement is a confirmation rather
        # than a validation, so a caller who confirms should not then be told
        # that the journal they picked was in the past.
        if task.status == TaskStatus.DONE and not acknowledge_reopen:
            raise TaskReopenNotAcknowledgedError(task_id)

        # The answer is kept rather than discarded: the link is idempotent, and
        # whether a row was actually written is the difference between announcing
        # a new link and announcing one that was already there.
        auto_link_created = await self.task_repo.add_intermediate_journal(
            task_id, previous_due_journal_id, user_id
        )
        # Published here rather than beside the retarget event below, so each
        # event sits behind the write it announces. That is what makes the pair
        # reach a consumer link-first without depending on two adjacent publish
        # calls staying in order.
        #
        # ``source`` is the caller's, not ``SYSTEM``: a retarget is something the
        # **user** did, and this link is a consequence of their action rather
        # than a background job. Filing it under the system would have one action
        # produce two events disagreeing about who performed it. What is derived
        # is the link's *cause*, and ``origin`` carries that.
        if auto_link_created:
            await self.event_publisher.publish(
                TaskJournalLinked(
                    task_id=task_id,
                    user_id=user_id,
                    journal_id=previous_due_journal_id,
                    origin=TaskJournalLinkOrigin.RETARGET,
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )
        # Through ``_save`` rather than straight to the repository, for the race
        # its docstring describes. The window this path had is now shut — the
        # journal is held ``FOR KEY SHARE`` from the locking read above, and a
        # ``DELETE`` conflicts with that — but the mapping stays: it is the same
        # method the journal-only create writes through, where no journal lock
        # is taken, and a guard that only holds on one of its callers is worth
        # none of them relying on.
        saved = await self._save(
            replace(
                task,
                due_journal_id=due_journal_id,
                status=TaskStatus.NOT_DONE,
            )
        )

        # After the save, so the event announces a change that finished. Not for
        # atomicity — the outbox row rides this same connection, so a failing
        # ``_save`` would abort an event published before it just as surely — but
        # so the order in the code matches the order of the facts, as it does in
        # ``create_task`` and ``update_task``. The status the task *was* in comes
        # from the locking read, which is the only place it still exists once the
        # row is saved.
        await self.event_publisher.publish(
            TaskDueJournalRetargeted(
                task_id=task_id,
                user_id=user_id,
                previous_due_journal_id=previous_due_journal_id,
                due_journal_id=due_journal_id,
                previous_status=task.status,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return saved

    @transactional
    async def create_task_with_trail(
        self,
        *,
        user_id: str,
        creating_journal_id: int,
        due_journal_id: int,
        text: str,
        transaction: AsyncConnection,
        contact_ids: Sequence[int] | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> tuple[Task, list[int]]:
        """:meth:`create_task`, and the journals the new task has passed through.

        Always empty in practice — creation writes no intermediate link — but
        read rather than assumed, so the field has one definition across every
        surface instead of an assumption here and a query elsewhere.

        ``source`` and ``changed_by`` are forwarded rather than defaulted here:
        a task an assistant created has to read as one an assistant created, and
        a wrapper that swallowed them would silently relabel every MCP creation
        as ``SYSTEM`` in the user's own history.
        """
        created = await self.create_task(
            user_id=user_id,
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            text=text,
            transaction=transaction,
            contact_ids=contact_ids,
            source=source,
            changed_by=changed_by,
        )
        return created, await self._trail_within_unit_of_work(created, user_id)

    @transactional
    async def update_task_with_trail(
        self,
        *,
        user_id: str,
        task_id: int,
        transaction: AsyncConnection,
        text: str | None = None,
        status: TaskStatus | None = None,
        flagged: bool | None = None,
        icon: TaskIcon | None | Unset = UNSET,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> tuple[Task, list[int]]:
        """:meth:`update_task`, and the journals the task has passed through.

        ``source`` and ``changed_by`` are forwarded for the reason
        :meth:`create_task_with_trail` gives: a wrapper that swallowed them would
        file every change made in the browser or by an assistant under
        ``SYSTEM``, and nothing above the outbox row would show it.
        """
        updated = await self.update_task(
            user_id=user_id,
            task_id=task_id,
            transaction=transaction,
            text=text,
            status=status,
            flagged=flagged,
            icon=icon,
            source=source,
            changed_by=changed_by,
        )
        return updated, await self._trail_within_unit_of_work(updated, user_id)

    @transactional
    async def set_status_with_trail(
        self,
        *,
        user_id: str,
        task_id: int,
        status: TaskStatus,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> tuple[Task, list[int]]:
        """:meth:`set_status`, and the journals the task has passed through.

        Provenance crosses **two** hops from here — this wrapper to
        :meth:`set_status`, and that to :meth:`update_task`, which is what
        actually publishes. Either one dropping it is a silent success.
        """
        updated = await self.set_status(
            user_id=user_id,
            task_id=task_id,
            status=status,
            transaction=transaction,
            source=source,
            changed_by=changed_by,
        )
        return updated, await self._trail_within_unit_of_work(updated, user_id)

    @transactional
    async def retarget_due_journal_with_trail(
        self,
        *,
        user_id: str,
        task_id: int,
        due_journal_id: int,
        transaction: AsyncConnection,
        acknowledge_reopen: bool = False,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> tuple[Task, list[int]]:
        """:meth:`retarget_due_journal`, and the trail it just added to.

        This is the pairing the retarget surfaces actually want: the journal the
        task has just left is in the trail, and it is the same trail the task in
        the first half of the tuple was written against.

        ``source`` and ``changed_by`` are forwarded rather than defaulted, as on
        the other three wrappers. This is the write where losing them costs
        most: retargeting is the only way a *done* task is reopened, so an
        assistant undoing somebody's completion would otherwise be recorded as
        the system having done it.
        """
        retargeted = await self.retarget_due_journal(
            user_id=user_id,
            task_id=task_id,
            due_journal_id=due_journal_id,
            transaction=transaction,
            acknowledge_reopen=acknowledge_reopen,
            source=source,
            changed_by=changed_by,
        )
        return retargeted, await self._trail_within_unit_of_work(retargeted, user_id)

    async def _trail_within_unit_of_work(self, task: Task, user_id: str) -> list[int]:
        """The task's trail, read inside the caller's still-open unit of work.

        **Why these four wrappers exist at all.** Reading the trail *after* the
        write's unit of work has committed lets a concurrent write on the same
        task land in between, so the response could pair an older
        ``due_journal_id`` and status with a newer set of links — a task
        representation that never existed as one version. Raised by the pull
        request's automated review. ``@transactional`` is re-entrant, so a
        wrapper that calls the write and then this read has both inside **one**
        unit of work, and the pair is a single consistent snapshot.

        The response is still a snapshot of the moment it committed rather than
        of the moment it is read, which is true of every write on this surface
        and is not what was wrong: what was wrong was the two halves disagreeing
        with each other.

        A task that has vanished cannot be observed from in here — the write and
        this read share a transaction — so, unlike the surfaces' own fallback,
        there is nothing to catch.
        """
        assert task.id is not None, "a persisted task has an id"
        return await self.task_repo.list_intermediate_journal_ids(task.id, user_id)

    async def list_intermediate_journal_ids(
        self, *, user_id: str, task_id: int
    ) -> list[int]:
        """List the journals one of the user's tasks has passed through.

        These are the task's **intermediate** journals: the ones it was
        discussed, revisited, or previously due in. Retargeting adds the
        previous due journal automatically — the model's one automatic link —
        and everything else that lands here is put there deliberately.

        Neither anchor appears: the creating and due journals are columns on the
        task, and a caller already has both. A journal *can* be in this list and
        be an anchor at the same time, which is a legitimate shape rather than a
        bug — retargeting back onto a journal a task already passed through
        leaves it as both.

        **This is a read**, so it takes no ``transaction`` and is not
        ``@transactional``. There is nothing to commit, and a unit of work here
        would commit whatever the caller happened to have open. It exists so a
        controller or an MCP tool can answer with the trail without reaching
        past the service into a repository.

        **It is not free, and the cost is deliberate.** The adapter reaches the
        links through ``_require_task_owned``, which is a ``FOR KEY SHARE``
        read of the task row — so every caller pays an extra round trip and
        leaves the weakest of row locks held until the request's connection is
        released. That guard cannot simply be skipped: the link tables carry no
        ``user_id``, so it is the *only* thing making this read owner-scoped,
        and dropping it would let a caller list another user's trail. ``FOR KEY
        SHARE`` blocks nothing but a delete of that row, and the request is
        ending anyway, so the exposure is a request's tail rather than a
        contended lock.

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to read

        Returns:
            The linked journal ids, oldest link first. Empty for a task that has
            passed through nothing, which is a fact about that task rather than
            an absent answer.

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's. The two are indistinguishable by design, exactly as they
                are on every other task read.
        """
        return await self.task_repo.list_intermediate_journal_ids(task_id, user_id)

    @transactional
    async def reorder_task(
        self,
        *,
        user_id: str,
        task_id: int,
        after_task_id: int | None,
        transaction: AsyncConnection,
    ) -> list[tuple[Task, list[int]]]:
        """Move an open task on a list to the top, or just after another open task.

        The list page's single move: a drag names the task above the drop point,
        a keyboard step its neighbour. Reordering is **not an edit** — nothing is
        published, no history is recorded and no task's ``updated_at`` moves
        (spec: *Contacts, events and history*).

        **Locks: the list ``FOR SHARE``, then its open tasks.** The share lock is
        the one every task write takes after its own task row (see
        :meth:`_hold_list_writable`), so the two never wait on each other for
        the list; they meet only on task rows, and no cycle can form. Both tasks
        are read plainly first, and the repository re-checks them under lock.

        Returns:
            The list's open tasks in their new order, each with its trail.

        Raises:
            TaskValidationError: ``after_task_id`` is the task itself; the task
                is on no list or is closed; the anchor is closed or on another
                list (``field`` names which).
            TaskNotFoundError: The task or the anchor does not exist or is not
                the acting user's — indistinguishably.
            TaskListArchivedError: The list is archived, so read-only — a move
                that would change nothing included.
            TaskListChangedConcurrentlyError: A task closed or left the list
                between the checks and the locks; re-read and retry.
        """
        if after_task_id == task_id:
            raise TaskValidationError(
                "after_task_id", "a task cannot be placed after itself"
            )
        task = await self._require_task(task_id, user_id)
        if task.task_list_id is None:
            raise TaskValidationError(
                "task_id", "the task is on no list, so it has no order to change"
            )
        anchor = (
            None
            if after_task_id is None
            else await self._require_task(after_task_id, user_id)
        )
        await self._hold_list_writable(task.task_list_id, task_id, user_id)
        if task.status is not TaskStatus.NOT_DONE:
            raise TaskValidationError("task_id", "only open tasks can be reordered")
        if anchor is not None and (
            anchor.task_list_id != task.task_list_id
            or anchor.status is not TaskStatus.NOT_DONE
        ):
            raise TaskValidationError(
                "after_task_id", "must be an open task on the same list"
            )

        reordered = await self.task_repo.move_within_list(
            task_id, user_id, after_task_id=after_task_id
        )
        return await self._with_trails(reordered, user_id)

    @transactional
    async def reorder_list_tasks(
        self,
        *,
        user_id: str,
        task_list_id: int,
        task_ids: Sequence[int],
        transaction: AsyncConnection,
        after_task_id: int | None = None,
        before_task_id: int | None = None,
    ) -> list[tuple[Task, list[int]]]:
        """Arrange a block of a list's open tasks, in the order given, in one write.

        An agent's reorder (user decision, ITER21-001 Phase 25): the named tasks
        leave their places, every other open task keeps its relative order, and
        the block lands at the top — or directly after ``after_task_id``, or
        directly before ``before_task_id``. Naming every open task sets the whole
        order. A task created on the list since the caller read it is not named,
        so it simply stays at the bottom.

        Not an edit, as :meth:`reorder_task` is not: nothing is published. The
        list is held ``FOR SHARE`` before anything else and no task row is
        locked before it, for the same reason.

        Returns:
            The list's open tasks in their new order, each with its trail.

        Raises:
            TaskValidationError: ``task_ids`` is empty or repeats a task, both
                anchors are given, an anchor is in the block; a named task is not
                an open task on this list (closed, on another list, or not the
                user's — one answer, so nothing about another user's tasks
                leaks); an anchor is not one. ``field`` names the argument.
            TaskListNotFoundError: The list does not exist or is not the user's.
            TaskListArchivedError: The list is archived — a no-op included.
            TaskListChangedConcurrentlyError: A named task closed or left the
                list between the check and the locks; re-read and retry.
        """
        anchors = {"after_task_id": after_task_id, "before_task_id": before_task_id}
        _check_arrangement(task_ids, anchors)

        task_list = await self.task_list_repo.find_by_id_for_share(
            task_list_id, user_id
        )
        if task_list is None:
            raise TaskListNotFoundError(task_list_id)
        task_list.ensure_writable()

        open_ids = {
            each.id
            for each in await self.task_repo.find_open_tasks_on_list(
                task_list_id, user_id
            )
        }
        not_open = [named for named in task_ids if named not in open_ids]
        if not_open:
            raise TaskValidationError(
                "task_ids",
                "not open tasks on this list: "
                + ", ".join(str(named) for named in not_open),
            )
        for field, anchor in anchors.items():
            if anchor is not None and anchor not in open_ids:
                raise TaskValidationError(field, "must be an open task on this list")

        arranged = await self.task_repo.arrange_open_tasks(
            task_list_id,
            user_id,
            task_ids=list(task_ids),
            after_task_id=after_task_id,
            before_task_id=before_task_id,
        )
        return await self._with_trails(arranged, user_id)

    async def _with_trails(
        self, tasks: list[Task], user_id: str
    ) -> list[tuple[Task, list[int]]]:
        """Pair each task with its trail, read for all of them at once."""
        ids = [each.id for each in tasks if each.id is not None]
        trails = await self.task_repo.list_intermediate_journal_ids_for_tasks(
            ids, user_id
        )
        return [(each, trails.get(each.id or 0, [])) for each in tasks]

    async def _save(self, task: Task) -> Task:
        """Write the task, keeping the promised error if an anchor just vanished.

        Used by every writer of an anchor column — the inserts on creation, from
        journals or on a list, and the update on a retarget. The anchor ids are
        read off the task being written, so the error names exactly the journal
        that write pointed at. The journal-only create's anchor checks are a
        plain read, so a journal deleted between that read and this write would
        fail the foreign key and surface a raw ``IntegrityError`` — a 500 in
        place of the 404 the caller was promised. The window is narrow and the database is never wrong here
        (the anchors are ``ON DELETE RESTRICT``, so nothing is corrupted); what
        is at stake is only which error the caller sees, so it is mapped back
        rather than locked out.

        Locking the journal rows for the duration closes the window, and the
        **retarget** path now does hold them — not for this, but because the lock
        order against journal merge required it, and ``FOR KEY SHARE`` conflicts
        with the ``DELETE`` too. So does the **list** create with a due journal,
        for the lock order against a retarget and a journal delete (see
        :meth:`create_list_task`). The **journal-only creation** path still does
        not: it would
        need the same owner-scoped locking read on ``JournalRepository`` to
        change an outcome that is identical either way — the journal is gone, and
        the task cannot anchor to it — so the mapping below stays, and is what
        both paths rely on. A violation naming anything else is re-raised
        untouched.
        """
        try:
            return await self.task_repo.save(task)
        except IntegrityError as error:
            anchor = _violated_anchor(error)
            if anchor is None:
                raise
            journal_id = (
                task.creating_journal_id
                if anchor == "creating"
                else task.due_journal_id
            )
            # A foreign key is only ever violated by an id that was written, so
            # the column the database named is set on this task.
            assert journal_id is not None, f"{anchor} anchor violated but unset"
            raise TaskAnchorJournalNotFoundError(anchor, journal_id) from error

    async def _require_task(self, task_id: int, user_id: str) -> Task:
        """Read one of the user's tasks, or raise the promised 404.

        The plain read, not the locking one — see
        :meth:`attach_intermediate_journal` for why the link methods do not need
        a lock where the status and retarget methods do.
        """
        task = await self.task_repo.find_by_id(task_id, user_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def _require_writable_task(self, task_id: int, user_id: str) -> Task:
        """:meth:`_require_task`, then :meth:`_hold_list_writable` on its list."""
        task = await self._require_task(task_id, user_id)
        await self._hold_list_writable(task.task_list_id, task_id, user_id)
        return task

    async def _hold_list_writable(
        self, task_list_id: int | None, task_id: int, user_id: str
    ) -> None:
        """Refuse a write to a task on an archived list; hold the list otherwise.

        The one place a task write consults the list's read-only rule, and the
        rule itself is the entity's — ``TaskList.ensure_writable``, which the
        list's own writes call — rather than a second reading of ``archived_at``.

        A journal-only task (``task_list_id is None``) has no list to ask, so
        nothing is read for it. Otherwise the list is read ``FOR SHARE`` and the
        lock is kept until the unit of work ends: an archive takes
        ``FOR NO KEY UPDATE``, so it waits for this write to commit, and a write
        that started while an archive was in flight waits for it and then reads
        the archived row. Two task writes on the same list share the lock.

        **Lock order: the task, then its list.** Callers that lock the task row
        do so before calling this. The reorders (:meth:`reorder_task`,
        :meth:`reorder_list_tasks`) lock the other way round — the list, then
        its open tasks — and that is safe only because their list lock is this
        same ``FOR SHARE``, which never waits on this one. A writer that locks a
        list *exclusively* and then its tasks — deleting a list — would
        deadlock against this, and must lock the tasks first.

        **One write does not use this: creating a task on a list.** A create
        has no task row to lock first, and its insert needs ``FOR NO KEY
        UPDATE`` on the list to compute the bottom; taking share here first
        would be a lock upgrade two concurrent creates deadlock on. So
        :meth:`create_list_task` reads the list with the update lock (after any
        due journal's key-share lock, the one lock it takes first) and calls
        ``ensure_writable`` itself.

        Raises:
            TaskListArchivedError: The list is archived, and so is the task.
            TaskNotFoundError: The list cannot be read. Unreachable while the
                list's foreign key restricts deletes; if it ever happens the
                task is answered as gone rather than as writable.
        """
        if task_list_id is None:
            return
        task_list = await self.task_list_repo.find_by_id_for_share(
            task_list_id, user_id
        )
        if task_list is None:
            raise TaskNotFoundError(task_id)
        task_list.ensure_writable()

    async def _refuse_if_list_archived(
        self, task_list_id: int | None, task_id: int, user_id: str
    ) -> None:
        """:meth:`_hold_list_writable`'s rule on a plain read, holding nothing.

        For a refusal that has to come before the task row is locked — the
        retarget's, which answers its no-op before taking any lock — so that a
        refused retarget holds nothing at all. It decides only whether to refuse
        early; a write that goes on must still take :meth:`_hold_list_writable`
        after its task lock.
        """
        if task_list_id is None:
            return
        task_list = await self.task_list_repo.find_by_id(task_list_id, user_id)
        if task_list is None:
            raise TaskNotFoundError(task_id)
        task_list.ensure_writable()

    async def _require_owned_journal(self, user_id: str, journal_id: int) -> Journal:
        """Load a journal the acting user owns, on the anchors' terms.

        Goes through :meth:`_journals_by_id`, so the property that ownership is
        enforced *by the query* — and therefore that another user's journal is
        indistinguishable from an absent one — has one place to hold rather than
        three. The error is the journal domain's, not
        ``TaskAnchorJournalNotFoundError``: an intermediate journal is not an
        anchor, and that error's message ("a task must be anchored to journals
        that exist and belong to you") would be describing a rule this call is
        not about.
        """
        found = await self._journals_by_id(user_id, [journal_id])
        if journal_id not in found:
            raise JournalNotFoundError(journal_id)
        return found[journal_id]

    async def _link_contacts(
        self,
        task_id: int,
        contact_ids: Sequence[int],
        user_id: str,
        transaction: AsyncConnection,
    ) -> list[int]:
        """Link every contact in one write, keeping the promised error.

        The same race as :meth:`_save`, one row over: the contacts were proved
        to exist a few statements ago, and a delete since then must still read
        as ``ContactNotFoundError`` rather than as a raw integrity error.

        With one insert per contact the vanished id was whichever one was being
        written. A batched insert has to work it out, and **the id is found by
        re-reading rather than by parsing the error.** PostgreSQL does put it in
        the violation's ``DETAIL`` (``Key (contact_id)=(999) is not present…``),
        but that is prose: it is localised by ``lc_messages``, it is a driver's
        choice whether to surface it separately from the primary message, and
        this module already learned in Phase 4 that matching against the wrong
        rendering of an error passes every test built on a hand-written one. A
        second ``SELECT`` on the ids the caller named answers the same question
        from data.

        **That re-read is what the savepoint is for.** PostgreSQL puts the whole
        transaction into a failed state on a constraint violation, so the lookup
        would itself raise ``InFailedSQLTransactionError``; wrapping the insert
        in a ``SAVEPOINT`` rolls back only the failed statement and leaves the
        connection usable. The integration test was mutation-checked against
        exactly that.

        If the re-read finds every contact still present, the violation is about
        something else and is re-raised untouched: naming an arbitrary id would
        send the caller looking for a contact that exists.
        """
        if not contact_ids:
            # Nothing to link, so the repository is not called at all — not even
            # for its ownership guard, which would otherwise cost a locking read
            # on every create that names no contacts. The guard still runs
            # whenever the method *is* called, empty list included; this is a
            # caller declining to make the call.
            return []

        wanted = list(contact_ids)
        try:
            async with savepoint(transaction):
                return await self.task_repo.add_contacts(task_id, wanted, user_id)
        except IntegrityError as error:
            if "contact_id" not in _driver_message(error):
                raise
            known = await self.contact_repo.find_names_by_ids(wanted, user_id=user_id)
            missing = [cid for cid in wanted if cid not in known]
            if not missing:
                raise
            raise ContactNotFoundError(missing[0]) from error

    async def _journals_by_id(
        self, user_id: str, journal_ids: Sequence[int]
    ) -> dict[int, Journal]:
        """The user's journals among ``journal_ids``, keyed by id.

        Ownership is enforced *by the query*, not by comparing a ``user_id``
        afterwards: a journal belonging to somebody else simply is not in the
        result, so it is indistinguishable from one that never existed and any
        error built on this can leak nothing. Both anchor resolutions go through
        here so that property has one place to hold.
        """
        return {
            journal.id: journal
            for journal in await self.journal_repo.find_by_ids_for_user(
                user_id, list(journal_ids)
            )
            if journal.id is not None
        }

    async def _resolve_anchors(
        self, user_id: str, creating_journal_id: int, due_journal_id: int
    ) -> Journal:
        """Load both anchors in one owner-scoped read and return the due journal.

        One call covers both anchors — and the same-journal case collapses to a
        single id — so an extra journal never costs an extra round trip.
        """
        wanted = _ordered_unique([creating_journal_id, due_journal_id])
        found = await self._journals_by_id(user_id, wanted)

        anchors: tuple[tuple[TaskJournalAnchor, int], ...] = (
            ("creating", creating_journal_id),
            ("due", due_journal_id),
        )
        for anchor, journal_id in anchors:
            if journal_id not in found:
                raise TaskAnchorJournalNotFoundError(anchor, journal_id)

        return found[due_journal_id]

    async def _lock_due_journal(
        self, user_id: str, due_journal_id: int
    ) -> Journal | None:
        """Hold the user's journal ``FOR KEY SHARE``, or ``None`` if it is not theirs.

        The lock a task's foreign key on it takes, taken before any other lock
        the write needs — the order :meth:`_lock_retarget_journals` and a journal
        delete's detach take the journal in. Owner-scoped, so a journal that
        belongs to somebody else is absent and was never locked. The caller
        decides when a missing one is refused, so the refusal order does not
        have to follow the lock order.
        """
        found = await self.journal_repo.find_and_lock_by_ids_for_user(
            user_id, [due_journal_id]
        )
        return next(
            (journal for journal in found if journal.id == due_journal_id), None
        )

    async def _lock_retarget_journals(
        self, user_id: str, previous_due_journal_id: int, due_journal_id: int
    ) -> dict[int, Journal]:
        """Hold both of a retarget's journals, in the order a merge holds them.

        The two journals a retarget writes against are the one it is leaving —
        the intermediate link's foreign key — and the one it is moving to — the
        anchor update's. Both foreign keys take ``FOR KEY SHARE`` when their
        statement runs; this takes the identical locks first, and in ascending id
        order, which is what stops the retarget and a journal merge acquiring the
        same pair of rows in opposite orders. See
        :meth:`~app.core.journal.models.repositories.JournalRepository.find_and_lock_by_ids_for_user`.

        The **creating** anchor is not among them and is still not re-read: it
        cannot change, its foreign key is not re-checked by an update that leaves
        the column alone, and reading it would invite a rule about it that the
        specification does not have.

        Ownership stays enforced by the query, so a journal belonging to somebody
        else is absent from the result and was never locked. The caller decides
        what a missing **due** journal means; a missing *previous* one needs no
        answer here, because it can only have been deleted by the merge this
        ordering exists to queue behind — and the locking read of the task that
        follows is what notices.
        """
        return {
            journal.id: journal
            for journal in await self.journal_repo.find_and_lock_by_ids_for_user(
                user_id, sorted({previous_due_journal_id, due_journal_id})
            )
            if journal.id is not None
        }

    async def _require_future_dated(
        self,
        user_id: str,
        due_journal_id: int,
        due_journal: Journal,
        now: datetime.datetime | None,
    ) -> None:
        """Enforce invariant 4 against the user's local day.

        The timezone is fetched once and the pure predicate applied to it, rather
        than calling the resolver's per-journal wrapper — the same shape the
        batch callers to come need, and the reason the resolver splits that way.

        The id is passed in rather than read off the journal: the caller looked
        it up by that id, so it is known to be an ``int`` there and would need a
        redundant narrowing check here.

        **The clock is read once.** Both the predicate and the error's "today"
        derive from one instant, because a bare ``now=None`` would let each read
        the clock separately — and a create landing on local midnight would then
        be refused against one day and told about another. Resolving the instant
        here rather than comparing dates inline keeps the rule itself in
        :func:`~app.core.journal.services.journal_date_resolver.is_future_dated`,
        which is the module that owns what "future-dated" means.

        **The journal's date can still move under this check, and that is not a
        hole.** A retarget now holds ``FOR KEY SHARE`` on the journal by the time
        it gets here, but that mode deliberately does not block an ordinary
        ``update_journal``: it can move the journal's date into the past between
        this check and the caller's write, so a task can be committed against a
        due journal that is *already* past. Raised in review on
        ITER18-001 Phase 7 as an invariant-4 violation; it is not one. The
        specification makes invariant 4 a rule about the moment a due journal is
        **set** — "checked when a due journal is *set*, not continuously. A task
        whose due journal has since moved into the past is **lapsed, not
        invalid**" — and a lapsed task is a first-class state the product is
        built around: it leaves the dashboard silently and the user resurrects it
        by retargeting. The check passed at the moment of setting; a journal
        edited a millisecond later and one edited a week later produce the
        identical, supported state, so a lock would narrow a window onto an
        outcome that is legitimate either side of it.

        A stronger lock would also cost something real. Blocking a journal edit
        for the length of a retarget's unit of work is a price this rule has no
        reason to charge, and ``FOR KEY SHARE`` was chosen on the retarget path
        precisely so it does not — see
        :meth:`~app.core.journal.models.repositories.JournalRepository.find_and_lock_by_ids_for_user`.
        On the journal-only creation path no journal lock is taken at all; the
        list create holds its due journal ``FOR KEY SHARE``, for its lock order
        rather than for this check, which that lock does not tighten either.
        """
        tz = await self.date_resolver.timezone_for(user_id)
        moment = now if now is not None else datetime.datetime.now(tz)
        if is_future_dated(due_journal, tz, moment):
            return

        raise TaskDueJournalNotFutureError(
            due_journal_id, journal_date(due_journal, tz), today_in(tz, moment)
        )

    async def _require_due_date_allowed(
        self,
        user_id: str,
        due_date: datetime.date,
        now: datetime.datetime | None,
    ) -> None:
        """Refuse a due date before today, judged in the user's local day.

        The clock is read once, as in :meth:`_require_future_dated`, so the
        rule and the error's "today" cannot straddle a local midnight.
        """
        tz = await self.date_resolver.timezone_for(user_id)
        moment = now if now is not None else datetime.datetime.now(tz)
        ensure_due_date_allowed(due_date, today_in(tz, moment))

    async def _resolve_contacts(
        self, contact_ids: Sequence[int] | None, *, user_id: str
    ) -> list[int]:
        """Return the contacts to link, having proved every one is ``user_id``'s.

        A contact named in a create must be real: dropping an unknown id would
        silently give the user a task with fewer people on it than they asked
        for. The lookup is owner-scoped, so another user's contact is not found,
        exactly as a missing one is.
        """
        if not contact_ids:
            return []

        wanted = _ordered_unique(contact_ids)
        known = await self.contact_repo.find_names_by_ids(wanted, user_id=user_id)
        for contact_id in wanted:
            if contact_id not in known:
                raise ContactNotFoundError(contact_id)
        return wanted

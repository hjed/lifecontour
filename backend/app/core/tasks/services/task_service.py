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
    TaskNotFoundError,
    TaskReopenNotAcknowledgedError,
    TaskStatus,
    TaskStatusTransitionError,
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
)
from app.infrastructure.unit_of_work import savepoint, transactional

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from core_shared.models.journals import Journal
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.core.contacts.models.repositories import ContactRepository
    from app.core.journal.models.repositories import JournalRepository
    from app.core.journal.services.journal_date_resolver import JournalDateResolver
    from app.core.tasks.models.repositories import TaskRepository
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
    roles: tuple[tuple[TaskJournalAnchor, int], ...] = (
        ("creating", task.creating_journal_id),
        ("due", task.due_journal_id),
    )
    for anchor, anchor_journal_id in roles:
        if anchor_journal_id == journal_id:
            raise TaskJournalIsAnchorError(task_id, journal_id, anchor)


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
    """

    def __init__(
        self,
        task_repo: TaskRepository,
        journal_repo: JournalRepository,
        contact_repo: ContactRepository,
        date_resolver: JournalDateResolver,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.task_repo = task_repo
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
        contacts = await self._resolve_contacts(contact_ids)

        created = await self._save(task, creating_journal_id, due_journal_id)
        assert created.id is not None, "Task ID must be set after save"
        await self._link_contacts(created.id, contacts, user_id, transaction)

        # Last, and deliberately: the event announces a create that finished,
        # links included, following the journal tag service's ordering. It reads
        # the *persisted* task because the id it carries exists only after the
        # save, and that id is what the history projection files rows under.
        await self.event_publisher.publish(
            TaskCreated(
                task_id=created.id,
                user_id=created.user_id,
                text=created.text,
                status=created.status,
                creating_journal_id=created.creating_journal_id,
                due_journal_id=created.due_journal_id,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return created

    @transactional
    async def update_task(
        self,
        *,
        user_id: str,
        task_id: int,
        transaction: AsyncConnection,
        text: str | None = None,
        status: TaskStatus | None = None,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> Task:
        """Change one of the user's tasks: its text, its status, or both.

        **One method owns both fields** because a ``PATCH`` may carry both, and
        JSON:API says a request is one change. Applying them as two calls would
        be two units of work and two read-decide-write sequences, so a client
        that reworded and completed a task in one request could have half of it
        applied. Here it is one read, one decision and one write.

        **No journal is involved**, on either half. The due journal is not read,
        which is what keeps a *lapsed* task both completable and editable: the
        future-dated rule is a write-time rule about *setting* a due journal, and
        re-applying it here would make exactly the tasks a user most needs to
        tidy up the ones they cannot.

        A call that changes nothing is a no-op: nothing is written, so
        ``updated_at`` does not move, **no event is published** and no change is
        recorded that did not happen. That covers the status a task already has,
        the text it already has, and — for a caller that is not a JSON:API
        surface — naming neither.

        **One write publishes one** ``TaskUpdated``, carrying ``changed_fields``
        for whichever of the two moved. Not one event per field: a ``PATCH`` may
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
        """
        task = await self.task_repo.find_by_id_for_update(task_id, user_id)
        if task is None:
            raise TaskNotFoundError(task_id)

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

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to link
            contact_id: The contact to reference
            transaction: The request connection; the unit of work commits here

        Returns:
            ``True`` when a link row was created, ``False`` when it was already
            there.

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's. The two are indistinguishable by design.
            ContactNotFoundError: When the contact does not exist. Existence is
                the whole check — ``contacts`` carries no owner column in this
                system, so there is no ownership to enforce (recorded as a
                divergence in the iteration document).
        """
        contacts = await self._resolve_contacts([contact_id])
        created = await self._link_contacts(task_id, contacts, user_id, transaction)
        return contact_id in created

    @transactional
    async def unlink_contact(
        self,
        *,
        user_id: str,
        task_id: int,
        contact_id: int,
        transaction: AsyncConnection,
    ) -> bool:
        """Remove a contact link from one of the user's tasks.

        **The contact is not required to still exist**, which is the deliberate
        asymmetry with :meth:`link_contact`. ``task_contacts.contact_id``
        cascades, so a deleted contact's links are already gone; demanding the
        contact here would make the one call a user might reach for while
        tidying up fail on exactly the contact they had just removed.

        Idempotent for the same reason ``DELETE`` is: unlinking a contact that
        is not linked changes nothing and says so.

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to unlink
            contact_id: The contact to stop referencing
            transaction: The request connection; the unit of work commits here

        Returns:
            ``True`` when a link row was removed, ``False`` when there was none.

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's.
        """
        return await self.task_repo.remove_contact(task_id, contact_id, user_id)

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
        is legitimate either side of it, and it would deepen the lock-order
        inversion against journal merge that ITER18-002 Phase 6 exists to remove.

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
        """
        task = await self._require_task(task_id, user_id)
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
        """
        task = await self._require_task(task_id, user_id)

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
        a second way for the two to disagree. The published event is a *marker*
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
        """
        await self.task_repo.delete(task_id, user_id)

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

        **Known: this ordering deadlocks against a concurrent journal merge.**
        The task row is locked first and the journals only afterwards, through
        the link insert's and the anchor update's foreign keys;
        :meth:`~app.core.tasks.models.repositories.TaskAnchorRepository.repoint_journal_links`
        takes the journals first and the task rows after. Retargeting a task
        while a merge absorbs the journal it is due in therefore aborts one of
        the two. Neither half-applies, so nothing is corrupted — but one caller
        sees a database error. Closing it means taking the journal locks first,
        in the merge's ascending-id order, which needs a locking read on the
        journal domain's port and a way to know the *previous* due journal before
        the task has been read. That is **ITER18-002 Phase 6**, whose subject is
        this pair; it is deliberately not done here, where the merge contract is
        not in scope.

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
        """
        task = await self.task_repo.find_by_id_for_update(task_id, user_id)
        if task is None:
            raise TaskNotFoundError(task_id)

        previous_due_journal_id = task.due_journal_id
        if previous_due_journal_id == due_journal_id:
            return task

        due_journal = await self._resolve_due_journal(user_id, due_journal_id)
        await self._require_future_dated(user_id, due_journal_id, due_journal, now)

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
        # its docstring describes. The window is wider here than on creation: the
        # journal-delete guard refuses to delete a journal that *already* anchors
        # a task, and the new due journal does not anchor this one until the
        # statement below runs — so a delete landing between the read above and
        # this write is permitted, and would otherwise surface as a raw
        # ``IntegrityError`` in place of the 404 this method promises.
        saved = await self._save(
            replace(
                task,
                due_journal_id=due_journal_id,
                status=TaskStatus.NOT_DONE,
            ),
            task.creating_journal_id,
            due_journal_id,
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

    async def _save(
        self, task: Task, creating_journal_id: int, due_journal_id: int
    ) -> Task:
        """Write the task, keeping the promised error if an anchor just vanished.

        Used by both writers of an anchor column — the insert on creation and the
        update on a retarget. The anchor checks are a plain read, so a journal
        deleted between that read and this write would fail the foreign key and
        surface a raw ``IntegrityError`` — a 500 in place of the 404 the caller
        was promised. The window is narrow and the database is never wrong here
        (the anchors are ``ON DELETE RESTRICT``, so nothing is corrupted); what
        is at stake is only which error the caller sees, so it is mapped back
        rather than locked out.

        Locking the journal rows for the duration would close the window, but it
        needs an owner-scoped *locking* read on ``JournalRepository`` — another
        domain's port — to change an outcome that is identical either way: the
        journal is gone, and the task cannot anchor to it. A violation naming
        anything else is re-raised untouched.
        """
        try:
            return await self.task_repo.save(task)
        except IntegrityError as error:
            anchor = _violated_anchor(error)
            if anchor is None:
                raise
            journal_id = creating_journal_id if anchor == "creating" else due_journal_id
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
            known = await self.contact_repo.find_names_by_ids(wanted)
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

    async def _resolve_due_journal(self, user_id: str, due_journal_id: int) -> Journal:
        """Load the due anchor alone, for a retarget, on the same terms.

        The creating anchor is not re-read: it cannot change, and reading it
        would invite a rule about it that the specification does not have.
        """
        found = await self._journals_by_id(user_id, [due_journal_id])
        if due_journal_id not in found:
            raise TaskAnchorJournalNotFoundError("due", due_journal_id)
        return found[due_journal_id]

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

        **The journal is read without a lock, and that is not a hole.** A
        concurrent ``update_journal`` can move the journal's date into the past
        between this check and the caller's write, so a task can be committed
        against a due journal that is *already* past. Raised in review on
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

        Two further reasons not to take one. It would have to be a locking read
        on the **journal** domain's port, which this service reaches for only
        deliberately (see :meth:`_save`). And it would be taken *after* the task
        row lock on the retarget path, deepening the lock-order inversion against
        journal merge that ITER18-002 Phase 6 exists to remove — buying nothing
        observable at the cost of more deadlocks.
        """
        tz = await self.date_resolver.timezone_for(user_id)
        moment = now if now is not None else datetime.datetime.now(tz)
        if is_future_dated(due_journal, tz, moment):
            return

        raise TaskDueJournalNotFutureError(
            due_journal_id, journal_date(due_journal, tz), today_in(tz, moment)
        )

    async def _resolve_contacts(self, contact_ids: Sequence[int] | None) -> list[int]:
        """Return the contacts to link, having proved every one of them exists.

        A contact named in a create must be real: dropping an unknown id would
        silently give the user a task with fewer people on it than they asked
        for. Existence is the whole check — ``contacts`` carries no owner column
        in this system, so there is no ownership to enforce here (recorded as a
        divergence in the iteration document).
        """
        if not contact_ids:
            return []

        wanted = _ordered_unique(contact_ids)
        known = await self.contact_repo.find_names_by_ids(wanted)
        for contact_id in wanted:
            if contact_id not in known:
                raise ContactNotFoundError(contact_id)
        return wanted

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
moment a due journal is set and at no other time. Nothing re-validates it on
read, which is exactly what makes a *lapsed* task — one whose due journal has
since passed — reachable rather than unloadable.
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from typing import TYPE_CHECKING

from core_shared.models.tasks import (
    Task,
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskJournalAnchor,
    TaskNotFoundError,
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
from app.infrastructure.unit_of_work import transactional

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from core_shared.models.journals import Journal
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.core.contacts.models.repositories import ContactRepository
    from app.core.journal.models.repositories import JournalRepository
    from app.core.journal.services.journal_date_resolver import JournalDateResolver
    from app.core.tasks.models.repositories import TaskRepository


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


class TaskService:
    """Creates tasks, edits them, moves them through their lifecycle, deletes them.

    Every operation enforces the specification's rules here rather than at a
    surface: the core invariants on creation, the transition matrix on a status
    change, the entity's text rule on an edit, and owner scoping throughout.
    REST and MCP are thin callers of each.
    """

    def __init__(
        self,
        task_repo: TaskRepository,
        journal_repo: JournalRepository,
        contact_repo: ContactRepository,
        date_resolver: JournalDateResolver,
    ) -> None:
        self.task_repo = task_repo
        self.journal_repo = journal_repo
        self.contact_repo = contact_repo
        self.date_resolver = date_resolver

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
    ) -> Task:
        """Create a task anchored to two of the user's journals.

        The creating journal is the journal the task is created *from* — the
        caller supplies it from context, never as a user's separate choice — and
        the due journal is the future moment the commitment matters. The two may
        be the same journal.

        Everything is validated before anything is written, so a rejected create
        leaves no partial task behind.

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
        for contact_id in contacts:
            await self._link_contact(created.id, contact_id, user_id)
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
        ``updated_at`` does not move and no change is recorded that did not
        happen. That covers the status a task already has, the text it already
        has, and — for a caller that is not a JSON:API surface — naming neither.

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to change
            transaction: The request connection; the unit of work commits here
            text: The new text, or ``None`` to leave it alone. Validated by the
                entity rather than here, so there is one definition of an
                acceptable task rather than two that can drift apart.
            status: The status to move to, or ``None`` to leave it alone

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
        # The entity's own rule first, as on creation: a blank text is wrong
        # outright, while a refused transition depends on state the caller may
        # not have known. ``replace`` re-runs ``__post_init__``, so the check is
        # the entity's rather than a second copy of it living here.
        if text is not None and text != task.text:
            updated = replace(updated, text=text)

        if status is not None and status != task.status:
            if not is_status_transition_allowed(task.status, status):
                raise TaskStatusTransitionError(task.status, status)
            updated = replace(updated, status=status)

        if updated is task:
            return task
        return await self.task_repo.save(updated)

    @transactional
    async def set_status(
        self,
        *,
        user_id: str,
        task_id: int,
        status: TaskStatus,
        transaction: AsyncConnection,
    ) -> Task:
        """Move one of the user's tasks to ``status``, changing nothing else.

        A thin delegation to :meth:`update_task`, deliberately. A status change
        arrives on its own from the MCP tool and beside a text edit from the
        endpoint; two implementations of the transition matrix would be two
        places for it to drift, and only one of them would be the one a given
        caller hit. Kept as a named method because "set the status" is a
        distinct intent an AI client needs a tool for, and because it is the
        signature Phase 6 shipped.

        See :meth:`update_task` for the rules, the row lock and the no-op.

        Args:
            user_id: The acting user; the task must be theirs
            task_id: The task to move
            status: The status to move it to
            transaction: The request connection; the unit of work commits here

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
        )

    @transactional
    async def delete_task(
        self, *, user_id: str, task_id: int, transaction: AsyncConnection
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

        Args:
            user_id: The acting user; a task belonging to anyone else is not
                found, exactly as one that never existed is not
            task_id: The task to delete
            transaction: The request connection; the unit of work commits here

        Raises:
            TaskNotFoundError: When the task does not exist or is not the acting
                user's. Reporting success for a task that was not there would
                tell a caller a commitment is gone when it may still be sitting
                on somebody's journal.
        """
        await self.task_repo.delete(task_id, user_id)

    async def _save(
        self, task: Task, creating_journal_id: int, due_journal_id: int
    ) -> Task:
        """Insert the task, keeping the promised error if an anchor just vanished.

        The anchor checks are a plain read, so a journal deleted between that read
        and this insert would fail the foreign key and surface a raw
        ``IntegrityError`` — a 500 in place of the 404 the caller was promised.
        The window is narrow and the database is never wrong here (the anchors are
        ``ON DELETE RESTRICT``, so nothing is corrupted); what is at stake is only
        which error the caller sees, so it is mapped back rather than locked out.

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

    async def _link_contact(self, task_id: int, contact_id: int, user_id: str) -> None:
        """Link one contact, keeping the promised error if it just vanished.

        The same race as :meth:`_save`, one row over: the contact was proved to
        exist a few statements ago, and a delete since then must still read as
        ``ContactNotFoundError`` rather than as a raw integrity error.
        """
        try:
            await self.task_repo.add_contact(task_id, contact_id, user_id)
        except IntegrityError as error:
            if "contact_id" not in _driver_message(error):
                raise
            raise ContactNotFoundError(contact_id) from error

    async def _resolve_anchors(
        self, user_id: str, creating_journal_id: int, due_journal_id: int
    ) -> Journal:
        """Load both anchors in one owner-scoped read and return the due journal.

        Ownership is enforced *by the query*, not by comparing a ``user_id``
        afterwards: a journal belonging to somebody else simply is not in the
        result, so it is indistinguishable from one that never existed and the
        error can leak nothing. One call covers both anchors — and the
        same-journal case collapses to a single id — so an extra journal never
        costs an extra round trip.
        """
        wanted = _ordered_unique([creating_journal_id, due_journal_id])
        found = {
            journal.id: journal
            for journal in await self.journal_repo.find_by_ids_for_user(user_id, wanted)
        }

        anchors: tuple[tuple[TaskJournalAnchor, int], ...] = (
            ("creating", creating_journal_id),
            ("due", due_journal_id),
        )
        for anchor, journal_id in anchors:
            if journal_id not in found:
                raise TaskAnchorJournalNotFoundError(anchor, journal_id)

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

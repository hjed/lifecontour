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

from typing import TYPE_CHECKING

from core_shared.models.tasks import (
    Task,
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskJournalAnchor,
)

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.services.journal_date_resolver import (
    is_future_dated,
    journal_date,
    today_in,
)
from app.infrastructure.unit_of_work import transactional

if TYPE_CHECKING:
    import datetime
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


class TaskService:
    """Creates tasks, enforcing the specification's core invariants."""

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

        created = await self.task_repo.save(task)
        assert created.id is not None, "Task ID must be set after save"
        for contact_id in contacts:
            await self.task_repo.add_contact(created.id, contact_id, user_id)
        return created

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
        """
        tz = await self.date_resolver.timezone_for(user_id)
        if is_future_dated(due_journal, tz, now):
            return

        raise TaskDueJournalNotFutureError(
            due_journal_id, journal_date(due_journal, tz), today_in(tz, now)
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

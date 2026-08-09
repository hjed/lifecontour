"""Reading a task back: the fetching half of the task read model.

:class:`TaskService` writes tasks. This reads them, and the two are separate
because they need different things and answer to different rules. Writing needs
a transaction, a lock and a domain event per change; reading needs none of
those, and must never acquire them — a read that opened a unit of work would
hold a transaction open for the length of a page render.

The service loads a task's pieces, resolves the acting user's timezone **once**,
turns each journal into a :class:`TaskJournalRef` dated in that timezone, and
hands everything to the pure assembler in ``core_shared``. Deciding *whether the
task lapsed* is not done here at all; deciding *whose day the dates belong to*
is done only here, and is the reason this layer exists rather than a controller
calling the rule directly.

**One read per collection.** A journal's task list calls this shape once per
task, so a read that costs one query per journal or per contact becomes an N+1
the first time a journal has twenty tasks in it. Every fetch below is batched
over the ids it needs, including the two anchors and the mentions, which go in a
single owner-scoped journal query.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from core_shared.models.journals import JournalNotFoundError
from core_shared.models.tasks import (
    TaskContactRef,
    TaskJournalRef,
    TaskNotFoundError,
    TaskReadModel,
    build_task_read_model,
)

from app.core.journal.services.journal_date_resolver import journal_date, today_in

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from zoneinfo import ZoneInfo

    from core_shared.models.journals import Journal
    from core_shared.models.tasks import Task

    from app.core.contacts.models.repositories import ContactRepository
    from app.core.journal.models.repositories import (
        CalendarInfoRepository,
        JournalRepository,
    )
    from app.core.journal.services.journal_date_resolver import JournalDateResolver
    from app.core.tasks.models.repositories import TaskRepository


def _ordered_unique(values: Iterable[int]) -> list[int]:
    """The values with duplicates dropped, first occurrence winning.

    A task's three journal roles overlap more often than not — invariant 6 lets
    one journal be both anchors, and a retarget onto an already-attached journal
    makes the due anchor a mention too — so the id list is de-duplicated before
    it becomes a query. Order is kept so the query's parameters are stable
    between runs rather than depending on set iteration.
    """
    return list(dict.fromkeys(values))


def _display_name(
    first_name: str | None, last_name: str | None, contact_id: int
) -> str:
    """A contact's name for a task row, tolerating missing parts.

    The same null-safe shape ``_enrich_journal_data`` uses on the same three
    columns, so a contact reads identically on a task and on a journal. The two
    are deliberately separate copies for now: the other lives inside a journals
    controller function, and lifting it out would rewrite a shipped endpoint.
    """
    parts = [part for part in (first_name, last_name) if part]
    return " ".join(parts) if parts else f"Contact {contact_id}"


class TaskReadService:
    """Assembles the read model for one of the acting user's tasks.

    Read-only: no ``@transactional``, no locks, no domain events. Provided at
    request scope by ``TaskProvider`` alongside :class:`TaskService`.
    """

    def __init__(
        self,
        task_repo: TaskRepository,
        journal_repo: JournalRepository,
        contact_repo: ContactRepository,
        calendar_info_repo: CalendarInfoRepository,
        date_resolver: JournalDateResolver,
    ) -> None:
        self.task_repo = task_repo
        self.journal_repo = journal_repo
        self.contact_repo = contact_repo
        self.calendar_info_repo = calendar_info_repo
        self.date_resolver = date_resolver

    async def read_model(
        self, user_id: str, task_id: int, *, now: datetime.datetime | None = None
    ) -> TaskReadModel:
        """One task with its journals by role, its contacts, and its lapse.

        Args:
            user_id: The acting user; every read below is scoped to them
            task_id: The task to read
            now: The instant to judge "today" from, for tests that need a
                specific side of a day boundary. Production omits it.

        Returns:
            The assembled read model.

        Raises:
            TaskNotFoundError: The task does not exist, or is not this user's —
                the two are deliberately indistinguishable.
            JournalNotFoundError: An anchor journal is missing, which the
                foreign keys make unreachable and which the read model cannot
                paper over.
        """
        task = await self.task_repo.find_by_id(task_id, user_id)
        if task is None:
            raise TaskNotFoundError(task_id)

        intermediate_ids = await self.task_repo.list_intermediate_journal_ids(
            task_id, user_id
        )
        contact_ids = await self.task_repo.list_contact_ids(task_id, user_id)

        timezone = await self.date_resolver.timezone_for(user_id)
        journal_refs = await self._journal_refs(
            user_id,
            _ordered_unique(
                [task.creating_journal_id, task.due_journal_id, *intermediate_ids]
            ),
            timezone,
        )

        return build_task_read_model(
            task=task,
            creating_journal=self._require_ref(journal_refs, task, "creating"),
            due_journal=self._require_ref(journal_refs, task, "due"),
            # A mention whose journal is missing is dropped rather than fatal.
            # The asymmetry with the anchors is deliberate: the due journal is
            # what the lapse rule reads, so losing it would make the answer a
            # guess, while losing a mention only loses a mention — and a task
            # the user can no longer open is worse than one showing one fewer
            # journal.
            intermediate_journals=[
                journal_refs[journal_id]
                for journal_id in intermediate_ids
                if journal_id in journal_refs
            ],
            contacts=await self._contact_refs(contact_ids),
            today=today_in(timezone, now),
        )

    async def _journal_refs(
        self, user_id: str, journal_ids: Sequence[int], timezone: ZoneInfo
    ) -> dict[int, TaskJournalRef]:
        """Every one of the user's journals among ``journal_ids``, keyed by id.

        Two queries for any number of journals: one owner-scoped fetch, then one
        batch cancellation lookup over whatever came back. Ownership is enforced
        by the first query rather than by a comparison afterwards, so another
        user's journal is simply absent — the same property ``TaskService``
        relies on for its anchors.
        """
        journals = {
            journal.id: journal
            for journal in await self.journal_repo.find_by_ids_for_user(
                user_id, list(journal_ids)
            )
            if journal.id is not None
        }
        cancelled_ids = await self.calendar_info_repo.find_cancelled_journal_ids(
            list(journals)
        )
        return {
            journal_id: self._journal_ref(
                journal_id, journal, timezone, cancelled=journal_id in cancelled_ids
            )
            for journal_id, journal in journals.items()
        }

    @staticmethod
    def _journal_ref(
        journal_id: int, journal: Journal, timezone: ZoneInfo, *, cancelled: bool
    ) -> TaskJournalRef:
        """One journal as a read surface sees it, dated in the user's timezone."""
        return TaskJournalRef(
            id=journal_id,
            title=journal.title,
            date=journal_date(journal, timezone),
            cancelled=cancelled,
        )

    @staticmethod
    def _require_ref(
        journal_refs: dict[int, TaskJournalRef], task: Task, anchor: str
    ) -> TaskJournalRef:
        """An anchor's ref, or the journal domain's 404.

        Both anchors are ``ON DELETE RESTRICT`` foreign keys and are resolved
        under the task's own owner, so an absent one means the data has been
        broken underneath us rather than that the caller asked for something
        reasonable. Failing beats inventing a lapse verdict for a journal
        nobody can see.
        """
        journal_id = (
            task.creating_journal_id if anchor == "creating" else task.due_journal_id
        )
        ref = journal_refs.get(journal_id)
        if ref is None:
            raise JournalNotFoundError(journal_id)
        return ref

    async def _contact_refs(self, contact_ids: Sequence[int]) -> list[TaskContactRef]:
        """The task's contacts, in link order, from one name lookup.

        An id with no row is skipped: ``task_contacts`` cascades from the
        contact side, so a deleted contact takes its link with it and this is
        only reachable through a race.
        """
        if not contact_ids:
            return []

        names = await self.contact_repo.find_names_by_ids(list(contact_ids))
        refs = []
        for contact_id in contact_ids:
            found = names.get(contact_id)
            if found is None:
                continue
            first_name, last_name, photo_url = found
            refs.append(
                TaskContactRef(
                    id=contact_id,
                    display_name=_display_name(first_name, last_name, contact_id),
                    photo_url=photo_url,
                )
            )
        return refs

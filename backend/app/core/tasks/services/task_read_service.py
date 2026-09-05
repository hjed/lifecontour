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
    DEFAULT_UPCOMING_DAYS_AHEAD,
    JournalTaskGroups,
    TaskContactRef,
    TaskJournalRef,
    TaskNotFoundError,
    TaskReadModel,
    TaskStatus,
    UpcomingTasks,
    build_task_read_model,
    derive_lapse_reason,
    group_tasks_by_link_role,
    select_upcoming_tasks,
    upcoming_window,
)

from app.core.journal.services.journal_date_resolver import (
    journal_date,
    local_window,
    today_in,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from zoneinfo import ZoneInfo

    from core_shared.models.journals import Journal
    from core_shared.models.tasks import Task, TaskLinkRole

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


def _lapses_its_tasks(
    journal_day: datetime.date, *, cancelled: bool, today: datetime.date
) -> bool:
    """Whether a not-done task due in this journal would already have lapsed.

    The lapse rule asked about a *journal* rather than a task. It is legitimate
    only where the journal being judged is the due journal itself — which on the
    listing it always is — and it goes through ``derive_lapse_reason`` rather
    than restating its two branches, so a later change to what lapsing means
    cannot leave the journal list behind.

    ``NOT_DONE`` is passed as the status because that is the only status the
    count contains: the query filters the terminal ones out before this is
    reached, and a done or cancelled task can never lapse anyway.
    """
    return (
        derive_lapse_reason(
            status=TaskStatus.NOT_DONE,
            due_journal_date=journal_day,
            due_journal_cancelled=cancelled,
            today=today,
        )
        is not None
    )


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
        models, _ = await self._assemble(
            user_id,
            [task],
            mentions={task_id: intermediate_ids},
            contacts={task_id: contact_ids},
            today=today_in(timezone, now),
            timezone=timezone,
        )
        return models[0]

    async def read_models_for_journal(
        self,
        user_id: str,
        journal_id: int,
        *,
        role: TaskLinkRole | None = None,
        now: datetime.datetime | None = None,
    ) -> JournalTaskGroups:
        """Every task linked to a journal, grouped by the role its link holds.

        The specification asks a journal's detail view for the tasks it is
        linked to, in three groups — due here, created here, mentioned here.
        This assembles all of them and hands them to the pure grouping rule.

        **Every linked task is returned, in every status.** The dashboard's
        tasks section hides done, cancelled and lapsed ones; a journal does not.
        Lapsed tasks "remain visible on every journal they are linked to", which
        is how a user finds one again, and a done task's link to the journal it
        arose in is part of the record. The lapse is therefore a *marker on the
        row* here rather than a filter.

        **Ownership costs no extra statement.** The journal is resolved through
        the same owner-scoped fetch the read models already need, so an unknown
        journal and another user's produce the same absence and the same error.
        A journal of the caller's with nothing linked to it is a different
        answer — three empty groups — which is the distinction that check buys.

        Args:
            user_id: The acting user; every read below is scoped to them
            journal_id: The journal being viewed
            role: Narrow the answer to one role, leaving the other two groups
                empty. Applied in the grouping rather than in SQL: a role is
                derived from anchors and mentions the read model already
                carries, so filtering in the query would be a second definition
                of it — and the query would still have to fetch the anchors.
            now: The instant to judge "today" from, for tests that need a
                specific side of a day boundary. Production omits it.

        Returns:
            The three groups, each ordered by due-journal date then task id.

        Raises:
            JournalNotFoundError: The journal does not exist or is not this
                user's — the two are deliberately indistinguishable.
        """
        tasks = await self.task_repo.find_tasks_for_journal(journal_id, user_id)
        task_ids = [task.id for task in tasks if task.id is not None]

        mentions = await self.task_repo.list_intermediate_journal_ids_for_tasks(
            task_ids, user_id
        )
        contacts = await self.task_repo.list_contact_ids_for_tasks(task_ids, user_id)

        timezone = await self.date_resolver.timezone_for(user_id)
        models, journal_refs = await self._assemble(
            user_id,
            tasks,
            mentions=mentions,
            contacts=contacts,
            today=today_in(timezone, now),
            timezone=timezone,
            # The viewed journal joins the batch rather than getting a lookup of
            # its own. It is almost always in there already — it anchors or is
            # mentioned by every task returned — and including it explicitly is
            # what makes the answer for a journal with *no* tasks a 200 with
            # three empty groups rather than a 404.
            extra_journal_ids=[journal_id],
        )
        if journal_id not in journal_refs:
            raise JournalNotFoundError(journal_id)

        return group_tasks_by_link_role(journal_id, models, role=role)

    async def read_models_for_upcoming_window(
        self,
        user_id: str,
        *,
        days_ahead: int = DEFAULT_UPCOMING_DAYS_AHEAD,
        now: datetime.datetime | None = None,
        timezone: ZoneInfo | None = None,
    ) -> UpcomingTasks:
        """The not-done tasks due between today and ``days_ahead`` days ahead.

        The dashboard's tasks section: "not-done tasks whose due journal falls
        between today and seven days ahead, inclusive", soonest first, with
        done, cancelled and lapsed tasks absent.

        **Today is the user's, not UTC's.** The timezone is resolved once and
        the window is built from it, so a user in Kiritimati is shown their
        Wednesday rather than the world's Tuesday. The window then reaches the
        query as instants, because that is what the stored column holds.

        **Today is in the window**, unlike the future-dated invariant on a due
        journal, which excludes it. The two rules answer different questions —
        "may this become a deadline" versus "is this deadline coming up" — and a
        task written yesterday for today is exactly what a dashboard is for.

        **The lapse is applied here rather than in SQL.** The query filters
        status and dates; the cancelled due journal that lapses a task inside a
        forward window is known only from the batched cancellation lookup
        ``_assemble`` already makes, so the exclusion belongs to the pure rule
        that reads the assembled verdict. Nothing re-derives it.

        Unpaginated and uncapped by design. The window bounds it, the dashboard
        applies its own five-item cap to what comes back, and a server-side cap
        would turn that cap's *show more* into a second request.

        Args:
            user_id: The acting user; every read below is scoped to them
            days_ahead: How far ahead to look, defaulting to the
                specification's seven
            now: The instant to judge "today" from, for tests that need a
                specific side of a day boundary. Production omits it.
            timezone: The acting user's zone, when the caller has **already
                resolved it**. Omit it and this resolves its own, which is what
                every surface does. It exists for a caller that asks what day it
                is on its own account as well — the daily summary's input
                assembler, which labels the day it is summarising — because two
                reads of ``user_settings`` in one request are two different
                statements under READ COMMITTED, and a timezone changed between
                them yields a prompt dated in the old zone around a window built
                in the new one. Raised by the pull request's automated review.

        Returns:
            The window and its tasks, ordered by due-journal date then task id.

        Raises:
            TaskValidationError: ``days_ahead`` is negative or beyond the
                maximum. Raised before the listing query, though **after** the
                settings read the window's anchor needs — the bound cannot be
                checked against a window that has not been built. Both surfaces
                reject an out-of-range value at their own schema, so in practice
                this is the backstop for a caller reaching the service directly
                rather than the path a bad request takes.
            JournalNotFoundError: An anchor journal is missing, which the
                foreign keys make unreachable.
        """
        zone = (
            timezone
            if timezone is not None
            else await self.date_resolver.timezone_for(user_id)
        )
        # Read once and carried, not consulted again below. With ``now=None``
        # each call to ``today_in`` reads the wall clock afresh, so a request
        # crossing local midnight between two of them would build the window
        # against one day and judge the lapse against the next — and a task due
        # on the earlier day would be dropped as "date passed" from a window
        # that still claims to include it. Raised by the pull request's
        # automated review.
        today = today_in(zone, now)
        window = upcoming_window(today, days_ahead)
        instants = local_window(window.first_day, window.last_day, zone)

        tasks = await self.task_repo.find_upcoming_tasks(
            user_id,
            window_start=instants.start,
            window_end=instants.end,
        )
        task_ids = [task.id for task in tasks if task.id is not None]

        mentions = await self.task_repo.list_intermediate_journal_ids_for_tasks(
            task_ids, user_id
        )
        contacts = await self.task_repo.list_contact_ids_for_tasks(task_ids, user_id)

        models, _ = await self._assemble(
            user_id,
            tasks,
            mentions=mentions,
            contacts=contacts,
            today=today,
            timezone=zone,
        )
        return select_upcoming_tasks(models, window)

    async def read_models_due_in_journals(
        self,
        user_id: str,
        journal_ids: Sequence[int],
        *,
        now: datetime.datetime | None = None,
        timezone: ZoneInfo | None = None,
    ) -> list[TaskReadModel]:
        """The tasks due in these journals, whatever became of each of them.

        The daily summary's past-day read. The upcoming window asks *what is
        still outstanding*; this asks *what was due here, and how did it
        resolve* — so where that listing drops done, cancelled and lapsed tasks,
        this one drops nothing at all. The finished tasks are the answer.

        **The status is the current one, and there is no reconstruction.** The
        row is read as it stands; ``field_history`` is never replayed and no
        point-in-time state is rebuilt. The consequence is deliberate and
        user-visible: a past day regenerated after a lapsed task was finally
        completed describes that task as **done**. That is the honest answer to
        "what became of this", and it is what the user already sees on the
        journal — a summary insisting the commitment was still outstanding would
        be the one contradicting the product.

        **A task retargeted off the day is absent**, for the same reason. The due
        anchor is read as it is now, so a commitment that has moved to next week
        is no longer part of how that day resolved. Nothing here reaches for
        where a task *used* to be due.

        **The day arrives as journal ids, not as a window.** The caller has
        already selected the day's journals — by overlap, so a multi-day journal
        running through the day is one of them — and re-deriving that span here
        would be a second definition of "that day" quietly different from the one
        the prompt is describing. It is also what makes the read cost nothing on
        a day with no journals.

        **Both halves of "which day is it" are injectable from birth.** ``now``
        fixes the instant and ``timezone`` the zone; the lapse verdict on every
        row hangs on the resulting date. The upcoming window gained its zone
        parameter from a review that found the asymmetry — a caller which had
        already read ``user_settings`` caused a second read, and two reads in one
        request are two statements a concurrent settings change can land between.
        This listing's only caller is exactly that caller, so it starts with
        both.

        Args:
            user_id: The acting user; every read below is scoped to them
            journal_ids: The day's journals. Empty reads nothing at all.
            now: The instant to judge "today" from, for tests that need a
                specific side of a day boundary. Production hands one down.
            timezone: The acting user's zone, when the caller has **already
                resolved it**. Omit it and this resolves its own.

        Returns:
            The models, in the query's order — the due journal's start, then the
            task id, which is the day's own sequence. Not re-sorted here: the
            statement already decided it, and a second ordering could disagree.

        Raises:
            JournalNotFoundError: An anchor journal is missing, which the
                foreign keys make unreachable.
        """
        if not journal_ids:
            return []

        zone = (
            timezone
            if timezone is not None
            else await self.date_resolver.timezone_for(user_id)
        )
        tasks = await self.task_repo.find_tasks_due_in_journals(
            list(journal_ids), user_id
        )
        task_ids = [task.id for task in tasks if task.id is not None]

        mentions = await self.task_repo.list_intermediate_journal_ids_for_tasks(
            task_ids, user_id
        )
        contacts = await self.task_repo.list_contact_ids_for_tasks(task_ids, user_id)

        models, _ = await self._assemble(
            user_id,
            tasks,
            mentions=mentions,
            contacts=contacts,
            today=today_in(zone, now),
            timezone=zone,
        )
        return models

    async def due_task_counts(
        self,
        user_id: str,
        journals: Sequence[Journal],
        *,
        now: datetime.datetime | None = None,
    ) -> dict[int, int]:
        """How many live commitments each of a page of journals is waiting on.

        The journal list's "tasks due" indicator. It counts a journal's not-done
        tasks and then drops the journals whose commitments have already
        **lapsed** — because a lapsed task leaves the dashboard silently and
        lighting a badge for it on the listing would be the counter the
        specification says lapsing must never produce.

        **The lapse rule collapses on this surface, which is why it is cheap.**
        Everywhere else the verdict needs the task's *due* journal fetched
        alongside it; here the due journal **is** the row journal, already
        loaded by the listing. So "would a not-done task due here be lapsed?" is
        a question about the journal, asked once per row, and it is put to
        ``derive_lapse_reason`` by way of :func:`_lapses_its_tasks` rather than
        re-derived — a second definition of *lapsed* on the busiest listing in
        the product is exactly the drift the pure rule exists to prevent.

        **A page that has nothing due costs one query.** The count runs first
        and, when it comes back empty, the timezone read and the cancellation
        lookup are skipped: there is nothing to judge. That is the path nearly
        every journal page takes, most journals having no tasks at all. A page
        that does have something due costs three, none of which grows with the
        page size.

        Args:
            user_id: The acting user; the count is scoped to them
            journals: The page's journals, as the listing already loaded them.
                Taken as entities rather than ids because their dates are what
                the lapse rule needs, and re-fetching them to learn what the
                caller already knows would be a fourth query.
            now: The instant to judge "today" from, for tests that need a
                specific side of a day boundary. Production omits it.

        Returns:
            A mapping of journal id to its live count. **Journals with nothing
            due are absent** rather than present with a zero, as the batched
            reads below this are, so callers read through ``.get(journal_id, 0)``.
        """
        journal_ids = [journal.id for journal in journals if journal.id is not None]
        if not journal_ids:
            return {}

        counts = await self.task_repo.count_not_done_tasks_by_due_journal(
            journal_ids, user_id
        )
        if not counts:
            return {}

        timezone = await self.date_resolver.timezone_for(user_id)
        today = today_in(timezone, now)
        # Narrowed to the journals that could still change the answer. Handing
        # the whole page over would make the cancellation lookup as wide as the
        # listing to settle a question about the few rows holding a commitment.
        cancelled = await self.calendar_info_repo.find_cancelled_journal_ids(
            [journal_id for journal_id in journal_ids if journal_id in counts]
        )

        return {
            journal.id: counts[journal.id]
            for journal in journals
            if journal.id in counts
            and not _lapses_its_tasks(
                journal_date(journal, timezone),
                cancelled=journal.id in cancelled,
                today=today,
            )
        }

    async def _assemble(
        self,
        user_id: str,
        tasks: Sequence[Task],
        *,
        mentions: dict[int, list[int]],
        contacts: dict[int, list[int]],
        today: datetime.date,
        timezone: ZoneInfo,
        extra_journal_ids: Sequence[int] = (),
    ) -> tuple[list[TaskReadModel], dict[int, TaskJournalRef]]:
        """Turn already-fetched tasks and their link ids into read models.

        **One read per collection, whatever the task count.** The timezone is
        resolved once, every journal across every role of every task arrives in
        one query, cancellation in one more, and every contact name in one. That
        is what lets the single-task read and a journal's whole task list share
        this method: the single read is simply the batch with one task in it,
        and its seven statements are the same seven. Seven is the *ceiling*
        rather than a constant: the contact-name lookup is skipped when nothing
        references anyone, and a journal with no tasks skips both batched link
        reads as well, so the floor is four. The invariance in the **task
        count** is the part that matters, and the part the tests pin.

        Args:
            user_id: The acting user
            tasks: The tasks to assemble, in the order they should come back
            mentions: Each task's intermediate journal ids, keyed by task id.
                A task with no links may be absent rather than empty.
            contacts: Each task's contact ids, on the same terms
            today: Today's date in the acting user's timezone, **already
                resolved**. A date rather than an instant, so this cannot read
                the clock a second time: with ``now=None`` every ``today_in``
                call samples the wall clock afresh, and a request crossing local
                midnight between two of them would judge one half of an answer
                against a different day from the other. The upcoming window
                needs the date before it has any tasks, so it resolves it and
                hands it down; taking it as a parameter is what makes the two
                halves agreeing structural rather than a coincidence of timing.
            timezone: The acting user's timezone, **already resolved**, on the
                same reasoning — one settings read per request, and no window
                for a change to it to land between two of them.
            extra_journal_ids: Journals to resolve beside the tasks' own — the
                journal a listing is *about*, which must be resolved even when
                nothing is linked to it

        Returns:
            The models, and the journal refs they were built from. The refs come
            back because a caller may need to know whether a journal of its own
            was among them, and re-fetching to find out would undo the batching.

        Raises:
            JournalNotFoundError: An anchor journal is missing.
        """
        journal_refs = await self._journal_refs(
            user_id,
            _ordered_unique(
                [
                    *extra_journal_ids,
                    *(
                        journal_id
                        for task in tasks
                        for journal_id in (
                            task.creating_journal_id,
                            task.due_journal_id,
                            *mentions.get(task.id or 0, []),
                        )
                    ),
                ]
            ),
            timezone,
        )
        contact_refs = await self._contact_refs_by_id(
            _ordered_unique(
                contact_id
                for task in tasks
                for contact_id in contacts.get(task.id or 0, [])
            )
        )

        models = [
            build_task_read_model(
                task=task,
                creating_journal=self._require_ref(journal_refs, task, "creating"),
                due_journal=self._require_ref(journal_refs, task, "due"),
                # A mention whose journal is missing is dropped rather than
                # fatal. The asymmetry with the anchors is deliberate: the due
                # journal is what the lapse rule reads, so losing it would make
                # the answer a guess, while losing a mention only loses a
                # mention — and a task the user can no longer open is worse than
                # one showing one fewer journal.
                intermediate_journals=[
                    journal_refs[journal_id]
                    for journal_id in mentions.get(task.id or 0, [])
                    if journal_id in journal_refs
                ],
                contacts=[
                    contact_refs[contact_id]
                    for contact_id in contacts.get(task.id or 0, [])
                    if contact_id in contact_refs
                ],
                today=today,
            )
            for task in tasks
        ]
        return models, journal_refs

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

    async def _contact_refs_by_id(
        self, contact_ids: Sequence[int]
    ) -> dict[int, TaskContactRef]:
        """Every contact across every task, keyed by id, from one name lookup.

        Keyed rather than ordered because the order belongs to each *task's*
        links, not to this set: a listing de-duplicates the ids across tasks to
        ask once, then re-reads each task's own link order out of this mapping.

        An id with no row is simply absent: ``task_contacts`` cascades from the
        contact side, so a deleted contact takes its link with it and this is
        only reachable through a race.
        """
        if not contact_ids:
            return {}

        names = await self.contact_repo.find_names_by_ids(list(contact_ids))
        refs: dict[int, TaskContactRef] = {}
        for contact_id in contact_ids:
            found = names.get(contact_id)
            if found is None:
                continue
            first_name, last_name, photo_url = found
            refs[contact_id] = TaskContactRef(
                id=contact_id,
                display_name=_display_name(first_name, last_name, contact_id),
                photo_url=photo_url,
            )
        return refs

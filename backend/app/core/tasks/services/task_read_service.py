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
single owner-scoped journal query, and the lists the tasks sit on, which go in
one more — skipped entirely when no task is on a list.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from core_shared.models.journals import JournalNotFoundError
from core_shared.models.tasks import (
    DEFAULT_UPCOMING_DAYS_AHEAD,
    JournalTaskGroups,
    TaskContactRef,
    TaskJournalAnchor,
    TaskJournalRef,
    TaskListNotFoundError,
    TaskListRef,
    TaskListTasks,
    TaskNotFoundError,
    TaskReadModel,
    TaskReadModelPage,
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
    journal_last_day,
    local_window,
    today_in,
)
from app.core.journal.services.journal_enrichment_service import (
    contact_display_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from zoneinfo import ZoneInfo

    from core_shared.models.journals import Journal
    from core_shared.models.tasks import Task, TaskLinkRole, TaskList

    from app.core.contacts.models.repositories import ContactRepository
    from app.core.journal.models.repositories import (
        CalendarInfoRepository,
        JournalRepository,
    )
    from app.core.journal.services.journal_date_resolver import JournalDateResolver
    from app.core.tasks.models.repositories import (
        TaskListRepository,
        TaskRepository,
    )


def _ordered_unique(values: Iterable[int]) -> list[int]:
    """The values with duplicates dropped, first occurrence winning.

    A task's three journal roles overlap more often than not — invariant 6 lets
    one journal be both anchors, and a retarget onto an already-attached journal
    makes the due anchor a mention too — so the id list is de-duplicated before
    it becomes a query. Order is kept so the query's parameters are stable
    between runs rather than depending on set iteration.
    """
    return list(dict.fromkeys(values))


def _to_list_ref(list_id: int, task_list: TaskList) -> TaskListRef:
    """The list a task sits on, as its read model carries it."""
    return TaskListRef(
        id=list_id,
        name=task_list.name,
        icon=task_list.icon,
        archived=task_list.is_archived,
    )


def _check_page(limit: int | None, offset: int) -> None:
    """Refuse a page no transport should be able to ask for."""
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be at least 0, got {offset}")


def _persisted_list_id(task_list: TaskList) -> int:
    """A resolved list's id; a list read back from storage always has one."""
    if task_list.id is None:
        raise ValueError("A list read back from storage has an id")
    return task_list.id


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
        task_list_repo: TaskListRepository,
        date_resolver: JournalDateResolver,
    ) -> None:
        self.task_repo = task_repo
        self.journal_repo = journal_repo
        self.contact_repo = contact_repo
        self.calendar_info_repo = calendar_info_repo
        self.task_list_repo = task_list_repo
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
            The three groups, each ordered by deadline (the due journal's date,
            else a list task's due date, undated last) then task id.

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
            Journal-only: a task on a list is left out, even one due inside
            the window.

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
        """The journal-only tasks due in these journals, whatever became of each.

        A task on a list is left out, as the summary reading this leaves list
        tasks out.

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

    async def read_models_on_list(
        self,
        user_id: str,
        task_list_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
        now: datetime.datetime | None = None,
    ) -> TaskReadModelPage:
        """A list's open tasks, in the user's manual order.

        The list page's main body. Every open task comes back by default: a
        list's open tasks are its working set, and the page shows them all.
        A ``limit`` cuts that set **before** it is assembled, so only the
        page's tasks have their journals and contacts read; the open rows
        themselves are one unpaged statement either way.

        Args:
            user_id: The acting user; every read below is scoped to them
            task_list_id: The list to read
            limit: The page size, or ``None`` for every open task
            offset: How many open tasks to skip when paging
            now: The instant to judge "today" (and so overdue) from, for tests

        Returns:
            The page, whose ``total`` is every open task on the list.

        Raises:
            TaskListNotFoundError: No such list, or it is not this user's —
                indistinguishably. Resolved before any task is read, because
                the repository answers an unowned list as an empty one.
            ValueError: ``limit`` below 1 or ``offset`` below 0; the transports
                bound both, so this is a caller's bug.
        """
        _check_page(limit, offset)
        task_list = await self._resolve_list(user_id, task_list_id)
        zone = await self.date_resolver.timezone_for(user_id)
        return await self._open_page(
            user_id, task_list, limit=limit, offset=offset, zone=zone, now=now
        )

    async def read_closed_models_on_list(
        self,
        user_id: str,
        task_list_id: int,
        *,
        limit: int,
        offset: int,
        now: datetime.datetime | None = None,
    ) -> TaskReadModelPage:
        """One page of a list's done and cancelled tasks, most recently closed
        first — the list page's Completed group.

        Args:
            user_id: The acting user; every read below is scoped to them
            task_list_id: The list to read
            limit: The page size, at least 1
            offset: How many closed tasks to skip, at least 0
            now: The instant to judge "today" from, for tests

        Returns:
            The page, with the total across every page — reported even for a
            page past the end.

        Raises:
            TaskListNotFoundError: As :meth:`read_models_on_list`.
            ValueError: A bad ``limit`` or ``offset``.
        """
        _check_page(limit, offset)
        task_list = await self._resolve_list(user_id, task_list_id)
        zone = await self.date_resolver.timezone_for(user_id)
        return await self._closed_page(
            user_id, task_list, limit=limit, offset=offset, zone=zone, now=now
        )

    async def read_list_with_tasks(
        self,
        user_id: str,
        task_list_id: int,
        *,
        page: int,
        limit: int,
        page_open_tasks: bool,
        include_completed: bool,
        now: datetime.datetime | None = None,
    ) -> TaskListTasks:
        """A list with its tasks in one answer — the MCP tool's read.

        The list is resolved once and the timezone read once for both
        sections. ``page`` and ``limit`` always page the completed tasks, and
        page the open ones too when ``page_open_tasks`` is set; otherwise
        every open task comes back.

        The two sections are separate statements with no transaction around
        them (reads open none), so a task closed in between can appear in
        both.

        Args:
            user_id: The acting user; every read below is scoped to them
            task_list_id: The list to read
            page: The 1-based page, for every paged section
            limit: The page size, for every paged section
            page_open_tasks: Page the open tasks as well
            include_completed: Read the completed page at all
            now: The instant to judge "today" from, for tests

        Raises:
            TaskListNotFoundError: As :meth:`read_models_on_list`.
            ValueError: ``page`` or ``limit`` below 1.
        """
        if page < 1:
            raise ValueError(f"page must be at least 1, got {page}")
        offset = (page - 1) * limit
        _check_page(limit, offset)
        task_list = await self._resolve_list(user_id, task_list_id)
        zone = await self.date_resolver.timezone_for(user_id)
        open_tasks = await self._open_page(
            user_id,
            task_list,
            limit=limit if page_open_tasks else None,
            offset=offset if page_open_tasks else 0,
            zone=zone,
            now=now,
        )
        completed = (
            await self._closed_page(
                user_id, task_list, limit=limit, offset=offset, zone=zone, now=now
            )
            if include_completed
            else None
        )
        return TaskListTasks(
            task_list=task_list, open_tasks=open_tasks, completed=completed
        )

    async def _resolve_list(self, user_id: str, task_list_id: int) -> TaskList:
        """The user's list, or its 404 — the read's ownership check."""
        task_list = await self.task_list_repo.find_by_id(task_list_id, user_id)
        if task_list is None:
            raise TaskListNotFoundError(task_list_id)
        return task_list

    async def _open_page(
        self,
        user_id: str,
        task_list: TaskList,
        *,
        limit: int | None,
        offset: int,
        zone: ZoneInfo,
        now: datetime.datetime | None,
    ) -> TaskReadModelPage:
        """The open tasks of an already-resolved list, cut before assembly."""
        list_id = _persisted_list_id(task_list)
        tasks = await self.task_repo.find_open_tasks_on_list(list_id, user_id)
        end = None if limit is None else offset + limit
        return TaskReadModelPage(
            models=await self._assemble_on_list(
                user_id, task_list, tasks[offset:end], zone=zone, now=now
            ),
            total=len(tasks),
        )

    async def _closed_page(
        self,
        user_id: str,
        task_list: TaskList,
        *,
        limit: int,
        offset: int,
        zone: ZoneInfo,
        now: datetime.datetime | None,
    ) -> TaskReadModelPage:
        """A page of the closed tasks of an already-resolved list."""
        closed = await self.task_repo.find_closed_tasks_on_list(
            _persisted_list_id(task_list), user_id, limit=limit, offset=offset
        )
        return TaskReadModelPage(
            models=await self._assemble_on_list(
                user_id, task_list, closed.tasks, zone=zone, now=now
            ),
            total=closed.total,
        )

    async def _assemble_on_list(
        self,
        user_id: str,
        task_list: TaskList,
        tasks: Sequence[Task],
        *,
        zone: ZoneInfo,
        now: datetime.datetime | None,
    ) -> tuple[TaskReadModel, ...]:
        """Assemble tasks read off one list, seeding their list ref with it.

        An empty page reads nothing more: there are no links to batch.
        """
        if not tasks:
            return ()
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
            known_lists=[task_list],
        )
        return tuple(models)

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

        **List tasks count, and are hidden with their journal.** A list task due
        in a journal is one of its not-done tasks, so it lights the badge. It
        never *lapses* — a late list task is overdue and stays on its list — but
        the journal-level rule here still drops the count once the journal has
        passed or been cancelled. That is a choice about the badge, not a lapse
        verdict on the task: the journal list does not keep a badge lit for
        lateness beyond its journal, as the dashboard shows an overdue task for
        only a week.

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
        known_lists: Sequence[TaskList] = (),
    ) -> tuple[list[TaskReadModel], dict[int, TaskJournalRef]]:
        """Turn already-fetched tasks and their link ids into read models.

        **One read per collection, whatever the task count.** The timezone is
        resolved once, every journal across every role of every task arrives in
        one query, cancellation in one more, every contact name in one, and
        every list the tasks sit on in one. That is what lets the single-task
        read and a journal's whole task list share this method: the single read
        is simply the batch with one task in it, and its statements are the
        same statements. Eight is the *ceiling* rather than a constant: the
        list lookup is skipped when no task is on a list — so a journal-only
        page costs the seven it always has — the contact-name lookup when
        nothing references anyone, and a journal with no tasks skips both
        batched link reads as well, so the floor is four. The invariance in the **task
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
            known_lists: Lists the caller has **already read** for this user —
                the list a listing is about — so their refs cost no second
                statement. Any other list the tasks sit on is still fetched.

        Returns:
            The models, and the journal refs they were built from. The refs come
            back because a caller may need to know whether a journal of its own
            was among them, and re-fetching to find out would undo the batching.

        Raises:
            JournalNotFoundError: A task's anchor journal is missing. An anchor
                the task does not have — a list task's — is not missing; its ref
                is ``None``.
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
                        # A list task may lack either anchor.
                        if journal_id is not None
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
            ),
            user_id=user_id,
        )
        list_refs = await self._list_refs(user_id, tasks, known_lists=known_lists)

        models = [
            build_task_read_model(
                task=task,
                creating_journal=self._anchor_ref(journal_refs, task, "creating"),
                due_journal=self._anchor_ref(journal_refs, task, "due"),
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
                task_list=self._list_ref(list_refs, task),
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
            last_day=journal_last_day(journal, timezone),
            cancelled=cancelled,
        )

    async def _list_refs(
        self,
        user_id: str,
        tasks: Sequence[Task],
        *,
        known_lists: Sequence[TaskList] = (),
    ) -> dict[int, TaskListRef]:
        """Every list the tasks sit on, keyed by id, from one owner-scoped read.

        Skipped when no task is on a list, so a page of journal-only tasks costs
        exactly what it did before lists existed — and when every list is among
        ``known_lists``, already read by the caller, so a list's own page costs
        no second list statement.
        """
        refs = {
            task_list.id: _to_list_ref(task_list.id, task_list)
            for task_list in known_lists
            if task_list.id is not None
        }
        missing = _ordered_unique(
            task.task_list_id
            for task in tasks
            if task.task_list_id is not None and task.task_list_id not in refs
        )
        if missing:
            found = await self.task_list_repo.find_by_ids(missing, user_id)
            refs.update(
                {
                    list_id: _to_list_ref(list_id, task_list)
                    for list_id, task_list in found.items()
                }
            )
        return refs

    @staticmethod
    def _list_ref(list_refs: dict[int, TaskListRef], task: Task) -> TaskListRef | None:
        """The task's list ref, ``None`` for a journal-only task.

        A list the owner cannot read is broken data underneath — a task's list
        is always its owner's — so it is the list's 404, as a vanished anchor
        is the journal's. Answering ``None`` would misreport a list task as
        journal-only, and its lapse with it.
        """
        if task.task_list_id is None:
            return None
        ref = list_refs.get(task.task_list_id)
        if ref is None:
            raise TaskListNotFoundError(task.task_list_id)
        return ref

    @staticmethod
    def _anchor_ref(
        journal_refs: dict[int, TaskJournalRef],
        task: Task,
        anchor: TaskJournalAnchor,
    ) -> TaskJournalRef | None:
        """An anchor's ref, ``None`` for an anchor the task does not have.

        A task on a list may have no journal in either role, and that is an
        ordinary task rather than a missing journal, so an **absent** anchor
        reads as ``None``.

        A **present** anchor whose journal is not among the refs is the journal
        domain's 404. Both anchors are ``ON DELETE RESTRICT`` foreign keys and
        are resolved under the task's own owner, so a vanished one means the
        data has been broken underneath us rather than that the caller asked
        for something reasonable. Failing beats inventing a lapse verdict for a
        journal nobody can see.
        """
        journal_id = (
            task.creating_journal_id if anchor == "creating" else task.due_journal_id
        )
        if journal_id is None:
            return None
        ref = journal_refs.get(journal_id)
        if ref is None:
            raise JournalNotFoundError(journal_id)
        return ref

    async def _contact_refs_by_id(
        self, contact_ids: Sequence[int], *, user_id: str
    ) -> dict[int, TaskContactRef]:
        """Every contact across every task, keyed by id, from one name lookup.

        Keyed rather than ordered because the order belongs to each *task's*
        links, not to this set: a listing de-duplicates the ids across tasks to
        ask once, then re-reads each task's own link order out of this mapping.

        An id with no row is simply absent: ``task_contacts`` cascades from the
        contact side, so a deleted contact takes its link with it and this is
        only reachable through a race. Another user's contact is absent too:
        the lookup is owner-scoped.
        """
        if not contact_ids:
            return {}

        names = await self.contact_repo.find_names_by_ids(
            list(contact_ids), user_id=user_id
        )
        refs: dict[int, TaskContactRef] = {}
        for contact_id in contact_ids:
            found = names.get(contact_id)
            if found is None:
                continue
            first_name, last_name, photo_url = found
            refs[contact_id] = TaskContactRef(
                id=contact_id,
                display_name=contact_display_name(first_name, last_name, contact_id),
                photo_url=photo_url,
            )
        return refs

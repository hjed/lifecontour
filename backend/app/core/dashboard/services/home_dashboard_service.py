"""Read service assembling the home dashboard.

Reads the four sections of the home page — summary, agenda, tasks and upcoming
contact dates — as one projection anchored on **today in the user's configured
timezone**. Read-only, so it opens no unit of work, matching
``OutdoorDashboardService``.

**The anchor is resolved once.** ``JournalDateResolver.timezone_for`` costs a
settings read and all four sections window on the same day, so the service takes
the zone once and uses the module's pure ``today_in`` — the batch discipline that
resolver's docstring asks for. Near local midnight an AEST user's "today" is not
UTC's, which is the whole reason the anchor is not simply ``date.today()``.

**Nothing here writes.** The summary section is the first to make that costly:
the journals view reads its summary through ``get_or_generate``, which commits a
row and then calls an AI model, so this service goes to
``JournalDailySummaryRepository`` for the same row instead. A page load must not
mutate, and regeneration stays a thing the user asks for on its own endpoint.

**Sections are read one at a time, each behind its own SAVEPOINT.** A request
holds a single ``AsyncConnection``, so concurrent section queries are not an
option, and a failed query would otherwise leave the transaction aborted and take
every section after it down with it. ``savepoint`` plus a caught ``Exception``
turns that into one section reporting *unavailable* while the rest answer
normally. A failure resolving the *anchor* is not a section failure and is left
to propagate: every window depends on it, so there is nothing to return.

**There is deliberately no composite dashboard MCP tool**, in this phase or this
iteration. An agent composes the same view from the daily-summary tool, journal
browsing, the task listing tools and the contacts tools, so no capability here is
UI-only; a fifth tool bundling four existing answers would be a second contract
to keep in step with this one for no new reach. Recorded as an accepted tradeoff.
"""

from __future__ import annotations

import datetime
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

from app.core.dashboard.models.sections import (
    AgendaDay,
    AgendaSectionData,
    DashboardSection,
    HomeDashboard,
    SummarySectionData,
    TasksSectionData,
    UpcomingDatesSectionData,
)
from app.core.dashboard.services.summary_section import summary_section_for
from app.core.dashboard.services.tasks_section import tasks_section_for
from app.core.journal.services.agenda import agenda_for_day
from app.core.journal.services.daily_summary_freshness import was_generated_on
from app.core.journal.services.journal_date_resolver import today_in
from app.infrastructure.unit_of_work import savepoint

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.core.contacts.services.upcoming_important_dates_service import (
        UpcomingImportantDatesService,
    )
    from app.core.journal.models.agenda import AgendaEntry
    from app.core.journal.models.repositories import AgendaRepository
    from app.core.journal.services.daily_summary_repository import (
        JournalDailySummaryRepository,
    )
    from app.core.journal.services.journal_date_resolver import JournalDateResolver
    from app.core.tasks.services.task_read_service import TaskReadService

logger = structlog.get_logger()


class HomeDashboardService:
    """Assembles the home dashboard's four sections for one user."""

    def __init__(
        self,
        date_resolver: JournalDateResolver,
        summary_repo: JournalDailySummaryRepository,
        agenda_repo: AgendaRepository,
        task_read_service: TaskReadService,
        upcoming_dates_service: UpcomingImportantDatesService,
        connection: AsyncConnection | None = None,
    ) -> None:
        self.date_resolver = date_resolver
        self.summary_repo = summary_repo
        self.agenda_repo = agenda_repo
        self.task_read_service = task_read_service
        self.upcoming_dates_service = upcoming_dates_service
        # Held for the per-section SAVEPOINTs, not for querying: the sections
        # read through their own repositories. ``savepoint`` no-ops without a
        # real connection, so a unit test may leave it out.
        self.connection = connection

    async def dashboard(
        self, user_id: str, now: datetime.datetime | None = None
    ) -> HomeDashboard:
        """The user's dashboard: all four sections, anchored on their today.

        Args:
            user_id: The acting user, whose timezone anchors every window.
            now: The instant the whole projection is read "as at" — the day
                every window is anchored on, and the moment the upcoming-dates
                ranking counts its recent activity back from. Injectable for
                testing either side of local midnight; defaults to **one**
                sample of the clock, shared by every section.

        Returns:
            The projection, with each section either ready or unavailable.
        """
        moment = now or datetime.datetime.now(datetime.UTC)
        tz = await self.date_resolver.timezone_for(user_id)
        anchor = today_in(tz, moment)

        return HomeDashboard(
            user_id=user_id,
            anchor_date=anchor,
            timezone=tz.key,
            summary=await self._section(
                "summary", lambda: self._load_summary(user_id, anchor, tz)
            ),
            agenda=await self._section(
                "agenda", lambda: self._load_agenda(user_id, anchor, tz)
            ),
            tasks=await self._section(
                "tasks", lambda: self._load_tasks(user_id, tz, moment)
            ),
            upcoming_dates=await self._section(
                "upcoming_dates",
                lambda: self._load_upcoming_dates(user_id, anchor, tz, moment),
            ),
        )

    async def _section[T](
        self, name: str, load: Callable[[], Awaitable[T | None]]
    ) -> DashboardSection[T]:
        """Read one section, degrading to *unavailable* if it cannot be read.

        A loader returns ``None`` when it read successfully and found there is
        nothing for the section to show — which for the summary is the ordinary
        state of a user whose day has no summary. That is unavailable too, since
        the wire distinguishes only *has a payload* from *has not*, but it is not
        an incident, so it is not logged as one. The loud path stays loud: a
        query that raised still warns, and its SAVEPOINT still rolls back so the
        remaining sections can use the connection.
        """
        try:
            async with savepoint(self.connection):
                data = await load()
        except Exception:
            logger.warning(
                "Home dashboard section unavailable",
                section=name,
                exc_info=True,
            )
            return DashboardSection.unavailable()

        if data is None:
            return DashboardSection.unavailable()
        return DashboardSection.ready(data)

    async def _load_summary(
        self, user_id: str, anchor: datetime.date, tz: ZoneInfo
    ) -> SummarySectionData | None:
        """Today's daily summary, read and never generated.

        ``DailySummaryService.get_or_generate`` is the journals view's path and
        it writes — a DISABLED row for an ineligible day, a GENERATING marker,
        then a multi-second AI call — so the dashboard goes to the repository
        instead. It is the same row, and a page load stays read-only.

        Read-only includes the freshness rule: a summary for today that was not
        generated today in the user's zone must not be served, so it is judged
        here with the anchor day and zone already in hand, and presented as
        generating rather than regenerated. Regenerating it is the user's own
        Regenerate control's job, or the journals view's, or MCP's.
        """
        summary = await self.summary_repo.find_by_user_and_date(user_id, anchor)
        if summary is None:
            return None
        return summary_section_for(
            summary, stale=not was_generated_on(summary, anchor, tz)
        )

    async def _load_agenda(
        self, user_id: str, anchor: datetime.date, tz: ZoneInfo
    ) -> AgendaSectionData:
        """Today's event journals in the order the card draws them, then tomorrow's.

        Each day's window is the user's **local** day, built by
        ``local_day_window`` so that a zone whose clocks change is the 23 or 25
        hours it really is and a day that ends in a repeated hour still ends
        where it ends. The day's date goes with it because an all-day event
        happens on a *date* rather than at instants and is matched by date;
        timed events are matched by overlap, so a multi-day journal running
        through today is on it. The ordering rule is applied here rather than in
        SQL because it belongs to the section, not to the query.

        **Tomorrow is a second read of the same query, not a wider one.** The
        page is one round trip, so tomorrow rides in this payload (open decision
        5); but one two-day window split afterwards could not put a multi-day
        event overlapping both days on both, and could not match all-day events
        against two dates. Two reads inside the section's one SAVEPOINT can, and
        a failure on either degrades the whole section rather than leaving a
        payload that looks complete while quietly missing a day.

        A day with nothing on it returns an **empty payload**, not ``None``:
        "nothing scheduled today" is an answer this section can give, and it must
        not arrive looking like the section that could not answer at all.
        """
        tomorrow = anchor + datetime.timedelta(days=1)
        return AgendaSectionData(
            entries=await self._agenda_for(user_id, anchor, tz),
            tomorrow=AgendaDay(
                date=tomorrow,
                entries=await self._agenda_for(user_id, tomorrow, tz),
            ),
        )

    async def _agenda_for(
        self, user_id: str, day: datetime.date, tz: ZoneInfo
    ) -> tuple[AgendaEntry, ...]:
        """One local day's event journals, in the agenda's order.

        The windowing and the ordering live together in ``agenda_for_day``
        because the daily summary reads the same day through it: two callers
        assembling the window themselves is two chances to disagree about where
        the user's day starts.
        """
        return await agenda_for_day(self.agenda_repo, user_id, day, tz)

    async def _load_tasks(
        self, user_id: str, tz: ZoneInfo, moment: datetime.datetime
    ) -> TasksSectionData:
        """Not-done tasks due between today and seven days ahead, soonest first.

        Read through the tasks domain's own upcoming-window listing rather than
        a query of the dashboard's: it is the same answer ``GET
        /api/tasks/upcoming`` returns, the same one an agent gets from
        ``list_upcoming_tasks``, and the same one ``DailySummaryInputAssembler``
        gathers for the prompt. Four callers assembling the window themselves
        would be four chances to disagree about which week it is, and the
        listing's docstring names this section as the caller it was shaped for.

        The window's span is left at the shared default that section and the
        upcoming dates beside it both inherit, because the specification says
        the two evidence columns cover the *same* seven days.

        **The zone and the instant are handed down, not re-resolved.** The
        listing resolves its own only when nobody gives it either, so passing
        both means the page still pays for exactly one ``user_settings`` read
        and reads every section as at one moment. It takes no ``today``: it
        derives the day from this pair, which is the pair the anchor above came
        from, so the section cannot land on a different day from the header.

        Done, cancelled and lapsed tasks are absent, and none of that is decided
        here — ``select_upcoming_tasks`` applies all three inside the listing.
        The one that genuinely bites in a *forward* window is the cancelled due
        journal: a date-passed lapse cannot fall inside a window that starts
        today.

        An empty week returns an **empty payload**, not ``None``: "nothing due
        in the next seven days" is an answer this section gives, and the card
        renders it as a good outcome rather than as a section that failed.
        """
        upcoming = await self.task_read_service.read_models_for_upcoming_window(
            user_id, now=moment, timezone=tz
        )
        return tasks_section_for(upcoming)

    async def _load_upcoming_dates(
        self,
        user_id: str,
        anchor: datetime.date,
        tz: ZoneInfo,
        moment: datetime.datetime,
    ) -> UpcomingDatesSectionData:
        """Important contact dates in the same seven days the tasks cover.

        Read through the contacts domain's shared service rather than a query of
        the dashboard's own: an agent reaches the same answer through
        ``list_upcoming_important_dates``, and the daily summary will reach it
        again (ITER18-005 Phase 6). Three callers assembling the window
        themselves is three chances to disagree about which week it is.

        **The anchor is handed down, not re-resolved.** The service resolves its
        own only when nobody gives it one; passing the dashboard's means this
        section cannot land on a different day from the agenda beside it, and
        the page still pays for exactly one settings read.

        **So is the instant, and the day alone was not enough.** This section is
        the only one ordered by something counted over a *window of time* rather
        than read off a row: importance signals are the last thirty days back
        from an instant. Handing down only the day left that instant to be
        sampled again downstream, so a caller who pinned ``now`` got a window
        fixed to one moment and a tie-break computed from another — not the
        single as-at snapshot this projection is meant to be. Raised by the
        review on #1407, and the third instance of two-clocks in this iteration.
        """
        upcoming = await self.upcoming_dates_service.upcoming_dates(
            user_id, today=anchor, now=moment
        )
        return UpcomingDatesSectionData(window=upcoming.window, dates=upcoming.dates)

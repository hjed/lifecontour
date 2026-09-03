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
from app.core.dashboard.services.agenda_section import order_agenda_entries
from app.core.dashboard.services.summary_section import summary_section_for
from app.core.journal.services.journal_date_resolver import (
    local_day_window,
    today_in,
)
from app.infrastructure.unit_of_work import savepoint

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.core.dashboard.models.repositories import AgendaRepository
    from app.core.dashboard.models.sections import AgendaEntry
    from app.core.journal.services.daily_summary_repository import (
        JournalDailySummaryRepository,
    )
    from app.core.journal.services.journal_date_resolver import JournalDateResolver

logger = structlog.get_logger()


class HomeDashboardService:
    """Assembles the home dashboard's four sections for one user."""

    def __init__(
        self,
        date_resolver: JournalDateResolver,
        summary_repo: JournalDailySummaryRepository,
        agenda_repo: AgendaRepository,
        connection: AsyncConnection | None = None,
    ) -> None:
        self.date_resolver = date_resolver
        self.summary_repo = summary_repo
        self.agenda_repo = agenda_repo
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
            now: The instant to read "today" from, for testing either side of
                local midnight. Defaults to the current time.

        Returns:
            The projection, with each section either ready or unavailable.
        """
        tz = await self.date_resolver.timezone_for(user_id)
        anchor = today_in(tz, now)

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
                "tasks", lambda: self._load_tasks(user_id, anchor, tz)
            ),
            upcoming_dates=await self._section(
                "upcoming_dates",
                lambda: self._load_upcoming_dates(user_id, anchor, tz),
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
        """
        return summary_section_for(
            await self.summary_repo.find_by_user_and_date(user_id, anchor)
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
        """One local day's event journals, in the agenda's order."""
        entries = await self.agenda_repo.list_entries_in_window(
            user_id, window=local_day_window(day, tz), anchor=day
        )
        return order_agenda_entries(entries)

    async def _load_tasks(
        self, user_id: str, anchor: datetime.date, tz: ZoneInfo
    ) -> TasksSectionData:
        """Not-done tasks due in the next seven days. Filled by Phase 13."""
        return TasksSectionData()

    async def _load_upcoming_dates(
        self, user_id: str, anchor: datetime.date, tz: ZoneInfo
    ) -> UpcomingDatesSectionData:
        """Important contact dates in the next seven days. Filled by Phase 11."""
        return UpcomingDatesSectionData()

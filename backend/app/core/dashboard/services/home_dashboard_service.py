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
    AgendaSectionData,
    DashboardSection,
    HomeDashboard,
    SummarySectionData,
    TasksSectionData,
    UpcomingDatesSectionData,
)
from app.core.dashboard.services.summary_section import summary_section_for
from app.core.journal.services.journal_date_resolver import today_in
from app.infrastructure.unit_of_work import savepoint

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from sqlalchemy.ext.asyncio import AsyncConnection

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
        connection: AsyncConnection | None = None,
    ) -> None:
        self.date_resolver = date_resolver
        self.summary_repo = summary_repo
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
        """Today's and tomorrow's event journals. Filled by Phases 5 and 6."""
        return AgendaSectionData()

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

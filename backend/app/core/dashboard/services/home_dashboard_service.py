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
from app.core.journal.services.journal_date_resolver import today_in
from app.infrastructure.unit_of_work import savepoint

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.core.journal.services.journal_date_resolver import JournalDateResolver

logger = structlog.get_logger()


class HomeDashboardService:
    """Assembles the home dashboard's four sections for one user."""

    def __init__(
        self,
        date_resolver: JournalDateResolver,
        connection: AsyncConnection | None = None,
    ) -> None:
        self.date_resolver = date_resolver
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
        self, name: str, load: Callable[[], Awaitable[T]]
    ) -> DashboardSection[T]:
        """Read one section, degrading to *unavailable* if it cannot be read."""
        try:
            async with savepoint(self.connection):
                return DashboardSection.ready(await load())
        except Exception:
            logger.warning(
                "Home dashboard section unavailable",
                section=name,
                exc_info=True,
            )
            return DashboardSection.unavailable()

    async def _load_summary(
        self, user_id: str, anchor: datetime.date, tz: ZoneInfo
    ) -> SummarySectionData:
        """Today's daily summary. Filled by Phase 2."""
        return SummarySectionData()

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

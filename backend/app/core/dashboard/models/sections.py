"""The home dashboard's sections and the envelope they travel in.

The dashboard is four independent evidence sections read in one round trip, and
any one of them can fail without the page being useless. So every section is
wrapped in a :class:`DashboardSection`, which distinguishes the two answers a
section can give that look alike but are not:

- **ready** — the section was read. Its payload may hold nothing, and "nothing
  scheduled today" is a real answer that a surface renders as one quiet line.
- **unavailable** — the section could not be read. ``data`` is ``None`` rather
  than an empty payload, so no caller can mistake a failure for an empty day.

The payload types are declared here from the outset and filled by later phases
(summary, agenda, tasks, upcoming dates). They are deliberately empty for now:
what this phase settles is the *envelope*, so the phases that add fields do not
have to change the contract around them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class SectionStatus(StrEnum):
    """Whether a section was read, or could not be."""

    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DashboardSection[T]:
    """One section of the dashboard, with the payload it managed to read.

    Built through :meth:`ready` and :meth:`unavailable` rather than directly, so
    an unavailable section can never be constructed holding data.
    """

    status: SectionStatus
    data: T | None = None

    @classmethod
    def ready(cls, data: T) -> DashboardSection[T]:
        """The section was read; ``data`` may be empty, which is an answer."""
        return cls(status=SectionStatus.READY, data=data)

    @classmethod
    def unavailable(cls) -> DashboardSection[T]:
        """The section could not be read; it carries no payload."""
        return cls(status=SectionStatus.UNAVAILABLE, data=None)

    @property
    def is_ready(self) -> bool:
        """Whether the section has a payload to render."""
        return self.status is SectionStatus.READY


@dataclass(frozen=True)
class SummarySectionData:
    """Today's daily summary. Filled by Phase 2."""


@dataclass(frozen=True)
class AgendaSectionData:
    """Today's event journals, and tomorrow's. Filled by Phases 5 and 6."""


@dataclass(frozen=True)
class TasksSectionData:
    """Not-done tasks due in the next seven days. Filled by Phase 13."""


@dataclass(frozen=True)
class UpcomingDatesSectionData:
    """Important contact dates falling in the next seven days. Filled by Phase 11."""


@dataclass(frozen=True)
class HomeDashboard:
    """The whole projection: the day it is about, and the four sections.

    ``anchor_date`` and ``timezone`` are the day every section was windowed on
    and the zone that decided where that day starts and ends. They are carried
    on the projection rather than left for a caller to re-derive because a
    browser recomputing "today" in its own zone could disagree with the rows it
    was just sent.
    """

    user_id: str
    anchor_date: date
    timezone: str
    summary: DashboardSection[SummarySectionData]
    agenda: DashboardSection[AgendaSectionData]
    tasks: DashboardSection[TasksSectionData]
    upcoming_dates: DashboardSection[UpcomingDatesSectionData]

"""The home dashboard's sections and the envelope they travel in.

The dashboard is four independent evidence sections read in one round trip, and
any one of them can fail without the page being useless. So every section is
wrapped in a :class:`DashboardSection`, which distinguishes the two answers a
section can give that look alike but are not:

- **ready** — the section has a payload. It may hold nothing, and "nothing
  scheduled today" is a real answer that a surface renders as one quiet line.
- **unavailable** — the section has no payload. ``data`` is ``None`` rather than
  an empty payload, so no caller can mistake it for an empty day.

**A section with no payload need not have failed.** The envelope was written for
sections that are lists, where *could not read* and *read, found nothing* are
worth separating. The summary is not a list: either the day has a summary or it
does not, and "it does not" is the same quiet line as "we could not tell you", so
that section reports unavailable for both. A section whose emptiness is
meaningful says so with a ready payload instead; both kinds are in use, and which
a section is belongs to the section, not to this envelope.

The payload types are declared here from the outset and filled by their own
phases. Summary and agenda are filled; tasks and upcoming dates are still empty,
which serialises as ``{}`` — ready, holding nothing — until the phases that give
them fields land.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum


class SectionStatus(StrEnum):
    """Whether a section has a payload, or has nothing for the page."""

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
        """The section has nothing to show: it could not be read, or has none.

        Which of the two it was is deliberately not on the wire. Both render as
        the same quiet line, and a section that wanted to tell them apart would
        report *ready* with a payload saying so.
        """
        return cls(status=SectionStatus.UNAVAILABLE, data=None)

    @property
    def is_ready(self) -> bool:
        """Whether the section has a payload to render."""
        return self.status is SectionStatus.READY


class DashboardSummaryState(StrEnum):
    """Which of the summary card's two *present* states a payload is in.

    The wireframe declares three states for the card, and the third —
    *unavailable* — is the absence of a summary rather than a summary in some
    condition, so it is the section's status and has no payload to sit in. That
    leaves exactly these two here, which is why a section that is ``ready``
    always has something the card can draw.
    """

    GENERATED = "generated"
    GENERATING = "generating"


@dataclass(frozen=True)
class SummarySectionData:
    """Today's daily summary — the page's headline.

    The same ``journal_daily_summaries`` row the journals view shows, read
    rather than produced: the dashboard never generates a summary, because a
    page load must not write.

    ``summary_text`` is the prose of the generated state and is ``None`` in the
    generating one, taken from the entity's own ``get_display_text`` so a row
    invalidated after the day changed cannot show yesterday's words. The four
    counters are carried whichever state applies; where they are *rendered* is
    the card's decision, not the payload's.
    """

    state: DashboardSummaryState
    summary_text: str | None = None
    journal_count: int = 0
    event_count: int = 0
    contact_count: int = 0
    mood_average: float | None = None


@dataclass(frozen=True)
class AgendaTag:
    """One of a journal's tags, as the agenda row draws it.

    The colour travels with the name because the card renders a colour-coded
    badge (**W15**) and a badge whose colour arrived separately from its label
    is one refactor away from showing the wrong one.
    """

    id: str
    name: str
    colour: str | None = None


@dataclass(frozen=True)
class AgendaParticipant:
    """A contact taking part in an event, for the avatar stack (**W16**).

    ``name`` is the whole display name rather than its parts: the stack shows
    initials and needs a readable label behind them, and deriving either from
    first/last would put that rule in the card instead of here.
    """

    contact_id: int
    name: str


@dataclass(frozen=True)
class AgendaEntry:
    """One event journal on the agenda.

    **Both the instants and the clock times are carried, and they answer
    different questions.** ``starts_at``/``ends_at`` are the journal's stored
    ``event_date_range`` — the quantity the day window compares against, the key
    the entries are ordered by, and the only way to tell that an entry began
    before today. ``start_time``/``end_time`` are the ``TIME`` columns
    ``journal_calendar_info`` stores, which is what the existing calendar surface
    renders and what **W13** draws as ``HH:MM - HH:MM``; they are ``None`` for an
    all-day event, and may be ``None`` for a timed one whose times were never
    filled in.

    ``is_cancelled`` is derived from ``CalendarInfo.event_state`` at the edge, so
    nothing downstream has to know the rest of that vocabulary. It is carried
    rather than filtered on because the specification requires a cancelled event
    to be *shown clearly marked* rather than silently dropped (**W18**) — but it
    is carried precisely so that no surface can present one as still happening.
    """

    journal_id: int
    title: str
    is_all_day: bool
    starts_at: datetime
    ends_at: datetime
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = None
    is_cancelled: bool = False
    tags: tuple[AgendaTag, ...] = ()
    participants: tuple[AgendaParticipant, ...] = ()


@dataclass(frozen=True)
class AgendaSectionData:
    """Today's event journals, in the order the card draws them.

    ``entries`` defaults to empty because a day with nothing scheduled is an
    answer this section can give: *ready* holding no entries, which the card
    renders as one quiet line, and which no caller can confuse with the section
    having failed to answer at all.

    Tomorrow's entries and their collapsed count (**W19**) land in Phase 6, as a
    field beside this one.
    """

    entries: tuple[AgendaEntry, ...] = ()


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

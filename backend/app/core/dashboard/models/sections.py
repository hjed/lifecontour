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
phases. Summary, agenda (today and tomorrow) and upcoming dates are filled;
tasks is still empty, which serialises as ``{}`` — ready, holding nothing —
until Phase 13 gives it fields.

**The agenda's rows are not declared here.** ``AgendaEntry`` and the tag and
participant it carries live in ``app.core.journal.models.agenda``, because they
describe journals and the daily summary reads them too. What stays is the part
that really is the dashboard's: ``AgendaDay``'s labelled day and
``AgendaSectionData``'s tomorrow-beneath-today shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from core_shared.models.date_window import UpcomingWindow

from app.core.contacts.models.upcoming_dates import UpcomingContactDate
from app.core.journal.models.agenda import AgendaEntry


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
class AgendaDay:
    """One day's event journals, in the order the card draws them.

    The ``date`` is the local day the entries were windowed on — carried for the
    same reason the projection carries its anchor: the disclosure's label
    (**W19**) must name the day the entries actually belong to, and a browser
    working "tomorrow" out in its own zone could disagree with the rows it was
    sent.

    ``entries`` defaults to empty because a day with nothing scheduled is an
    answer: *ready* holding no entries, which the card renders as one quiet line.
    The collapsed count **W19** shows is ``len(entries)`` rather than a second
    field, because the list is not capped and a count kept beside it would be
    derivable data that can drift from the thing it describes. Cancelled entries
    count — they are shown when the day is expanded, marked (**W18**), and a
    count that skipped them would be the first step towards a list that did.
    """

    date: date
    entries: tuple[AgendaEntry, ...] = ()


@dataclass(frozen=True)
class AgendaSectionData:
    """Today's event journals, with tomorrow's beneath them.

    ``entries`` is today, in the order the card draws it. It defaults to empty
    because a day with nothing scheduled is an answer this section can give:
    *ready* holding no entries, which the card renders as one quiet line, and
    which no caller can confuse with the section having failed to answer at all.

    ``tomorrow`` rides in the same payload rather than behind a second request
    (open decision 5): the page is one round trip, and tomorrow is one extra day
    of a small list, not a second page of data. It is **required**, not
    optional, so that "nothing tomorrow" and "tomorrow was never read" can never
    be the same absence — a ready agenda has both days, or it is not ready.
    """

    tomorrow: AgendaDay
    entries: tuple[AgendaEntry, ...] = ()


@dataclass(frozen=True)
class TasksSectionData:
    """Not-done tasks due in the next seven days. Filled by Phase 13."""


@dataclass(frozen=True)
class UpcomingDatesSectionData:
    """Important contact dates falling in the same seven days the tasks cover.

    **The rows are not declared here**, for the reason the agenda's are not:
    ``UpcomingContactDate`` describes contacts, and the daily summary reads the
    same occurrences (ITER18-005 Phase 6). What is the dashboard's own is this
    pairing of the window with the rows it found.

    The window rides in the payload rather than being left to a client to derive
    from ``meta.anchor``: a section that says "the next seven days" must be able
    to say so when it found **nothing**, and an empty list has no rows to
    subtract dates from.

    **Uncapped.** ITER18-004 Phase 13 settled the shape for both evidence
    sections — the whole window travels and the card applies its cap (three, per
    open decision 3), so a show-more reveals the rest without a second request.

    Attributes:
        window: The span these dates were read for
        dates: The occurrences in it, ordered by date then contact importance
    """

    window: UpcomingWindow
    dates: tuple[UpcomingContactDate, ...] = ()


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

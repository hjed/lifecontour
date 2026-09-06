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

The payload types were declared here from the outset and filled by their own
phases; all four now carry fields, and none of those phases added, renamed or
reshaped a section.

**Most sections' rows are not declared here.** ``AgendaEntry`` and the tag and
participant it carries live in ``app.core.journal.models.agenda``, and
``UpcomingContactDate`` in the contacts domain, because they describe journals
and contacts and the daily summary reads them too. What stays is the part that
really is the dashboard's: ``AgendaDay``'s labelled day and
``AgendaSectionData``'s tomorrow-beneath-today shape.

``DashboardTask`` is the exception, and its reason is the test of the rule. The
tasks section does not show a task read model: it shows less of one — no status,
no lapse, neither the creating journal nor the intermediate ones — plus a field
no read model has, the ``days_away`` its relative chip is drawn from. That is a
row belonging to this page rather than to the tasks domain, so it is declared
here, over the tasks domain's own journal and contact refs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from core_shared.models.date_window import UpcomingWindow
from core_shared.models.tasks import TaskContactRef, TaskJournalRef

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
class DashboardTask:
    """One task as the dashboard's row draws it (**W22**–**W27**).

    A row of this section rather than a task read model on the wire, and the
    difference is two-way. It **adds** ``days_away``, which no read model
    carries because no other surface draws a relative due chip; and it **drops**
    the status, the lapse, the creating journal and the intermediate journals,
    every one of which is either constant for every row this section can hold or
    material no dashboard row shows. A field that is always the same value
    invites a surface to branch on it.

    The two field types it does keep are the tasks domain's own
    ``TaskJournalRef`` and ``TaskContactRef``, reused rather than re-declared:
    they already say exactly what a row needs, and a parallel pair would be two
    definitions of a task's journal to keep in step.

    Attributes:
        task_id: The task itself, which is what the inline done action acts on
        text: The commitment, as the user wrote it (**W23**)
        due_journal: The journal it is due in — id and title for the link
            (**W26**), and the date **already resolved in the acting user's
            timezone**. ``cancelled`` on it is always false here: a cancelled
            due journal lapses its task, and a lapsed task is not in this
            section.
        days_away: How many days from the window's first day the due journal
            falls, ``0`` meaning today. The material the relative chip is drawn
            from (**W25**), published rather than left to be derived: the
            window's first day is the page's anchor, and a browser subtracting
            dates in its own zone can land a day out near midnight.
        contacts: The people the task references, in link order (**W27**)
    """

    task_id: int
    text: str
    due_journal: TaskJournalRef
    days_away: int
    contacts: tuple[TaskContactRef, ...] = ()


@dataclass(frozen=True)
class TasksSectionData:
    """Not-done tasks due between today and seven days ahead, soonest first.

    The window rides in the payload for the reason the upcoming dates' does: a
    section that says "the next seven days" has to be able to say so when it
    found **nothing**, and an empty list has no rows to derive a span from.

    **Uncapped.** The whole window travels and the card applies the five-item
    cap (**W22**), so the show-more (**W28**) reveals the remainder from data the
    page already holds rather than making a second request. The count that
    show-more names is the length of ``tasks``.

    Done, cancelled and lapsed tasks are absent, and none of those exclusions is
    decided here: they belong to ``select_upcoming_tasks``, which the read
    service applies before this payload is assembled.

    Attributes:
        window: The span these tasks were read for
        tasks: The rows, ordered by due-journal date then task id
    """

    window: UpcomingWindow
    tasks: tuple[DashboardTask, ...] = ()


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

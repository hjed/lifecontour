"""A day's event journals, denormalised for the surfaces that list them.

**This is a journal projection, not a dashboard one.** Every row it describes is
a journal: the read behind it joins ``journals``, ``journal_calendar_info``,
``calendars``, the tag assignments and the contact relationships, and a journal
has the EVENT type exactly when a calendar-info row exists for it. It lived in
the dashboard domain while the dashboard was its only caller; the daily summary
is the second, and a journal-domain caller reaching into the dashboard for a
read over journal tables had the dependency backwards.

``OutdoorDashboardRepository`` is the precedent: a projection shaped for one
card still belongs to the domain whose rows it returns. The dashboard keeps what
is genuinely its own — ``AgendaDay`` and ``AgendaSectionData``, the envelope and
the tomorrow-disclosure shape — and imports these, which is the direction that
already existed.

The wireframe references below are kept deliberately. They record *why* a field
is carried rather than derived at the edge, and the reason survives the move.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


@dataclass(frozen=True)
class AgendaTag:
    """One of a journal's tags, as the agenda row draws it.

    The colour travels with the name because the card renders a colour-coded
    badge (**W15**) and a badge whose colour arrived separately from its label
    is one refactor away from showing the wrong one.

    Spelled ``color`` against this codebase's usual Australian English, because
    it is the name the column, the tags API and the frontend's own tag type all
    use. A second spelling for one field would mean the same tag arriving under
    two names from two endpoints.
    """

    id: str
    name: str
    color: str | None = None


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
    """One event journal on a day's agenda.

    **Both the instants and the clock times are carried, and they answer
    different questions.** ``starts_at``/``ends_at`` are the journal's stored
    ``event_date_range`` — the quantity the day window compares against, the key
    the entries are ordered by, and the only way to tell that an entry began
    before today. ``start_time``/``end_time`` are the ``TIME`` columns
    ``journal_calendar_info`` stores, which is what the existing calendar surface
    renders and what **W13** draws as ``HH:MM - HH:MM``; they are ``None`` for an
    all-day event, and may be ``None`` for a timed one whose times were never
    filled in.

    ``calendar_color`` is the colour of the calendar the event belongs to, which
    is what **W17** keys the row's accent bar to. It travels with the entry
    because the accent is per row: a card that fetched calendars separately would
    have to join them back up itself, and the calendar is already reachable from
    the row the query reads. The journal's *type* glyph (**W14**) is a separate
    join and is not here.

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
    timezone: str | None = None
    location: str | None = None
    calendar_color: str | None = None
    is_cancelled: bool = False
    tags: tuple[AgendaTag, ...] = ()
    participants: tuple[AgendaParticipant, ...] = ()

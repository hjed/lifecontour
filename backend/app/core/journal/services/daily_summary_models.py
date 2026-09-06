"""Data models for daily summary generation pipeline.

Defines the input contract for assembling journal data for a single day
into a structured format suitable for AI prompt building.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core_shared.models.tasks import TaskReadModel, UpcomingTasks

    from app.core.contacts.models.upcoming_dates import UpcomingContactDates
    from app.core.journal.models.agenda import AgendaEntry


@dataclass
class DailySummaryJournalEntry:
    """A single journal's data prepared for the summary prompt."""

    title: str
    content: str
    types: list[str] = field(default_factory=list)
    contact_names: list[str] = field(default_factory=list)
    mood_value: int | None = None
    energy_level: int | None = None
    series_names: list[str] = field(default_factory=list)


@dataclass
class DailySummaryInput:
    """Aggregated input data for a single day's summary generation.

    Assembled by DailySummaryInputAssembler from repository data.

    ``agenda`` is the day's scheduled events — the same ``AgendaEntry`` the home
    dashboard's agenda card draws, reused rather than re-projected so the two
    surfaces cannot describe the same day differently. It is populated for the
    **current day only**: forward-looking material belongs to today, and a
    summary of last Tuesday describes last Tuesday.

    ``upcoming_tasks`` is the same rule again, over the commitments due in the
    week ahead. It carries the whole ``UpcomingTasks`` the dashboard's listing
    returns — the window travelling **beside** the tasks — rather than a bare
    list, because the prompt states which window it is describing and a caller
    that had to re-derive the span from the rows could not describe an empty one
    at all.

    ``None`` and an empty ``UpcomingTasks`` mean different things and the
    distinction is load-bearing: ``None`` is *not gathered* (the day is not
    today, so nothing was asked for), while a present-but-empty answer is
    *gathered, nothing due*. Only the second is a fact about the user's week.

    ``upcoming_dates`` is the third of the current day's forward-looking
    groups: the important contact dates falling in the **same seven days** the
    tasks window covers. It carries the whole ``UpcomingContactDates`` the
    dashboard's section and the ``list_upcoming_important_dates`` tool are
    answered with — window, occurrences and all — for the same reason
    ``upcoming_tasks`` does, and the same ``None``-versus-empty distinction
    applies. Nothing here re-derives recurrence: the occurrence, its derived
    years and the 29 February substitution are ``resolve_occurrence``'s answers,
    reached through the one service that asks it.

    ``past_day_tasks`` is the mirror image, and the **past day's only** input:
    the commitments due in this day's journals, each carrying how it resolved.
    It is populated for a day already behind the user's today and for no other,
    so it and ``upcoming_tasks`` can never both be present — a task due today
    would otherwise appear in two sections of one prompt. The same ``None``
    versus empty distinction applies, for the same reason.

    **The resolutions are current, not reconstructed.** Each model carries the
    task's status as it stands at generation time; nothing replays
    ``field_history`` to rebuild what was true on the day. So a past-day summary
    regenerated after a lapsed task was finally completed describes it as
    **done** — the honest answer to "what became of this", and the one that
    matches what the user sees on the journal.
    """

    user_id: str
    summary_date: date
    journals: list[DailySummaryJournalEntry] = field(default_factory=list)
    journal_count: int = 0
    event_count: int = 0
    contact_names: list[str] = field(default_factory=list)
    mood_values: list[int] = field(default_factory=list)
    previous_summary: str | None = None
    agenda: list[AgendaEntry] = field(default_factory=list)
    upcoming_tasks: UpcomingTasks | None = None
    upcoming_dates: UpcomingContactDates | None = None
    past_day_tasks: list[TaskReadModel] | None = None

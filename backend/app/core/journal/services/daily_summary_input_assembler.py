"""Input assembler for daily summary generation.

Gathers day-scoped data from repositories and assembles it into
a DailySummaryInput suitable for prompt building.

**The current day's agenda is read through the domain's own agenda port**
rather than through a query of this module's own. The summary and the home
dashboard are two renderings of one day, and a second implementation of "the
user's event journals on this local day" is the way they start disagreeing
about it.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from core_shared.models.contacts.entities import SummaryStatus

from app.core.journal.services.agenda import agenda_for_day
from app.core.journal.services.daily_summary_models import (
    DailySummaryInput,
    DailySummaryJournalEntry,
)
from app.core.journal.services.journal_date_resolver import today_in
from app.core.settings.timezone_utils import DEFAULT_TIMEZONE, resolve_timezone

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from app.core.journal.models.agenda import AgendaEntry
    from app.core.journal.models.repositories import (
        AgendaRepository,
        JournalContactRelationshipRepository,
        JournalRepository,
        JournalSeriesRepository,
        MoodDataRepository,
    )

    from .daily_summary_repository import JournalDailySummaryRepository

logger = logging.getLogger(__name__)


class DailySummaryInputAssembler:
    """Gathers journal data for a single day and assembles it for summary input."""

    def __init__(
        self,
        journal_repo: JournalRepository,
        mood_repo: MoodDataRepository,
        contact_relationship_repo: JournalContactRelationshipRepository,
        summary_repo: JournalDailySummaryRepository,
        series_repo: JournalSeriesRepository | None = None,
        agenda_repo: AgendaRepository | None = None,
    ) -> None:
        self._journal_repo = journal_repo
        self._mood_repo = mood_repo
        self._contact_relationship_repo = contact_relationship_repo
        self._summary_repo = summary_repo
        self._series_repo = series_repo
        self._agenda_repo = agenda_repo

    async def assemble(
        self,
        user_id: str,
        summary_date: date,
        timezone: str = DEFAULT_TIMEZONE,
        *,
        now: datetime | None = None,
    ) -> DailySummaryInput:
        """Assemble input data for a single day's summary.

        Fetches all journals for the given date, along with their types,
        contact relationships, and mood data. The day boundaries are computed
        in the user's ``timezone`` (then converted to UTC for the query) so the
        summary covers the user's local day rather than the UTC day.

        When ``summary_date`` is **today** in that timezone, the day's agenda is
        gathered too. It is not for any other day: forward-looking material
        belongs to the current day, and a past day should cost no extra read.

        ``now`` exists only so the local-midnight boundary can be pinned in
        tests, as ``DailySummaryFreshnessChecker``'s injectable clock is —
        defaulted, so no caller has to hold a clock to ask for a summary.
        """
        # Build the day's bounds in the user's timezone, then convert to UTC
        # for the (UTC-stored) query.
        tz = resolve_timezone(timezone)
        start_date = (
            datetime(
                summary_date.year,
                summary_date.month,
                summary_date.day,
                tzinfo=tz,
            )
            .astimezone(UTC)
            .isoformat()
        )
        end_date = (
            datetime(
                summary_date.year,
                summary_date.month,
                summary_date.day,
                23,
                59,
                59,
                tzinfo=tz,
            )
            .astimezone(UTC)
            .isoformat()
        )

        # Fetch journals for the day
        journals = await self._journal_repo.get_all(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
        )

        # Series membership per journal (one bulk lookup)
        series_names_by_journal: dict[int, list[str]] = {}
        journal_ids = [j.id for j in journals if j.id is not None]
        if self._series_repo is not None and journal_ids:
            series_names_by_journal = (
                await self._series_repo.get_series_names_for_journal_ids(
                    journal_ids, user_id
                )
            )

        # Assemble per-journal data
        entries: list[DailySummaryJournalEntry] = []
        all_contact_names: list[str] = []
        mood_values: list[int] = []
        event_count = 0

        for journal in journals:
            # Get types
            types: list[str] = []
            if hasattr(self._journal_repo, "get_types") and journal.id is not None:
                types = await self._journal_repo.get_types(journal.id)

            if "EVENT" in types:
                event_count += 1

            # Get contacts
            entry_contact_names: list[str] = []
            if journal.id is not None:
                rels = await self._contact_relationship_repo.get_by_journal(journal.id)
                for rel in rels:
                    name = getattr(rel, "contact_name", None)
                    if name:
                        entry_contact_names.append(name)
                        all_contact_names.append(name)

            # Get mood data
            mood_value: int | None = None
            energy_level: int | None = None
            if journal.id is not None:
                mood_data = await self._mood_repo.find_by_journal_id(journal.id)
                if mood_data:
                    mood_value = mood_data.mood_value
                    energy_level = mood_data.energy_level
                    if mood_value is not None:
                        mood_values.append(mood_value)

            entries.append(
                DailySummaryJournalEntry(
                    title=journal.title,
                    content=journal.content or "",
                    types=types,
                    contact_names=entry_contact_names,
                    mood_value=mood_value,
                    energy_level=energy_level,
                    series_names=(
                        series_names_by_journal.get(journal.id, [])
                        if journal.id is not None
                        else []
                    ),
                )
            )

        # Check for previous summary
        previous_summary: str | None = None
        existing = await self._summary_repo.find_by_user_and_date(user_id, summary_date)
        if existing and existing.status == SummaryStatus.GENERATED:
            previous_summary = existing.summary_text

        return DailySummaryInput(
            user_id=user_id,
            summary_date=summary_date,
            journals=entries,
            journal_count=len(journals),
            event_count=event_count,
            contact_names=all_contact_names,
            mood_values=mood_values,
            previous_summary=previous_summary,
            agenda=await self._agenda_for(user_id, summary_date, tz, now),
        )

    async def _agenda_for(
        self,
        user_id: str,
        summary_date: date,
        tz: ZoneInfo,
        now: datetime | None,
    ) -> list[AgendaEntry]:
        """The day's scheduled events, when the day is the user's today.

        Any other day reads nothing at all — not an empty window, no round trip
        — because the answer would be discarded: the prompt renders the agenda
        for the current day only.
        """
        if summary_date != today_in(tz, now):
            return []
        if self._agenda_repo is None:
            return []
        return list(await agenda_for_day(self._agenda_repo, user_id, summary_date, tz))

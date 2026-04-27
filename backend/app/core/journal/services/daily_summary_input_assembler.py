"""Input assembler for daily summary generation.

Gathers day-scoped data from repositories and assembles it into
a DailySummaryInput suitable for prompt building.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from core_shared.models.contacts.entities import SummaryStatus

from app.core.journal.services.daily_summary_models import (
    DailySummaryInput,
    DailySummaryJournalEntry,
)

if TYPE_CHECKING:
    from app.core.journal.models.repositories import (
        JournalContactRelationshipRepository,
        JournalRepository,
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
    ) -> None:
        self._journal_repo = journal_repo
        self._mood_repo = mood_repo
        self._contact_relationship_repo = contact_relationship_repo
        self._summary_repo = summary_repo

    async def assemble(self, user_id: str, summary_date: date) -> DailySummaryInput:
        """Assemble input data for a single day's summary.

        Fetches all journals for the given date, along with their types,
        contact relationships, and mood data.
        """
        # Build ISO date strings for the date range query
        start_date = datetime(
            summary_date.year,
            summary_date.month,
            summary_date.day,
            tzinfo=UTC,
        ).isoformat()
        end_date = datetime(
            summary_date.year,
            summary_date.month,
            summary_date.day,
            23,
            59,
            59,
            tzinfo=UTC,
        ).isoformat()

        # Fetch journals for the day
        journals = await self._journal_repo.get_all(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
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
        )

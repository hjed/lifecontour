"""Domain entity for journal daily summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from core_shared.models.contacts.entities import SummaryStatus


@dataclass
class JournalDailySummary:
    """AI-generated daily summary for a user's journals on a specific date.

    Provides a cached, read-only natural-language summary of what happened
    on a given day based on journal content and metadata.
    """

    user_id: str
    summary_date: date
    id: int | None = None
    summary_text: str | None = None
    journal_count: int = 0
    event_count: int = 0
    contact_count: int = 0
    mood_average: float | None = None
    status: SummaryStatus = SummaryStatus.PENDING
    generated_at: datetime | None = None
    #: When an input change last marked this day stale. A **change stamp**, not
    #: a staleness flag: staleness is derived from ``generated_at`` against the
    #: user's today. This is read with the row before its inputs are assembled
    #: and compared again when the result is written, so a generation whose
    #: inputs were gathered before an invalidation cannot overwrite the marker
    #: that invalidation left.
    invalidated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def get_display_text(self) -> str | None:
        """Get the text to display for this summary.

        Returns the summary text only when status is GENERATED.
        Returns None if summary is not yet generated, is disabled, or failed.
        """
        if self.status != SummaryStatus.GENERATED:
            return None
        return self.summary_text

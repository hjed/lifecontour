"""Adopt an existing journal for an instance of a split-off recurrence.

Google can answer a "this and following" edit by ending the old recurrence and
starting a new one under an unrelated id. The Google worker pairs the halves
(``integration_workers/google/split_adoption.py``) and sends the new instance
as an update of the old journal carrying ``split_adopted_from``, the old
recurrence's series key. Adopting it means:

1. **The series follows.** The new recurrence is folded into the series the
   old one resolves to, so its later instances join that series as ordinary
   creates instead of starting a duplicate one.
2. **The journal is re-pointed, not rewritten.** The ordinary update path
   moves the link to the new event and takes the new times and calendar info;
   the user's title and notes are kept, as the payload's are dropped.
3. **The old recurrence is re-planned.** The adopted journal leaves it, and the
   occurrence after the slot it left may now continue a cancelled run.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from core_shared.models.history import Provenance
from core_shared.models.journals import Journal
from core_shared.models.outbox_events import JournalSyncEventData

from app.core.integrations.adapters.sql.journal_event_link_repository import (
    SqlJournalEventLinkRepository,
)
from app.core.integrations.cancelled_recurrence_tidier import (
    CancelledRecurrenceTidier,
    TidyOutcome,
)
from app.core.integrations.recurrence_keys import root_recurring_event_id
from app.core.journal.models.repositories import JournalSeriesRepository


@dataclass(frozen=True)
class SplitAdoption:
    """Where the adopted journal sat in the old recurrence."""

    journal_id: int
    calendar_id: UUID
    old_recurring_event_id: str | None
    old_start: datetime | None


def adopted_journal_data(
    journal_data: dict[str, Any], journal: Journal
) -> dict[str, Any]:
    """The payload's journal data, keeping the adopted journal's title and notes.

    The worker sends the new event's description so a fallback create has one;
    an adoption never writes it over the journal's notes.
    """
    kept = {key: value for key, value in journal_data.items() if key != "content"}
    kept["title"] = journal.title
    return kept


class SplitAdopter:
    """Folds a split-off recurrence in, then re-plans the one it left."""

    def __init__(
        self,
        link_repo: SqlJournalEventLinkRepository,
        series_repo: JournalSeriesRepository,
        tidier: CancelledRecurrenceTidier,
    ) -> None:
        """Initialize over the processor's links, series and tidier."""
        self.link_repo = link_repo
        self.series_repo = series_repo
        self.tidier = tidier

    async def is_superseded(
        self, *, journal_id: int, calendar_id: UUID, payload: JournalSyncEventData
    ) -> bool:
        """Whether a later adoption has already moved this journal on.

        An adoption is delivered again after a newer one (the stream retries a
        failed delivery after newer events): the journal's link then belongs
        to neither the recurrence adopted from nor this event, and applying it
        would move the journal back.
        """
        current = await self.link_repo.find_by_journal(journal_id, calendar_id)
        if current is None or current.external_event_id == payload.external_event_id:
            return False
        if current.recurring_event_id is None:
            return False
        return root_recurring_event_id(current.recurring_event_id) != (
            payload.split_adopted_from
        )

    async def begin(
        self, *, journal: Journal, calendar_id: UUID, payload: JournalSyncEventData
    ) -> SplitAdoption:
        """Fold the new recurrence into the old series; note where the journal was.

        Call it before the update re-points the link, which is what moves the
        journal out of the old recurrence. The old recurrence is locked first,
        before anything is written, in the order the cancel handlers take it.
        """
        assert journal.id is not None
        old_link = await self.link_repo.find_by_journal(journal.id, calendar_id)
        if old_link is not None and old_link.recurring_event_id:
            await self.link_repo.lock_recurrence(
                calendar_id, old_link.recurring_event_id
            )
        new_key = payload.series_recurring_event_id or payload.recurring_event_id
        into_key = payload.split_adopted_from
        if new_key and into_key and new_key != into_key:
            await self.series_repo.adopt_recurrence(
                user_id=journal.user_id,
                calendar_id=calendar_id,
                recurring_event_id=new_key,
                into_recurring_event_id=into_key,
            )
        return SplitAdoption(
            journal_id=journal.id,
            calendar_id=calendar_id,
            old_recurring_event_id=old_link.recurring_event_id if old_link else None,
            old_start=old_link.event_date_range_start if old_link else None,
        )

    async def finish(
        self, adoption: SplitAdoption, *, source: Provenance, changed_by: str
    ) -> TidyOutcome | None:
        """Re-plan the old recurrence around the slot the journal left."""
        if adoption.old_recurring_event_id is None or adoption.old_start is None:
            return None
        return await self.tidier.tidy(
            calendar_id=adoption.calendar_id,
            recurring_event_id=adoption.old_recurring_event_id,
            source=source,
            changed_by=changed_by,
            left_slot=(adoption.old_start, adoption.journal_id),
        )

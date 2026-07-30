"""Read service for the incomplete outdoor activities review.

Composes the facts projection with the pure ``evaluate_incompleteness`` rules
and the dismissal store: a dismissed journal is excluded regardless of which
rules it matches, unless the caller opts in to seeing dismissed entries
(``include_dismissed``, used by the UI's un-dismiss affordance). Read-only —
no unit of work, matching ``LogbookDataService``.

Only activities that have **already started** are reviewed: a trip whose event
range begins after the end of today is a plan, not a gap in the logbook, so it
never reaches the rules. Like ``OutdoorDashboardService``, "today" ends at
midnight in the **user's configured timezone**
(``UserSettingsRepository.get_timezone``, UTC fallback) — an AEST user's day
does not end at UTC midnight. Activities already underway have started, so a
multi-day trip straddling today still counts.
"""

import dataclasses
import datetime
from zoneinfo import ZoneInfo

from core_shared.models.journals import (
    IncompleteOutdoorActivity,
    evaluate_incompleteness,
)

from app.core.journal.models.repositories import (
    IncompleteOutdoorActivityRepository,
    OutdoorActivityDismissalRepository,
)
from app.core.settings.models import UserSettingsRepository
from app.core.settings.timezone_utils import resolve_timezone


class IncompleteOutdoorActivityService:
    """Computes the incomplete outdoor activities list for a user."""

    def __init__(
        self,
        facts_repo: IncompleteOutdoorActivityRepository,
        dismissal_repo: OutdoorActivityDismissalRepository,
        user_settings_repo: UserSettingsRepository,
    ) -> None:
        self.facts_repo = facts_repo
        self.dismissal_repo = dismissal_repo
        self.user_settings_repo = user_settings_repo

    async def _user_timezone(self, user_id: str) -> ZoneInfo:
        """The user's configured timezone (UTC when unset or invalid)."""
        return resolve_timezone(await self.user_settings_repo.get_timezone(user_id))

    async def list_incomplete(
        self,
        user_id: str,
        include_dismissed: bool = False,
        anchor: datetime.date | None = None,
    ) -> list[IncompleteOutdoorActivity]:
        """The user's incomplete outdoor journals with reasons, newest first.

        Journals that have not started by the end of ``anchor`` (default: today
        in the user's timezone) are excluded — they are plans, not review items.
        Dismissed journals are excluded by default; with ``include_dismissed``
        they are returned alongside live entries, marked ``dismissed=True``.
        """
        tz = await self._user_timezone(user_id)
        anchor = anchor or datetime.datetime.now(tz).date()
        # ``time.max`` (23:59:59.999999) covers the final fractional second of
        # the anchor day, matching the dashboard's end-of-day bounds.
        started_by = datetime.datetime.combine(anchor, datetime.time.max, tz)

        facts = await self.facts_repo.list_outdoor_activity_facts(user_id)
        dismissed = await self.dismissal_repo.list_dismissed_journal_ids(user_id)
        results = [
            result
            if entry.journal_id not in dismissed
            else dataclasses.replace(result, dismissed=True)
            for entry in facts
            if entry.event_date_range.start <= started_by
            and (include_dismissed or entry.journal_id not in dismissed)
            and (result := evaluate_incompleteness(entry)) is not None
        ]
        # Newest first; -journal_id keeps ties deterministic (id ascending).
        results.sort(
            key=lambda result: (result.event_date_range.start, -result.journal_id),
            reverse=True,
        )
        return results

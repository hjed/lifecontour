"""Read service for the incomplete outdoor activities review.

Composes the facts projection with the pure ``evaluate_incompleteness`` rules
and the dismissal store: a dismissed journal is excluded regardless of which
rules it matches, unless the caller opts in to seeing dismissed entries
(``include_dismissed``, used by the UI's un-dismiss affordance). Read-only —
no unit of work, matching ``LogbookDataService``.
"""

import dataclasses

from core_shared.models.journals import (
    IncompleteOutdoorActivity,
    evaluate_incompleteness,
)

from app.core.journal.models.repositories import (
    IncompleteOutdoorActivityRepository,
    OutdoorActivityDismissalRepository,
)


class IncompleteOutdoorActivityService:
    """Computes the incomplete outdoor activities list for a user."""

    def __init__(
        self,
        facts_repo: IncompleteOutdoorActivityRepository,
        dismissal_repo: OutdoorActivityDismissalRepository,
    ) -> None:
        self.facts_repo = facts_repo
        self.dismissal_repo = dismissal_repo

    async def list_incomplete(
        self, user_id: str, include_dismissed: bool = False
    ) -> list[IncompleteOutdoorActivity]:
        """The user's incomplete outdoor journals with reasons, newest first.

        Dismissed journals are excluded by default; with ``include_dismissed``
        they are returned alongside live entries, marked ``dismissed=True``.
        """
        facts = await self.facts_repo.list_outdoor_activity_facts(user_id)
        dismissed = await self.dismissal_repo.list_dismissed_journal_ids(user_id)
        results = [
            result
            if entry.journal_id not in dismissed
            else dataclasses.replace(result, dismissed=True)
            for entry in facts
            if (include_dismissed or entry.journal_id not in dismissed)
            and (result := evaluate_incompleteness(entry)) is not None
        ]
        # Newest first; -journal_id keeps ties deterministic (id ascending).
        results.sort(
            key=lambda result: (result.event_date_range.start, -result.journal_id),
            reverse=True,
        )
        return results

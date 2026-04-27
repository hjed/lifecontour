"""Eligibility checker for daily summary generation.

Determines whether a day has enough substance to warrant
an AI-generated summary.
"""

from __future__ import annotations


class DailySummaryEligibilityChecker:
    """Determines if a day qualifies for summary generation.

    A day is eligible if it has at least ``min_journals`` journals.
    The product spec requires "multiple journals", so the default
    threshold is 2.
    """

    DEFAULT_MIN_JOURNALS = 2

    def __init__(self, min_journals: int | None = None) -> None:
        self._min_journals = (
            min_journals if min_journals is not None else self.DEFAULT_MIN_JOURNALS
        )

    def is_eligible(self, journal_count: int) -> bool:
        """Return True if the day has enough journals for a summary."""
        return journal_count >= self._min_journals

"""Eligibility checker for daily summary generation.

Determines whether a day has enough substance to warrant an AI-generated
summary — and singles out **today**, which always does.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

from app.core.journal.services.journal_date_resolver import today_in
from app.core.settings.timezone_utils import resolve_timezone


class DailySummaryEligibilityChecker:
    """Determines if a day qualifies for summary generation.

    **Today is always eligible**, whatever its journal count: a day with no
    journals but three tasks and a friend's birthday is exactly the day the
    user most needs a briefing for (Home Dashboard specification,
    *Extending the Daily Summary → Eligibility*). Every other day — past *or*
    future — needs at least ``min_journals`` journals, the "multiple journals"
    the journals specification asks for, so the default threshold is 2.

    "Today" is the current date in the caller's ``timezone`` — the user's
    configured zone — never UTC's date; near local midnight the two differ.
    ``clock`` is injectable so the boundary can be pinned in tests either
    side of local midnight.
    """

    DEFAULT_MIN_JOURNALS = 2

    def __init__(
        self,
        min_journals: int | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._min_journals = (
            min_journals if min_journals is not None else self.DEFAULT_MIN_JOURNALS
        )
        self._clock = clock if clock is not None else _utc_now

    def is_eligible(
        self,
        journal_count: int,
        *,
        summary_date: date,
        timezone: str | None,
    ) -> bool:
        """Whether ``summary_date`` qualifies for a summary.

        Today (in ``timezone``) always does; any other day needs enough
        journals.
        """
        if summary_date == today_in(resolve_timezone(timezone), self._clock()):
            return True
        return journal_count >= self._min_journals


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)

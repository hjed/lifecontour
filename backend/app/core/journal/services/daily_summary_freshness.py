"""Freshness rule for daily summaries — today's must have been generated today.

A summary produced yesterday evening is stale by the morning and must not be
served (Home Dashboard specification, *Extending the Daily Summary →
Freshness*). The rule singles out **today**: a past day's summary describes
that day and is kept however long ago it was written, and a future day is
simply not today yet.

Both halves of the comparison — which day is today, and which day the summary
was generated on — are read in the user's configured timezone, never UTC's,
through the same ``today_in`` / ``local_date`` pair the eligibility checker and
the home dashboard anchor on, so the three surfaces cannot disagree about when
the user's day starts.

Staleness is *derived* from ``generated_at`` rather than stored: nothing has to
be written for a summary to go stale at midnight. It sits beside, not instead
of, the explicit ``PENDING`` marker that input-driven invalidation sets — that
marker says "the inputs changed", this rule says "the day changed", and
``DailySummaryService.get_or_generate`` regenerates on either.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from app.core.journal.services.journal_date_resolver import local_date, today_in
from app.core.settings.timezone_utils import resolve_timezone

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from core_shared.models.journals.daily_summary import JournalDailySummary


def was_generated_on(summary: JournalDailySummary, day: date, tz: ZoneInfo) -> bool:
    """Whether ``summary`` was generated on ``day`` in ``tz``.

    A summary that never recorded when it was generated cannot prove it was
    generated on any day, so the answer is ``False``. The status is not
    consulted: whether a row may be *served* is the caller's rule — this only
    says *when* it was produced.
    """
    if summary.generated_at is None:
        return False
    return local_date(summary.generated_at, tz) == day


class DailySummaryFreshnessChecker:
    """Decides whether a cached summary is too old to serve.

    ``clock`` is injectable so the local-midnight boundary can be pinned in
    tests either side of it, mirroring ``DailySummaryEligibilityChecker``.
    """

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock if clock is not None else _utc_now

    def is_stale(
        self,
        summary: JournalDailySummary,
        *,
        timezone: str | None,
        now: datetime | None = None,
    ) -> bool:
        """Whether ``summary`` is today's and was not generated today.

        "Today" is the current date in ``timezone`` — the user's configured
        zone, falling back to UTC when unset or unknown. Any day other than
        today is never stale.

        ``now`` lets a caller impose the instant it has already read, so that
        every day-based decision in one request is made against one reading of
        the clock rather than four. Falls back to ``clock`` when none is given.
        """
        tz = resolve_timezone(timezone)
        moment = now if now is not None else self._clock()
        if summary.summary_date != today_in(tz, moment):
            return False
        return not was_generated_on(summary, summary.summary_date, tz)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)

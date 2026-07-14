"""Read service for the outdoor logbook dashboard.

Computes the upcoming-activities and activity-totals widgets from the
dashboard repository's windowed rows. Window arithmetic mirrors the journal
date-window browsing semantics — windows run from midnight on their first day
to end-of-day (``time.max``) on their last, compared with an overlap predicate so
multi-day trips straddling a boundary still count — but the boundaries (and
the default "today" anchor) are computed in the **user's configured
timezone** (``UserSettingsRepository.get_timezone``, UTC fallback), matching
``DailySummaryInputAssembler``: an AEST user's dashboard day starts at their
midnight, not UTC's. Read-only — no unit of work, matching
``IncompleteOutdoorActivityService``.

Also computes the checked-out-gear and templates-done widgets. Both compare
instants (the resolved checkout window is timestamped), so unlike the
windowed widgets they need no timezone anchoring; the determination and
grouping rules live in core_shared (``is_currently_checked_out`` /
``checked_out_gear`` / ``templates_done_by_type``) so they stay pure.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from core_shared.models.journals import (
    EventDateRange,
    OutdoorActivityTotals,
    checked_out_gear,
    effective_outdoor_journal_types,
    templates_done_by_type,
)

from app.core.settings.timezone_utils import resolve_timezone

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from core_shared.models.journals import (
        CheckedOutGearItem,
        TemplateDone,
        UpcomingOutdoorActivity,
    )

    from app.core.journal.models.repositories import OutdoorDashboardRepository
    from app.core.settings.models import UserSettingsRepository

UPCOMING_DAYS_FORWARD = 30
UPCOMING_CAP = 10
TOTALS_WINDOW_DAYS = (30, 365)


def _window(
    start_day: datetime.date, end_day: datetime.date, tz: ZoneInfo
) -> EventDateRange:
    """An inclusive window from midnight on ``start_day`` to end-of-day on ``end_day``, in ``tz``.

    ``time.max`` (23:59:59.999999) covers the final fractional second, like
    ``compute_search_window``'s full-day bounds — timestamps have microsecond
    precision, so nothing on ``end_day`` can fall past it.
    """
    return EventDateRange(
        start=datetime.datetime.combine(start_day, datetime.time.min, tz),
        end=datetime.datetime.combine(end_day, datetime.time.max, tz),
    )


class OutdoorDashboardService:
    """Computes the outdoor dashboard's upcoming and totals sections."""

    def __init__(
        self,
        dashboard_repo: OutdoorDashboardRepository,
        user_settings_repo: UserSettingsRepository,
    ) -> None:
        self.dashboard_repo = dashboard_repo
        self.user_settings_repo = user_settings_repo

    async def _user_timezone(self, user_id: str) -> ZoneInfo:
        """The user's configured timezone (UTC when unset or invalid)."""
        return resolve_timezone(await self.user_settings_repo.get_timezone(user_id))

    async def list_upcoming_activities(
        self, user_id: str, anchor: datetime.date | None = None
    ) -> list[UpcomingOutdoorActivity]:
        """The user's upcoming outdoor activities, soonest first, capped at 10.

        Outdoor journals and OUTDOOR_PLANNING events overlapping the next
        ``UPCOMING_DAYS_FORWARD`` days from ``anchor`` (default: today in the
        user's timezone, which also anchors the window boundaries).
        """
        tz = await self._user_timezone(user_id)
        anchor = anchor or datetime.datetime.now(tz).date()
        window = _window(
            anchor, anchor + datetime.timedelta(days=UPCOMING_DAYS_FORWARD), tz
        )
        upcoming = await self.dashboard_repo.list_upcoming_journals(
            user_id, window_start=window.start, window_end=window.end
        )
        upcoming.sort(
            key=lambda entry: (entry.event_date_range.start, entry.journal_id)
        )
        return upcoming[:UPCOMING_CAP]

    async def activity_totals(
        self, user_id: str, anchor: datetime.date | None = None
    ) -> OutdoorActivityTotals:
        """Outdoor activity counts by journal type over the rolling windows.

        A single repository fetch covers the widest window; each returned
        journal is bucketed into every ``TOTALS_WINDOW_DAYS`` window its date
        range overlaps and counted once per effective journal type. Windows
        end on ``anchor`` (default: today in the user's timezone).
        """
        tz = await self._user_timezone(user_id)
        anchor = anchor or datetime.datetime.now(tz).date()
        windows = {
            days: _window(anchor - datetime.timedelta(days=days), anchor, tz)
            for days in TOTALS_WINDOW_DAYS
        }
        facts = await self.dashboard_repo.list_outdoor_type_facts(
            user_id,
            window_start=windows[max(TOTALS_WINDOW_DAYS)].start,
            window_end=windows[max(TOTALS_WINDOW_DAYS)].end,
        )

        counts: dict[int, dict[str, int]] = {days: {} for days in TOTALS_WINDOW_DAYS}
        for entry in facts:
            journal_types = effective_outdoor_journal_types(entry.subtypes)
            for days, window in windows.items():
                if not entry.event_date_range.overlaps(window):
                    continue
                for journal_type in journal_types:
                    bucket = counts[days]
                    bucket[journal_type.value] = bucket.get(journal_type.value, 0) + 1

        return OutdoorActivityTotals(
            last_30_days=dict(sorted(counts[30].items())),
            last_365_days=dict(sorted(counts[365].items())),
        )

    async def list_checked_out_gear(
        self, user_id: str, now: datetime.datetime | None = None
    ) -> list[CheckedOutGearItem]:
        """The gear items currently checked out, longest-out first.

        Checked out ⇔ the resolved checkout window (buffer overrides falling
        back to the journal's event range) contains ``now`` and Snipe-IT
        hasn't already recorded the return. ``now`` is an instant, so no
        timezone anchoring is needed.
        """
        now = now or datetime.datetime.now(datetime.UTC)
        facts = await self.dashboard_repo.list_gear_checkout_facts(
            user_id, ending_after=now
        )
        return checked_out_gear(facts, now)

    async def templates_done(self, user_id: str) -> dict[str, list[TemplateDone]]:
        """Unique templates done with per-template counts, grouped by type."""
        references = await self.dashboard_repo.list_template_references(user_id)
        return templates_done_by_type(references)

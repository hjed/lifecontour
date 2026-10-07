"""Tests for the smart-sync window and the listing tracker (#1560)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core_shared.models.sync_job import SyncJob, SyncType

from snipeit_sync_window import (
    CURSOR_OVERLAP,
    FULL_RESYNC_INTERVAL,
    ListedRecord,
    ListingTracker,
    SyncWindow,
    resolve_sync_window,
)

_NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
_CURSOR = datetime(2026, 10, 7, 9, 30)  # Snipe-IT wall clock, naive


def _parent(
    *, cursor: str | None = "2026-10-07 09:30:00", completed_at: datetime = _NOW
) -> SyncJob:
    return SyncJob(
        job_id="p",
        user_id="u",
        integration_source="snipeit",
        sync_type="smart",
        status="completed",
        completed_at=completed_at,
        sync_resource="assets",
        sync_cursor=cursor,
    )


class TestResolveSyncWindow:
    def test_full_lists_everything_and_keeps_the_previous_cursor(self) -> None:
        window = resolve_sync_window(
            SyncType.FULL, last_completed=_parent(), last_full=None, now=_NOW
        )

        assert window == SyncWindow(
            since=None, sync_type=SyncType.FULL, previous_cursor=_CURSOR
        )

    def test_smart_starts_an_overlap_before_the_cursor(self) -> None:
        window = resolve_sync_window(
            SyncType.SMART,
            last_completed=_parent(),
            last_full=_parent(completed_at=_NOW - timedelta(days=1)),
            now=_NOW,
        )

        assert window == SyncWindow(
            since=_CURSOR - CURSOR_OVERLAP,
            sync_type=SyncType.SMART,
            previous_cursor=_CURSOR,
        )
        assert window.escalation is None

    def test_smart_without_a_completed_run_runs_as_full(self) -> None:
        window = resolve_sync_window(
            SyncType.SMART, last_completed=None, last_full=None, now=_NOW
        )

        assert (window.since, window.sync_type) == (None, SyncType.FULL)
        assert window.escalation == "no completed sync to resume from"

    def test_smart_without_a_cursor_runs_as_full(self) -> None:
        window = resolve_sync_window(
            SyncType.SMART,
            last_completed=_parent(cursor=None),
            last_full=_parent(cursor=None),
            now=_NOW,
        )

        assert (window.since, window.sync_type) == (None, SyncType.FULL)

    def test_smart_with_an_unparseable_cursor_runs_as_full(self) -> None:
        window = resolve_sync_window(
            SyncType.SMART,
            last_completed=_parent(cursor="garbage"),
            last_full=_parent(),
            now=_NOW,
        )

        assert window.sync_type == SyncType.FULL
        assert window.previous_cursor is None

    def test_smart_runs_as_full_when_no_full_run_completed(self) -> None:
        window = resolve_sync_window(
            SyncType.SMART, last_completed=_parent(), last_full=None, now=_NOW
        )

        assert (window.since, window.sync_type) == (None, SyncType.FULL)
        assert window.escalation == "no full sync completed in the last 7 days"

    def test_smart_runs_as_full_once_the_last_full_run_is_stale(self) -> None:
        stale = _parent(completed_at=_NOW - FULL_RESYNC_INTERVAL - timedelta(1))

        window = resolve_sync_window(
            SyncType.SMART, last_completed=_parent(), last_full=stale, now=_NOW
        )

        assert window.sync_type == SyncType.FULL
        assert window.previous_cursor == _CURSOR


class TestListingTracker:
    def test_full_window_selects_every_record(self) -> None:
        tracker = ListingTracker(
            SyncWindow(since=None, sync_type=SyncType.FULL, previous_cursor=None)
        )

        selected = tracker.select(
            [ListedRecord(1, datetime(2026, 1, 1)), ListedRecord(2, None)]
        )

        assert selected == [1, 2]

    def test_smart_window_selects_records_changed_since_inclusive(self) -> None:
        since = datetime(2026, 10, 7, 8, 30)
        tracker = ListingTracker(
            SyncWindow(since=since, sync_type=SyncType.SMART, previous_cursor=None)
        )

        selected = tracker.select(
            [
                ListedRecord(1, since - timedelta(seconds=1)),
                ListedRecord(2, since),
                ListedRecord(3, since + timedelta(hours=1)),
                ListedRecord(4, None),
            ]
        )

        assert selected == [2, 3, 4]
        assert tracker.listed_ids == [1, 2, 3, 4]

    def test_cursor_is_the_newest_change_seen(self) -> None:
        tracker = ListingTracker(
            SyncWindow(since=None, sync_type=SyncType.FULL, previous_cursor=None)
        )
        tracker.select([ListedRecord(1, datetime(2026, 10, 7, 9))])
        tracker.select(
            [ListedRecord(2, datetime(2026, 10, 7, 11, 5, 3)), ListedRecord(3, None)]
        )

        assert tracker.cursor == "2026-10-07 11:05:03"

    def test_cursor_carries_the_previous_one_forward(self) -> None:
        tracker = ListingTracker(
            SyncWindow(since=None, sync_type=SyncType.SMART, previous_cursor=_CURSOR)
        )
        tracker.select([ListedRecord(1, _CURSOR - timedelta(days=1))])

        assert tracker.cursor == "2026-10-07 09:30:00"

    def test_cursor_is_none_when_nothing_was_seen(self) -> None:
        tracker = ListingTracker(
            SyncWindow(since=None, sync_type=SyncType.FULL, previous_cursor=None)
        )

        assert tracker.cursor is None

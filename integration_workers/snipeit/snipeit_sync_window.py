"""Which Snipe-IT records a sync fetches (#1560).

A full sync fetches every listed record. A smart sync still lists every record,
which costs one call per page, but fetches only those whose ``updated_at`` is at
or after the last completed run's cursor, sparing a call per unchanged record.

The cursor is the newest ``updated_at`` a listing saw, in Snipe-IT's own naive
wall clock: comparing Snipe-IT's timestamps with each other needs neither the
instance's zone, which its API does not expose, nor agreement between clocks.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from core_shared.models.sync_job import SyncJob, SyncType

from snipeit_models import SNIPEIT_DATETIME_FORMAT, parse_wall_clock

SyncResource = Literal["assets", "maintenances"]

# How far before the cursor a smart sync starts. A record edited while the last
# listing ran can carry an ``updated_at`` older than a newer record that listing
# saw, and Snipe-IT's naive wall clock repeats an hour when daylight saving
# ends; an hour covers both. Fetching an unchanged record again costs one call,
# and its version hash then skips it.
CURSOR_OVERLAP = timedelta(hours=1)

# A smart sync runs as a full one when no full sync has completed for this long.
# ``updated_at`` misses some changes: renaming an asset's model or manufacturer
# does not touch the asset, a record can be skipped by offset paging while
# another is deleted, and a migration or transformer change can need every
# record re-imported.
FULL_RESYNC_INTERVAL = timedelta(days=7)


@dataclass(frozen=True)
class ListedRecord:
    """A record as a listing page returns it."""

    id: int
    updated_at: datetime | None


@dataclass(frozen=True)
class SyncWindow:
    """What one run fetches.

    Attributes:
        since: Fetch only records changed at or after this Snipe-IT wall-clock
            time, or every record when ``None``.
        sync_type: The type the run performs, full when a smart sync escalated.
        previous_cursor: The cursor the run starts from, carried forward when
            its own listing sees nothing newer.
        escalation: Why a smart sync runs as a full one, or ``None``.
    """

    since: datetime | None
    sync_type: SyncType
    previous_cursor: datetime | None
    escalation: str | None = field(default=None, compare=False)


def resolve_sync_window(
    requested: SyncType,
    *,
    last_completed: SyncJob | None,
    last_full: SyncJob | None,
    now: datetime,
    settings_changed_at: datetime | None = None,
) -> SyncWindow:
    """Work out what a run of the ``requested`` type fetches.

    Args:
        requested: The sync type the run was queued with.
        last_completed: The newest completed run for this user and resource.
        last_full: The newest completed full run for this user and resource.
        now: The current (aware) time.
        settings_changed_at: When the user's Snipe-IT settings or credentials
            last changed. A cursor is only good for the listing it came from:
            another URL is another clock, and another user mapping or API key
            can bring in records whose ``updated_at`` predates it.
    """
    cursor = parse_wall_clock(last_completed.sync_cursor) if last_completed else None
    if requested is SyncType.FULL:
        return SyncWindow(since=None, sync_type=SyncType.FULL, previous_cursor=cursor)

    if cursor is None:
        escalation = "no completed sync to resume from"
    elif _settings_changed_since(last_completed, settings_changed_at):
        escalation = "Snipe-IT settings changed since the last sync"
    elif (
        last_full is None
        or last_full.completed_at is None
        or now - last_full.completed_at > FULL_RESYNC_INTERVAL
    ):
        escalation = (
            f"no full sync completed in the last {FULL_RESYNC_INTERVAL.days} days"
        )
    else:
        return SyncWindow(
            since=cursor - CURSOR_OVERLAP,
            sync_type=SyncType.SMART,
            previous_cursor=cursor,
        )
    return SyncWindow(
        since=None,
        sync_type=SyncType.FULL,
        previous_cursor=cursor,
        escalation=escalation,
    )


def _settings_changed_since(
    run: SyncJob | None, settings_changed_at: datetime | None
) -> bool:
    """Whether the settings changed after ``run`` started listing."""
    if run is None or settings_changed_at is None:
        return False
    started = run.started_at or run.created_at
    return started is None or settings_changed_at > started


class ListingTracker:
    """Selects the records a run fetches and remembers what its listing saw."""

    def __init__(self, window: SyncWindow) -> None:
        self._since = window.since
        self._newest = window.previous_cursor
        self.listed_ids: list[int] = []

    def select(self, records: Iterable[ListedRecord]) -> list[int]:
        """Record a listing page and return the ids of the records to fetch.

        A record without a readable ``updated_at`` is always fetched.
        """
        selected: list[int] = []
        for record in records:
            self.listed_ids.append(record.id)
            stamp = record.updated_at
            if stamp is not None and (self._newest is None or stamp > self._newest):
                self._newest = stamp
            if self._since is None or stamp is None or stamp >= self._since:
                selected.append(record.id)
        return selected

    @property
    def cursor(self) -> str | None:
        """The newest change seen, formatted the way Snipe-IT writes it."""
        if self._newest is None:
            return None
        return self._newest.strftime(SNIPEIT_DATETIME_FORMAT)

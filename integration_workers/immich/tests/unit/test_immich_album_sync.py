"""Unit tests for Immich album sync helpers.

Covers album date-range derivation (timezone-aware day boundaries with a
per-photo EXIF timezone and UTC fallback) and album version hashing, which
drive ITER11-004 Phase 1 album import.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from immich_models import ImmichAlbum, ImmichAsset, ImmichExifInfo
from immich_sync_service import ImmichSyncService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asset(
    *,
    taken_at: datetime | None = None,
    exif_taken: datetime | None = None,
    timezone: str | None = None,
) -> ImmichAsset:
    exif = None
    if exif_taken is not None or timezone is not None:
        exif = ImmichExifInfo(date_time_original=exif_taken, timezone=timezone)
    return ImmichAsset(id="asset-1", taken_at=taken_at, exif_info=exif)


def _album(
    *,
    name: str = "Trip",
    description: str = "A trip",
    asset_count: int = 3,
    updated_at: datetime | None = None,
) -> ImmichAlbum:
    return ImmichAlbum(
        id="album-1",
        album_name=name,
        description=description,
        asset_count=asset_count,
        updated_at=updated_at,
    )


# ---------------------------------------------------------------------------
# derive_album_date_range
# ---------------------------------------------------------------------------


class TestDeriveAlbumDateRange:
    def test_empty_assets_returns_none(self) -> None:
        assert ImmichSyncService.derive_album_date_range([]) is None

    def test_assets_without_timestamps_returns_none(self) -> None:
        assert ImmichSyncService.derive_album_date_range([_asset()]) is None

    def test_earliest_and_latest_taken_at_define_day_boundaries(self) -> None:
        assets = [
            _asset(taken_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC)),
            _asset(taken_at=datetime(2026, 1, 17, 14, 30, tzinfo=UTC)),
            _asset(taken_at=datetime(2026, 1, 16, 8, 0, tzinfo=UTC)),
        ]

        result = ImmichSyncService.derive_album_date_range(assets)

        assert result is not None
        start, end = result
        # Day boundaries in UTC (no EXIF timezone present).
        assert start == datetime(2026, 1, 15, 0, 0, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 1, 17, 23, 59, 59, 999999, tzinfo=UTC)

    def test_single_photo_spans_its_whole_day(self) -> None:
        assets = [_asset(taken_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC))]

        start, end = ImmichSyncService.derive_album_date_range(assets)  # type: ignore[misc]

        assert start == datetime(2026, 3, 1, 0, 0, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 1, 23, 59, 59, 999999, tzinfo=UTC)

    def test_falls_back_to_exif_date_time_original(self) -> None:
        assets = [_asset(exif_taken=datetime(2026, 2, 2, 9, 0, tzinfo=UTC))]

        start, end = ImmichSyncService.derive_album_date_range(assets)  # type: ignore[misc]

        assert start.date() == datetime(2026, 2, 2).date()
        assert end.date() == datetime(2026, 2, 2).date()

    def test_uses_per_photo_exif_timezone_for_day_boundaries(self) -> None:
        # 23:00 UTC on 14 Jan is 10:00 on 15 Jan in AEDT (+11:00). The day
        # boundary must reflect the local day, not the UTC day.
        assets = [
            _asset(
                taken_at=datetime(2026, 1, 14, 23, 0, tzinfo=UTC),
                timezone="Australia/Sydney",
            )
        ]

        start, end = ImmichSyncService.derive_album_date_range(assets)  # type: ignore[misc]

        syd = ZoneInfo("Australia/Sydney")
        assert start == datetime(2026, 1, 15, 0, 0, 0, 0, tzinfo=syd)
        assert end == datetime(2026, 1, 15, 23, 59, 59, 999999, tzinfo=syd)

    def test_invalid_exif_timezone_falls_back_to_utc(self) -> None:
        assets = [
            _asset(
                taken_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
                timezone="Not/AZone",
            )
        ]

        start, end = ImmichSyncService.derive_album_date_range(assets)  # type: ignore[misc]

        assert start == datetime(2026, 1, 15, 0, 0, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 1, 15, 23, 59, 59, 999999, tzinfo=UTC)

    def test_naive_timestamp_is_treated_as_utc(self) -> None:
        assets = [_asset(taken_at=datetime(2026, 1, 15, 10, 0))]  # noqa: DTZ001

        start, end = ImmichSyncService.derive_album_date_range(assets)  # type: ignore[misc]

        assert start == datetime(2026, 1, 15, 0, 0, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 1, 15, 23, 59, 59, 999999, tzinfo=UTC)


# ---------------------------------------------------------------------------
# calculate_album_version_hash
# ---------------------------------------------------------------------------


class TestCalculateAlbumVersionHash:
    def test_hash_is_stable_for_identical_metadata(self) -> None:
        updated = datetime(2026, 1, 1, tzinfo=UTC)
        a = _album(updated_at=updated)
        b = _album(updated_at=updated)

        assert ImmichSyncService.calculate_album_version_hash(
            a
        ) == ImmichSyncService.calculate_album_version_hash(b)

    def test_hash_changes_when_name_changes(self) -> None:
        base = _album(name="Trip")
        changed = _album(name="Holiday")

        assert ImmichSyncService.calculate_album_version_hash(
            base
        ) != ImmichSyncService.calculate_album_version_hash(changed)

    def test_hash_changes_when_description_changes(self) -> None:
        base = _album(description="A trip")
        changed = _album(description="A long trip")

        assert ImmichSyncService.calculate_album_version_hash(
            base
        ) != ImmichSyncService.calculate_album_version_hash(changed)

    def test_hash_changes_when_asset_count_changes(self) -> None:
        base = _album(asset_count=3)
        changed = _album(asset_count=4)

        assert ImmichSyncService.calculate_album_version_hash(
            base
        ) != ImmichSyncService.calculate_album_version_hash(changed)

    def test_hash_changes_when_updated_at_changes(self) -> None:
        base = _album(updated_at=datetime(2026, 1, 1, tzinfo=UTC))
        changed = _album(updated_at=datetime(2026, 2, 1, tzinfo=UTC))

        assert ImmichSyncService.calculate_album_version_hash(
            base
        ) != ImmichSyncService.calculate_album_version_hash(changed)


# ---------------------------------------------------------------------------
# sync_albums — emits outbox events
# ---------------------------------------------------------------------------


def _extract_album_events(mock_connection: AsyncMock) -> list[dict[str, Any]]:
    """Extract immich_album outbox event payloads from execute calls."""
    events = []
    for call in mock_connection.execute.call_args_list:
        args = call[0]
        if len(args) >= 2 and isinstance(args[1], dict):
            params = args[1]
            if "event_type" in params and "event_data" in params:
                events.append(
                    {
                        "event_type": params["event_type"],
                        "event_data": json.loads(params["event_data"]),
                    }
                )
    return events


def _fetchone(result_row: MagicMock | None) -> MagicMock:
    result = MagicMock()
    result.fetchone.return_value = result_row
    return result


def _service(api: AsyncMock, conn: AsyncMock) -> ImmichSyncService:
    return ImmichSyncService(api_client=api, connection=conn, user_id="user-1")


def _full_album() -> ImmichAlbum:
    return ImmichAlbum(
        id="album-1",
        album_name="Trip",
        description="An album",
        asset_count=2,
        assets=[
            _asset(taken_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC)),
            _asset(taken_at=datetime(2026, 1, 16, 12, 0, tzinfo=UTC)),
        ],
        updated_at=datetime(2026, 1, 17, tzinfo=UTC),
    )


@pytest.mark.asyncio
class TestSyncAlbums:
    async def test_new_album_emits_created_event(self) -> None:
        api = AsyncMock()
        api.get_all_albums.return_value = [ImmichAlbum(id="album-1")]
        api.get_album.return_value = _full_album()
        conn = AsyncMock()
        # _find_album_sync_metadata → None (new); INSERT outbox → ignored result
        conn.execute.side_effect = [_fetchone(None), MagicMock()]

        result = await _service(api, conn).sync_albums()

        assert result.created == 1
        events = _extract_album_events(conn)
        assert len(events) == 1
        assert events[0]["event_type"] == "immich_album.created"
        data = events[0]["event_data"]
        assert data["external_id"] == "album-1"
        assert data["journal_data"]["title"] == "Trip"
        assert data["journal_data"]["event_date_range_start"].startswith("2026-01-15")

    async def test_changed_album_emits_updated_event(self) -> None:
        api = AsyncMock()
        api.get_all_albums.return_value = [ImmichAlbum(id="album-1")]
        api.get_album.return_value = _full_album()
        conn = AsyncMock()
        existing = MagicMock()
        existing.version_hash = "stale-hash"
        conn.execute.side_effect = [_fetchone(existing), MagicMock()]

        result = await _service(api, conn).sync_albums()

        assert result.updated == 1
        events = _extract_album_events(conn)
        assert events[0]["event_type"] == "immich_album.updated"

    async def test_unchanged_album_emits_no_event(self) -> None:
        api = AsyncMock()
        api.get_all_albums.return_value = [ImmichAlbum(id="album-1")]
        album = _full_album()
        api.get_album.return_value = album
        conn = AsyncMock()
        existing = MagicMock()
        existing.version_hash = ImmichSyncService.calculate_album_version_hash(album)
        conn.execute.side_effect = [_fetchone(existing)]

        result = await _service(api, conn).sync_albums()

        assert result.unchanged == 1
        assert _extract_album_events(conn) == []

"""Unit tests for ImmichAlbumOutboxEventProcessor pure logic.

Covers field merge protection (local-edit detection), journal building from
album payload data, and reference_data construction — without a database.
"""

from datetime import UTC, datetime

from core_shared.models.outbox_events import ImmichAlbumSyncEventData

from app.core.integrations.immich_album_outbox_event_processor import (
    ImmichAlbumOutboxEventProcessor,
)


class TestHasLocalEdits:
    """Merge-protection detection: journal.updated_at > link.updated_at."""

    def test_journal_edited_after_link_is_local_edit(self) -> None:
        link = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        journal = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
        assert ImmichAlbumOutboxEventProcessor._has_local_edits(journal, link) is True

    def test_journal_not_edited_since_sync_is_not_local_edit(self) -> None:
        link = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
        journal = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        assert ImmichAlbumOutboxEventProcessor._has_local_edits(journal, link) is False

    def test_equal_timestamps_are_not_local_edit(self) -> None:
        ts = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        assert ImmichAlbumOutboxEventProcessor._has_local_edits(ts, ts) is False

    def test_missing_link_timestamp_is_not_local_edit(self) -> None:
        journal = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        assert ImmichAlbumOutboxEventProcessor._has_local_edits(journal, None) is False


class TestBuildJournal:
    """Journal entity construction from album journal_data."""

    def test_builds_journal_with_event_date_range(self) -> None:
        journal_data = {
            "user_id": "user-1",
            "title": "Trip",
            "content": "An album",
            "event_date_range_start": "2026-01-15T00:00:00+00:00",
            "event_date_range_end": "2026-01-17T23:59:59+00:00",
        }
        journal = ImmichAlbumOutboxEventProcessor._build_journal(
            journal_data, journal_id=7
        )
        assert journal.id == 7
        assert journal.user_id == "user-1"
        assert journal.title == "Trip"
        assert journal.event_date_range.start == datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
        assert journal.event_date_range.end == datetime(
            2026, 1, 17, 23, 59, 59, tzinfo=UTC
        )


class TestReferenceData:
    """Album external reference display-metadata construction."""

    def _payload(self, **metadata: object) -> ImmichAlbumSyncEventData:
        return ImmichAlbumSyncEventData(
            external_id="album-1",
            version_hash="v1",
            sync_action="created",
            journal_data={
                "user_id": "u",
                "title": "t",
                "content": "",
                "event_date_range_start": "2026-01-15T00:00:00+00:00",
                "event_date_range_end": "2026-01-15T23:59:59+00:00",
            },
            album_metadata=dict(metadata),
            sync_timestamp=datetime.now(UTC).isoformat(),
        )

    def test_includes_album_id_and_present_metadata(self) -> None:
        payload = self._payload(album_name="Trip", asset_count=3)
        data = ImmichAlbumOutboxEventProcessor._reference_data(payload)
        assert data["album_id"] == "album-1"
        assert data["album_name"] == "Trip"
        assert data["asset_count"] == 3

    def test_omits_missing_metadata_fields(self) -> None:
        payload = self._payload(album_name="Trip")
        data = ImmichAlbumOutboxEventProcessor._reference_data(payload)
        assert "album_url" not in data
        assert "thumbnail_asset_id" not in data

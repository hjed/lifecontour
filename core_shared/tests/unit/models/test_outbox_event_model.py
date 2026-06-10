"""
Unit tests for ``OutboxEvent`` model factory methods.

Focused on ``create_immich_album_sync_event`` — the factory the Immich worker
uses to emit ``immich_album.*`` events through the typed model instead of raw
SQL. Validates the produced ``event_type`` / ``aggregate_id`` and that the
``event_data`` round-trips through ``ImmichAlbumSyncEventData``.
"""

from typing import Any, cast

import pytest

from core_shared.models.outbox import OutboxEvent
from core_shared.models.outbox_events import (
    ImmichAlbumSyncEventData,
    parse_outbox_event_data,
)


@pytest.fixture
def journal_data() -> dict[str, Any]:
    """Journal fields for an album sync event."""
    return {
        "user_id": "user-1",
        "title": "Trip to the coast",
        "content": "A weekend away",
        "event_date_range_start": "2025-01-01T12:00:00+00:00",
        "event_date_range_end": "2025-01-02T12:00:00+00:00",
    }


@pytest.fixture
def album_metadata() -> dict[str, Any]:
    """Album display + sync metadata."""
    return {
        "album_name": "Trip to the coast",
        "description": "A weekend away",
        "asset_count": 12,
        "people": [{"id": "p1", "name": "Alice"}],
    }


class TestCreateImmichAlbumSyncEvent:
    """Tests for ``OutboxEvent.create_immich_album_sync_event``."""

    def test_created_event_shape(
        self, journal_data: dict[str, Any], album_metadata: dict[str, Any]
    ) -> None:
        """A created event has the right type, default source and aggregate."""
        event = OutboxEvent.create_immich_album_sync_event(
            external_id="album-uuid-1",
            version_hash="hash-1",
            sync_action="created",
            journal_data=journal_data,
            album_metadata=album_metadata,
        )

        assert event.event_type == "immich_album.created"
        # No existing journal → aggregate_id falls back to 0.
        assert event.aggregate_id == 0
        assert event.event_data["integration_source"] == "immich_album"
        assert event.event_data["external_id"] == "album-uuid-1"
        assert event.event_data["sync_action"] == "created"
        assert "sync_timestamp" in event.event_data

    def test_updated_event_uses_existing_journal_id_as_aggregate(
        self, journal_data: dict[str, Any], album_metadata: dict[str, Any]
    ) -> None:
        """An updated event carries the existing journal id as aggregate_id."""
        event = OutboxEvent.create_immich_album_sync_event(
            external_id="album-uuid-2",
            version_hash="hash-2",
            sync_action="updated",
            journal_data=journal_data,
            album_metadata=album_metadata,
            existing_journal_id=77,
        )

        assert event.event_type == "immich_album.updated"
        assert event.aggregate_id == 77
        assert event.event_data["existing_journal_id"] == 77

    def test_event_data_round_trips_through_payload_model(
        self, journal_data: dict[str, Any], album_metadata: dict[str, Any]
    ) -> None:
        """The serialized payload validates against ImmichAlbumSyncEventData."""
        event = OutboxEvent.create_immich_album_sync_event(
            external_id="album-uuid-3",
            version_hash="hash-3",
            sync_action="created",
            journal_data=journal_data,
            album_metadata=album_metadata,
        )

        parsed = parse_outbox_event_data(
            cast(str, event.event_type), cast("dict[str, Any]", event.event_data)
        )
        assert isinstance(parsed, ImmichAlbumSyncEventData)
        assert parsed.external_id == "album-uuid-3"
        assert parsed.version_hash == "hash-3"
        assert parsed.album_metadata["asset_count"] == 12

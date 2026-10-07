"""
Integration tests for ImmichSyncService outbox-event emission.

These exercise the real ``INSERT INTO outbox_events`` through asyncpg for
every Immich sync flow that emits an event (contact created/updated/linked,
album created/updated). The unit tests mock the DB connection, so they never
run asyncpg's parameter encoder — which is exactly where the regression lived:
the worker passed a timezone-aware ``datetime`` into the physically
``TIMESTAMP WITHOUT TIME ZONE`` ``occurred_at`` / ``created_at`` columns via a
raw ``text()`` INSERT, and asyncpg rejected it with::

    invalid input for query argument ...
    (can't subtract offset-naive and offset-aware datetimes)

Emitting through the typed ``OutboxEvent`` model (as the Google worker does)
fixes it; these tests fail against the old raw-SQL path and pass after.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text

from immich_models import ImmichAlbum, ImmichAsset, ImmichAssetPerson
from immich_sync_service import ImmichSyncService

USER_ID = "test-user-outbox"


@dataclass
class OutboxRow:
    """A persisted outbox_events row with ``event_data`` decoded from JSON text."""

    event_id: str
    event_type: str
    aggregate_id: int
    event_data: dict[str, Any]
    occurred_at: datetime
    created_at: datetime


@pytest.fixture
def sync_service(async_connection: Any) -> ImmichSyncService:
    """Build a sync service bound to the real test connection.

    The API client is an ``AsyncMock``; people-sync tests feed person dicts
    directly and never touch the API, while album-sync tests configure the
    relevant API methods explicitly.
    """
    return ImmichSyncService(
        api_client=AsyncMock(),
        connection=async_connection,
        user_id=USER_ID,
        integration_source="immich",
        server_url="https://immich.example.com",
    )


async def _fetch_outbox_rows(
    connection: Any, event_type: str, external_id: str
) -> list[OutboxRow]:
    """Return outbox_events rows for an (event_type, external_id) pair.

    ``event_data`` is stored as JSON text, so it is decoded here — which also
    asserts the persisted value is valid JSON the OutboxRelay can consume.
    """
    result = await connection.execute(
        text("""
            SELECT event_id, event_type, aggregate_id, event_data,
                   occurred_at, created_at
            FROM outbox_events
            WHERE event_type = :event_type
        """),
        {"event_type": event_type},
    )
    rows = [
        OutboxRow(
            event_id=row.event_id,
            event_type=row.event_type,
            aggregate_id=row.aggregate_id,
            event_data=json.loads(row.event_data),
            occurred_at=row.occurred_at,
            created_at=row.created_at,
        )
        for row in result.fetchall()
    ]
    return [r for r in rows if r.event_data.get("external_id") == external_id]


def _person_dict(
    person_id: str, name: str, birth_date: str | None = None
) -> dict[str, Any]:
    """Serialized ImmichPerson payload as ``sync_people_batch`` expects it."""
    return {
        "id": person_id,
        "name": name,
        "birthDate": birth_date,
        "isHidden": False,
    }


def _album(album_id: str, name: str, description: str = "") -> ImmichAlbum:
    """Build an ImmichAlbum with one dated, people-tagged asset."""
    return ImmichAlbum(
        id=album_id,
        album_name=name,
        description=description,
        asset_count=1,
        album_thumbnail_asset_id="thumb-1",
        updated_at=datetime(2025, 1, 2, 9, 0, tzinfo=UTC),
        assets=[
            ImmichAsset(
                id="asset-1",
                taken_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
                people=[ImmichAssetPerson(id="person-1", name="Alice")],
            )
        ],
    )


class TestContactOutboxEmission:
    """Real-database tests for ``_emit_outbox_event`` via ``sync_people_batch``."""

    @pytest.mark.asyncio
    async def test_sync_people_batch_emits_contact_created_event(
        self, sync_service: ImmichSyncService, async_connection: Any
    ) -> None:
        """An unmatched person produces exactly one ``contact.created`` row.

        Direct reproduction of the reported bug: before the fix this raises an
        asyncpg ``DataError`` that ``sync_people_batch`` swallows into
        ``result.errors``, leaving zero outbox rows.
        """
        person_id = "11111111-1111-4111-8111-111111111111"
        people = [_person_dict(person_id, "Zane Uniquesson")]

        result = await sync_service.sync_people_batch(people)

        assert result.errors == 0, result.error_details
        assert result.created == 1

        rows = await _fetch_outbox_rows(async_connection, "contact.created", person_id)
        assert len(rows) == 1
        row = rows[0]
        assert row.event_data["integration_source"] == "immich"
        assert row.event_data["sync_type"] == "created"
        # The event and its contact both name the syncing user as owner.
        assert row.event_data["user_id"] == USER_ID
        assert row.event_data["contact_data"]["user_id"] == USER_ID
        # Timestamps round-trip through the real (naive) columns.
        assert row.occurred_at is not None
        assert row.created_at is not None

    @pytest.mark.asyncio
    async def test_sync_people_batch_emits_contact_updated_when_version_changed(
        self, sync_service: ImmichSyncService, async_connection: Any
    ) -> None:
        """A linked person with a stale version hash yields ``contact.updated``."""
        person_id = "22222222-2222-4222-8222-222222222222"
        contact_id = await seed_contact(
            async_connection, first_name="Existing", last_name="Person", user_id=USER_ID
        )

        # Link the person via the canonical sync_metadata store with a *different*
        # hash so the next sync detects a change.
        await sync_service._upsert_sync_metadata(
            external_id=person_id,
            internal_id=contact_id,
            version_hash="stale-hash-that-will-not-match",
        )

        result = await sync_service.sync_people_batch(
            [_person_dict(person_id, "Existing Person")]
        )

        assert result.errors == 0, result.error_details
        assert result.updated == 1

        rows = await _fetch_outbox_rows(async_connection, "contact.updated", person_id)
        assert len(rows) == 1
        assert rows[0].event_data["sync_type"] == "updated"

    @pytest.mark.asyncio
    async def test_sync_people_batch_links_and_emits_contact_updated_on_name_match(
        self, sync_service: ImmichSyncService, async_connection: Any
    ) -> None:
        """A single name match auto-links and emits ``contact.updated``."""
        person_id = "33333333-3333-4333-8333-333333333333"
        contact_id = await seed_contact(
            async_connection, first_name="Linkable", last_name="Match", user_id=USER_ID
        )

        result = await sync_service.sync_people_batch(
            [_person_dict(person_id, "Linkable Match")]
        )

        assert result.errors == 0, result.error_details
        assert result.linked == 1

        # The external reference was created for the matched contact.
        ref = await sync_service._find_external_reference(person_id)
        assert ref is not None
        assert ref.internal_entity_id == contact_id

        rows = await _fetch_outbox_rows(async_connection, "contact.updated", person_id)
        assert len(rows) == 1


def _album_sync_service(connection: Any, album: ImmichAlbum) -> ImmichSyncService:
    """Sync service whose mock API returns a single album and no shared links.

    The API client is typed ``Any`` so its async methods can be configured
    without mypy flagging method assignment.
    """
    api: Any = AsyncMock()
    api.get_shared_links.return_value = []
    api.get_album.return_value = album
    return ImmichSyncService(
        api_client=api,
        connection=connection,
        user_id=USER_ID,
        integration_source="immich",
        server_url="https://immich.example.com",
    )


class TestAlbumOutboxEmission:
    """Real-database tests for ``_emit_album_outbox_event`` via batch sync."""

    @pytest.mark.asyncio
    async def test_sync_albums_batch_emits_album_created_event(
        self, async_connection: Any
    ) -> None:
        """A new album produces exactly one ``immich_album.created`` row."""
        album_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        service = _album_sync_service(
            async_connection, _album(album_id, "Trip to the coast")
        )

        result = await service.sync_albums_batch([album_id])

        assert result.errors == 0, result.error_details
        assert result.created == 1

        rows = await _fetch_outbox_rows(
            async_connection, "immich_album.created", album_id
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.event_data["integration_source"] == "immich_album"
        assert row.event_data["sync_action"] == "created"
        assert row.event_data["journal_data"]["title"] == "Trip to the coast"
        assert row.occurred_at is not None
        assert row.created_at is not None

    @pytest.mark.asyncio
    async def test_sync_albums_batch_emits_album_updated_when_metadata_changed(
        self, async_connection: Any
    ) -> None:
        """An album with a stale version hash yields ``immich_album.updated``."""
        album_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

        # Seed album sync metadata under the album integration source with a
        # hash that won't match the freshly computed one.
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (internal_id, integration_source, external_id,
                     last_synced_at, version_hash, sync_status,
                     retry_count, created_at, updated_at)
                VALUES
                    (0, 'immich_album', :external_id,
                     NOW(), 'stale-album-hash', 'success',
                     0, NOW(), NOW())
            """),
            {"external_id": album_id},
        )

        service = _album_sync_service(
            async_connection, _album(album_id, "Updated album")
        )

        result = await service.sync_albums_batch([album_id])

        assert result.errors == 0, result.error_details
        assert result.updated == 1

        rows = await _fetch_outbox_rows(
            async_connection, "immich_album.updated", album_id
        )
        assert len(rows) == 1
        assert rows[0].event_data["sync_action"] == "updated"

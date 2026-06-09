"""Integration tests for the Immich album-creation REST endpoints (ITER11-006).

Exercises ``POST /search-photos``, ``POST /create-album`` and the asset
thumbnail proxy end-to-end over HTTP, with the Immich server stubbed via respx
and credentials patched (so no encryption setup is needed). Album-creation
writes are asserted against the real test database, including that the journal
becomes a PHOTO_ALBUM.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

USER_ID = "test-user-123"
SERVER_URL = "https://immich.example.com"
CREDS = (SERVER_URL, "test-api-key")
_GET_CREDS = (
    "app.infrastructure.auth.immich_token_service.ImmichTokenService.get_credentials"
)


async def _seed_journal(connection: AsyncConnection, *, user_id: str = USER_ID) -> int:
    journal_id = (
        await connection.execute(
            text("""
                INSERT INTO journals
                    (user_id, title, content,
                     event_date_range_start, event_date_range_end,
                     created_at, updated_at)
                VALUES (:u, 'Trip', '',
                        '2026-01-15T00:00:00+00:00', '2026-01-15T23:59:59+00:00',
                        now(), now())
                RETURNING id
            """),
            {"u": user_id},
        )
    ).scalar_one()
    return int(journal_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_photos_returns_photos_with_proxy_urls(
    authenticated_client,
    clean_database: AsyncConnection,
    respx_mock,
) -> None:
    journal_id = await _seed_journal(clean_database)
    respx_mock.post(f"{SERVER_URL}/api/search/metadata").mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": {
                    "items": [
                        {"id": "asset-1", "originalFileName": "a.jpg"},
                        {"id": "asset-2", "originalFileName": "b.jpg"},
                    ]
                }
            },
        )
    )

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=CREDS):
        response = await authenticated_client.post(
            "/api/integrations/immich/search-photos",
            json={"journal_id": journal_id},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["count"] == 2
    ids = [p["id"] for p in body["data"]]
    assert ids == ["asset-1", "asset-2"]
    assert (
        body["data"][0]["attributes"]["thumbnailUrl"]
        == "/api/integrations/immich/assets/asset-1/thumbnail"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_photos_404_for_other_users_journal(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    journal_id = await _seed_journal(clean_database, user_id="someone-else")

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=CREDS):
        response = await authenticated_client.post(
            "/api/integrations/immich/search-photos",
            json={"journal_id": journal_id},
        )

    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_photos_400_when_not_connected(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    journal_id = await _seed_journal(clean_database)

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=(None, None)):
        response = await authenticated_client.post(
            "/api/integrations/immich/search-photos",
            json={"journal_id": journal_id},
        )

    assert response.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_album_links_journal_and_marks_photo_album(
    authenticated_client,
    clean_database: AsyncConnection,
    respx_mock,
) -> None:
    journal_id = await _seed_journal(clean_database)
    respx_mock.post(f"{SERVER_URL}/api/albums").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "album-uuid-1",
                "albumName": "Trip",
                "assetCount": 2,
                "albumThumbnailAssetId": "asset-1",
            },
        )
    )

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=CREDS):
        response = await authenticated_client.post(
            "/api/integrations/immich/create-album",
            json={
                "journal_id": journal_id,
                "asset_ids": ["asset-1", "asset-2"],
                "create_shared_link": False,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["id"] == "album-uuid-1"
    assert body["data"]["attributes"]["assetCount"] == 2
    assert body["data"]["attributes"]["sharedLinkUrl"] is None

    # SyncMetadata links journal -> album with the album source.
    sm = (
        await clean_database.execute(
            text("""
                SELECT external_id, internal_id FROM sync_metadata
                WHERE internal_id = :jid AND integration_source = 'immich_album'
            """),
            {"jid": journal_id},
        )
    ).fetchone()
    assert sm is not None
    assert sm.external_id == "album-uuid-1"

    # ExternalReference records the album link with display metadata.
    ref = (
        await clean_database.execute(
            text("""
                SELECT reference_data FROM external_references
                WHERE internal_entity_id = :jid
                  AND external_system = 'immich'
                  AND external_entity_type = 'album'
            """),
            {"jid": journal_id},
        )
    ).fetchone()
    assert ref is not None
    reference_data = json.loads(ref.reference_data)
    assert reference_data["album_url"] == f"{SERVER_URL}/albums/album-uuid-1"

    # The journal is now a PHOTO_ALBUM (derived from the sync_metadata row).
    from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

    types = await SqlJournalRepository(clean_database).get_types(journal_id)
    assert "PHOTO_ALBUM" in types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_album_with_shared_link_persists_url(
    authenticated_client,
    clean_database: AsyncConnection,
    respx_mock,
) -> None:
    journal_id = await _seed_journal(clean_database)
    respx_mock.post(f"{SERVER_URL}/api/albums").mock(
        return_value=httpx.Response(
            201, json={"id": "album-uuid-2", "albumName": "Trip", "assetCount": 1}
        )
    )
    respx_mock.post(f"{SERVER_URL}/api/shared-links").mock(
        return_value=httpx.Response(201, json={"id": "link-1", "key": "sharekey"})
    )

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=CREDS):
        response = await authenticated_client.post(
            "/api/integrations/immich/create-album",
            json={
                "journal_id": journal_id,
                "asset_ids": ["asset-1"],
                "create_shared_link": True,
            },
        )

    assert response.status_code == 200
    assert (
        response.json()["data"]["attributes"]["sharedLinkUrl"]
        == f"{SERVER_URL}/share/sharekey"
    )

    ref = (
        await clean_database.execute(
            text("""
                SELECT reference_data FROM external_references
                WHERE internal_entity_id = :jid
                  AND external_entity_type = 'album'
            """),
            {"jid": journal_id},
        )
    ).fetchone()
    assert ref is not None
    assert json.loads(ref.reference_data)["shared_link_url"] == (
        f"{SERVER_URL}/share/sharekey"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_album_409_when_already_linked(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    from app.core.integrations.adapters.sql.sync_metadata_repository import (
        SyncMetadataRepository,
    )
    from app.core.journal.adapters.sql.album_sync_read_repository import (
        AlbumSyncReadRepository,
    )

    journal_id = await _seed_journal(clean_database)
    # Pre-link the journal to an existing album.
    await SyncMetadataRepository(clean_database).upsert(
        integration_source="immich_album",
        external_id="existing-album",
        version_hash="v1",
        internal_id=journal_id,
    )
    await AlbumSyncReadRepository(clean_database).upsert_link(
        journal_id, "existing-album", {"album_id": "existing-album"}, bump_anchor=True
    )

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=CREDS):
        response = await authenticated_client.post(
            "/api/integrations/immich/create-album",
            json={
                "journal_id": journal_id,
                "asset_ids": ["asset-1"],
                "create_shared_link": False,
            },
        )

    assert response.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_asset_thumbnail_proxy_returns_bytes(
    authenticated_client,
    clean_database: AsyncConnection,
    respx_mock,
) -> None:
    respx_mock.get(f"{SERVER_URL}/api/assets/asset-9/thumbnail").mock(
        return_value=httpx.Response(
            200, content=b"\xff\xd8\xff\xe0jpeg", headers={"content-type": "image/jpeg"}
        )
    )

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=CREDS):
        response = await authenticated_client.get(
            "/api/integrations/immich/assets/asset-9/thumbnail"
        )

    assert response.status_code == 200
    assert response.content == b"\xff\xd8\xff\xe0jpeg"
    assert response.headers["content-type"] == "image/jpeg"

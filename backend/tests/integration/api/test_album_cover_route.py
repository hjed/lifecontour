"""Integration tests for the journal album-cover proxy route.

Validates ``GET /api/journals/{id}/album-cover``: it streams the album cover
bytes for a PHOTO_ALBUM journal (with Immich credentials + a cover asset) and
returns 404 for non-album journals or albums without a cover.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.immich.album_outbox_event_processor import (
    EVENT_TYPE_IMMICH_ALBUM_CREATED,
    ImmichAlbumOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

USER_ID = "test-user-123"
_CREDS = ("https://immich.example.com", "test-api-key")


async def _create_album_journal(
    connection: AsyncConnection, *, thumbnail_asset_id: str | None
) -> int:
    """Seed a PHOTO_ALBUM journal via the processor and return its id."""
    service = JournalService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(connection),
    )
    processor = ImmichAlbumOutboxEventProcessor(
        journal_service=service, connection=connection
    )
    album_metadata: dict[str, object] = {"album_name": "Trip", "asset_count": 2}
    if thumbnail_asset_id is not None:
        album_metadata["thumbnail_asset_id"] = thumbnail_asset_id

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TYPE_IMMICH_ALBUM_CREATED,
        aggregate_id="0",
        event_data={
            "integration_source": "immich_album",
            "external_id": str(uuid.uuid4()),
            "version_hash": "v1",
            "sync_action": "created",
            "journal_data": {
                "user_id": USER_ID,
                "title": "Trip",
                "content": "",
                "event_date_range_start": "2026-01-15T00:00:00+00:00",
                "event_date_range_end": "2026-01-15T23:59:59+00:00",
            },
            "album_metadata": album_metadata,
            "sync_timestamp": datetime.now(UTC).isoformat(),
        },
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )
    result = await processor.process_event(event)
    return int(result["journal_id"])


@pytest.mark.asyncio
async def test_album_cover_returns_image_bytes(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    journal_id = await _create_album_journal(
        clean_database, thumbnail_asset_id="asset-uuid"
    )

    with (
        patch(
            "app.infrastructure.auth.immich_token_service.ImmichTokenService.get_credentials",
            new_callable=AsyncMock,
            return_value=_CREDS,
        ),
        patch(
            "app.core.integrations.immich.album_cover_proxy_service.AlbumCoverProxyService._fetch_thumbnail",
            new_callable=AsyncMock,
            return_value=(b"\xff\xd8\xff\xe0jpeg", "image/jpeg"),
        ),
    ):
        response = await authenticated_client.get(
            f"/api/journals/{journal_id}/album-cover"
        )

    assert response.status_code == 200
    assert response.content == b"\xff\xd8\xff\xe0jpeg"
    assert response.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_album_cover_404_for_non_album_journal(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    journal_id = (
        await clean_database.execute(
            text("""
                INSERT INTO journals
                    (user_id, title, content,
                     event_date_range_start, event_date_range_end,
                     created_at, updated_at)
                VALUES (:u, 'Plain', '',
                        '2026-01-15T00:00:00+00:00', '2026-01-15T23:59:59+00:00',
                        now(), now())
                RETURNING id
            """),
            {"u": USER_ID},
        )
    ).scalar()

    response = await authenticated_client.get(f"/api/journals/{journal_id}/album-cover")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_album_cover_404_when_album_has_no_cover_asset(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    journal_id = await _create_album_journal(clean_database, thumbnail_asset_id=None)

    with patch(
        "app.infrastructure.auth.immich_token_service.ImmichTokenService.get_credentials",
        new_callable=AsyncMock,
        return_value=_CREDS,
    ):
        response = await authenticated_client.get(
            f"/api/journals/{journal_id}/album-cover"
        )

    assert response.status_code == 404

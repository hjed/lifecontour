"""Integration tests for AlbumSyncReadRepository.

Verifies PHOTO_ALBUM type data is read from sync_metadata + external_references,
and that a malformed reference_data row degrades gracefully instead of 500ing.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import EventDateRange, Journal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

USER_ID = "album-read-user"


@pytest_asyncio.fixture
async def repo(async_connection: AsyncConnection) -> AlbumSyncReadRepository:
    return AlbumSyncReadRepository(async_connection)


async def _make_album_journal(
    connection: AsyncConnection, *, album_id: str, reference_data: str | None
) -> int:
    now = datetime.now(UTC)
    journal = Journal(
        user_id=USER_ID,
        title="Album",
        content="content",
        event_date_range=EventDateRange(start=now, end=now + timedelta(hours=1)),
    )
    saved = await SqlJournalRepository(connection).save(journal)
    assert saved.id is not None

    await connection.execute(
        text("""
            INSERT INTO sync_metadata (
                internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status
            ) VALUES (
                :internal_id, 'immich_album', :external_id, now(), 'h', 'success'
            )
        """),
        {"internal_id": saved.id, "external_id": album_id},
    )
    await connection.execute(
        text("""
            INSERT INTO external_references (
                internal_entity_type, internal_entity_id, external_system,
                external_entity_type, external_entity_id, reference_data,
                created_at, updated_at
            ) VALUES (
                'journal', :internal_id, 'immich', 'album', :external_id,
                :reference_data, now(), now()
            )
        """),
        {
            "internal_id": saved.id,
            "external_id": album_id,
            "reference_data": reference_data,
        },
    )
    return saved.id


@pytest.mark.integration
class TestAlbumSyncReadRepository:
    async def test_returns_album_display_data(
        self, repo: AlbumSyncReadRepository, async_connection: AsyncConnection
    ):
        journal_id = await _make_album_journal(
            async_connection,
            album_id="album-good",
            reference_data='{"album_name": "Summer Trip", "asset_count": 9}',
        )

        data = await repo.find_by_journal_id(journal_id)

        assert data is not None
        assert data["immich_album_id"] == "album-good"
        assert data["album_name"] == "Summer Trip"
        assert data["asset_count"] == 9

    async def test_malformed_reference_data_degrades_gracefully(
        self, repo: AlbumSyncReadRepository, async_connection: AsyncConnection
    ):
        journal_id = await _make_album_journal(
            async_connection,
            album_id="album-bad",
            reference_data="{ this is not valid json",
        )

        data = await repo.find_by_journal_id(journal_id)

        # No crash; the bare album id is still returned.
        assert data is not None
        assert data["immich_album_id"] == "album-bad"
        assert "album_name" not in data

    async def test_non_album_journal_returns_none(
        self, repo: AlbumSyncReadRepository, async_connection: AsyncConnection
    ):
        now = datetime.now(UTC)
        saved = await SqlJournalRepository(async_connection).save(
            Journal(
                user_id=USER_ID,
                title="Plain",
                content="c",
                event_date_range=EventDateRange(start=now, end=now),
            )
        )
        assert saved.id is not None

        assert await repo.find_by_journal_id(saved.id) is None

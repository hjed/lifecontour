"""Integration tests for AlbumSyncReadRepository.

Verifies PHOTO_ALBUM type data is read from sync_metadata + external_references,
that a malformed reference_data row degrades gracefully instead of 500ing, and
that ``upsert_link`` dual-writes the album ``reference_data`` onto sync_metadata.
"""

import json
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


async def _make_album_sync_metadata_only(
    connection: AsyncConnection, *, album_id: str
) -> int:
    """Seed a journal + immich_album sync_metadata row with NULL reference_data.

    Mirrors what the album outbox processor writes before it calls
    ``upsert_link`` (the sync_metadata row exists; reference_data is not yet set).
    """
    now = datetime.now(UTC)
    saved = await SqlJournalRepository(connection).save(
        Journal(
            user_id=USER_ID,
            title="Album",
            content="content",
            event_date_range=EventDateRange(start=now, end=now + timedelta(hours=1)),
        )
    )
    assert saved.id is not None
    await connection.execute(
        text("""
            INSERT INTO sync_metadata (
                internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status,
                internal_entity_type, external_entity_type
            ) VALUES (
                :internal_id, 'immich_album', :external_id, now(), 'h', 'success',
                'journal', 'album'
            )
        """),
        {"internal_id": saved.id, "external_id": album_id},
    )
    return saved.id


@pytest.mark.integration
class TestAlbumLinkDualWrite:
    """``upsert_link`` mirrors reference_data onto the sync_metadata link."""

    async def test_upsert_link_mirrors_reference_data_to_sync_metadata(
        self, repo: AlbumSyncReadRepository, async_connection: AsyncConnection
    ):
        album_id = "album-mirror"
        journal_id = await _make_album_sync_metadata_only(
            async_connection, album_id=album_id
        )
        reference_data = {"album_name": "Mirrored Trip", "asset_count": 12}

        await repo.upsert_link(journal_id, album_id, reference_data, bump_anchor=True)

        # The album reference_data is written to external_references (existing
        # behaviour) and mirrored onto the canonical sync_metadata link.
        sm = await async_connection.execute(
            text("""
                SELECT reference_data FROM sync_metadata
                WHERE integration_source = 'immich_album'
                  AND external_id = :album_id
                  AND internal_id = :journal_id
            """),
            {"album_id": album_id, "journal_id": journal_id},
        )
        sm_row = sm.fetchone()
        assert sm_row is not None
        assert sm_row.reference_data is not None
        assert json.loads(sm_row.reference_data) == reference_data

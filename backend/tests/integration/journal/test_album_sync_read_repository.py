"""Integration tests for AlbumSyncReadRepository.

Verifies PHOTO_ALBUM type data is read from the canonical sync_metadata link
(``reference_data``), that a malformed reference_data row degrades gracefully
instead of 500ing, and that ``upsert_link`` writes the album link (and merge
anchor) onto sync_metadata only.
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

    # Album display data lives in the canonical sync_metadata link; the read
    # path no longer joins external_references.
    await connection.execute(
        text("""
            INSERT INTO sync_metadata (
                internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status,
                internal_entity_type, external_entity_type, reference_data
            ) VALUES (
                :internal_id, 'immich_album', :external_id, now(), 'h', 'success',
                'journal', 'album', :reference_data
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


async def _count_album_external_refs(connection: AsyncConnection, album_id: str) -> int:
    """Count legacy external_references album rows for an album id."""
    result = await connection.execute(
        text("""
            SELECT count(*) AS n FROM external_references
            WHERE external_system = 'immich'
              AND external_entity_type = 'album'
              AND external_entity_id = :album_id
        """),
        {"album_id": album_id},
    )
    return int(result.scalar_one())


async def _sync_metadata_anchor(
    connection: AsyncConnection, album_id: str, journal_id: int
) -> datetime:
    result = await connection.execute(
        text("""
            SELECT updated_at FROM sync_metadata
            WHERE integration_source = 'immich_album'
              AND external_id = :album_id
              AND internal_id = :journal_id
        """),
        {"album_id": album_id, "journal_id": journal_id},
    )
    row = result.fetchone()
    assert row is not None
    anchor: datetime = row.updated_at
    return anchor


@pytest.mark.integration
class TestAlbumLinkWrite:
    """``upsert_link`` writes the canonical sync_metadata link only (Phase 4)."""

    async def test_upsert_link_writes_sync_metadata_only(
        self, repo: AlbumSyncReadRepository, async_connection: AsyncConnection
    ):
        album_id = "album-mirror"
        journal_id = await _make_album_sync_metadata_only(
            async_connection, album_id=album_id
        )
        reference_data = {"album_name": "Mirrored Trip", "asset_count": 12}

        await repo.upsert_link(
            journal_id, album_id, reference_data, version_hash="v1", bump_anchor=True
        )

        # The album reference_data is written onto the canonical sync_metadata link.
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

        # ...and no external_references row is written.
        assert await _count_album_external_refs(async_connection, album_id) == 0

    async def test_upsert_link_clears_stale_error_on_success(
        self, repo: AlbumSyncReadRepository, async_connection: AsyncConnection
    ):
        """A successful upsert clears a prior failure's sync_status/error_message."""
        album_id = "album-recover"
        journal_id = await _make_album_sync_metadata_only(
            async_connection, album_id=album_id
        )
        # Simulate a prior failed sync leaving a status + error message behind.
        await async_connection.execute(
            text("""
                UPDATE sync_metadata
                SET sync_status = 'failed', error_message = 'boom'
                WHERE integration_source = 'immich_album'
                  AND external_id = :album_id AND internal_id = :journal_id
            """),
            {"album_id": album_id, "journal_id": journal_id},
        )

        await repo.upsert_link(
            journal_id,
            album_id,
            {"album_name": "Recovered"},
            version_hash="v2",
            bump_anchor=True,
        )

        row = (
            await async_connection.execute(
                text("""
                    SELECT sync_status, error_message FROM sync_metadata
                    WHERE integration_source = 'immich_album'
                      AND external_id = :album_id AND internal_id = :journal_id
                """),
                {"album_id": album_id, "journal_id": journal_id},
            )
        ).fetchone()
        assert row is not None
        assert row.sync_status == "success"
        assert row.error_message is None

    async def test_find_link_reads_sync_metadata_anchor(
        self, repo: AlbumSyncReadRepository, async_connection: AsyncConnection
    ):
        album_id = "album-anchor-read"
        journal_id = await _make_album_sync_metadata_only(
            async_connection, album_id=album_id
        )

        link = await repo.find_link(album_id, journal_id=journal_id)

        assert link is not None
        assert link.internal_entity_id == journal_id
        # The anchor matches the sync_metadata row's updated_at.
        assert link.updated_at == await _sync_metadata_anchor(
            async_connection, album_id, journal_id
        )

    async def test_bump_anchor_advances_then_preserves(
        self, repo: AlbumSyncReadRepository, async_connection: AsyncConnection
    ):
        album_id = "album-anchor-bump"
        journal_id = await _make_album_sync_metadata_only(
            async_connection, album_id=album_id
        )
        # Pin the anchor to a known past value.
        past = datetime(2020, 1, 1, tzinfo=UTC)
        await async_connection.execute(
            text("""
                UPDATE sync_metadata SET updated_at = :past
                WHERE integration_source = 'immich_album'
                  AND external_id = :album_id AND internal_id = :journal_id
            """),
            {"past": past, "album_id": album_id, "journal_id": journal_id},
        )

        # bump_anchor=False preserves the anchor (locally edited journal stays
        # protected) while still writing reference_data.
        await repo.upsert_link(
            journal_id,
            album_id,
            {"album_name": "A"},
            version_hash="v2",
            bump_anchor=False,
        )
        assert (
            await _sync_metadata_anchor(async_connection, album_id, journal_id) == past
        )

        # bump_anchor=True advances the anchor.
        await repo.upsert_link(
            journal_id,
            album_id,
            {"album_name": "B"},
            version_hash="v3",
            bump_anchor=True,
        )
        assert (
            await _sync_metadata_anchor(async_connection, album_id, journal_id) > past
        )

    async def test_delete_removes_sync_metadata_only(
        self, repo: AlbumSyncReadRepository, async_connection: AsyncConnection
    ):
        album_id = "album-delete"
        journal_id = await _make_album_sync_metadata_only(
            async_connection, album_id=album_id
        )

        await repo.delete(journal_id)

        remaining = await async_connection.execute(
            text("""
                SELECT count(*) FROM sync_metadata
                WHERE integration_source = 'immich_album' AND internal_id = :journal_id
            """),
            {"journal_id": journal_id},
        )
        assert int(remaining.scalar_one()) == 0

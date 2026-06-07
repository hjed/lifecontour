"""Integration tests for PHOTO_ALBUM journal type detection via sync_metadata.

ITER11-004 Phase 1: PHOTO_ALBUM membership is no longer inferred from a
``journal_photo_album_data`` row. A journal is a PHOTO_ALBUM when it has a
``sync_metadata`` row with ``integration_source='immich_album'``. These tests
guard that detection, the NOTE-type regression (a non-album sync_metadata row
must not suppress NOTE), and PHOTO_ALBUM filtering.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import EventDateRange, Journal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

USER_ID = "type-detection-user"


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


def _make_journal(title: str = "Album Journal") -> Journal:
    now = datetime.now(UTC)
    return Journal(
        user_id=USER_ID,
        title=title,
        content="content",
        event_date_range=EventDateRange(start=now, end=now + timedelta(hours=1)),
    )


async def _add_sync_metadata(
    connection: AsyncConnection,
    *,
    internal_id: int,
    integration_source: str,
    external_id: str,
) -> None:
    await connection.execute(
        text("""
            INSERT INTO sync_metadata (
                internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status
            ) VALUES (
                :internal_id, :integration_source, :external_id,
                now(), :version_hash, 'success'
            )
        """),
        {
            "internal_id": internal_id,
            "integration_source": integration_source,
            "external_id": external_id,
            "version_hash": "hash-1",
        },
    )


@pytest.mark.integration
class TestPhotoAlbumTypeDetection:
    """PHOTO_ALBUM type detection from sync_metadata."""

    async def test_journal_with_album_sync_metadata_reports_photo_album(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A journal with an immich_album sync_metadata row is a PHOTO_ALBUM."""
        saved = await journal_repository.save(_make_journal())
        assert saved.id is not None
        await _add_sync_metadata(
            async_connection,
            internal_id=saved.id,
            integration_source="immich_album",
            external_id="album-uuid-1",
        )

        types = await journal_repository.get_types(saved.id)

        assert "PHOTO_ALBUM" in types
        assert "NOTE" in types

    async def test_journal_without_type_rows_is_note_only(
        self,
        journal_repository: SqlJournalRepository,
    ):
        """A plain journal reports NOTE and not PHOTO_ALBUM."""
        saved = await journal_repository.save(_make_journal(title="Plain"))
        assert saved.id is not None

        types = await journal_repository.get_types(saved.id)

        assert types == ["NOTE"]

    async def test_non_album_sync_metadata_does_not_imply_photo_album(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A strava sync_metadata row must not make a journal a PHOTO_ALBUM.

        Regression: the album detection join is scoped to
        integration_source='immich_album', so an unrelated sync_metadata row on
        the same internal id must neither add PHOTO_ALBUM nor suppress NOTE.
        """
        saved = await journal_repository.save(_make_journal(title="Strava"))
        assert saved.id is not None
        await _add_sync_metadata(
            async_connection,
            internal_id=saved.id,
            integration_source="strava",
            external_id="activity-1",
        )

        types = await journal_repository.get_types(saved.id)

        assert "PHOTO_ALBUM" not in types
        assert types == ["NOTE"]


@pytest.mark.integration
class TestPhotoAlbumTypeFiltering:
    """PHOTO_ALBUM and NOTE filtering with sync_metadata-based detection."""

    async def test_filter_by_photo_album_returns_album_journals(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Filtering by PHOTO_ALBUM returns only album-linked journals."""
        plain = await journal_repository.save(_make_journal(title="Plain"))
        album = await journal_repository.save(_make_journal(title="Album"))
        assert album.id is not None
        await _add_sync_metadata(
            async_connection,
            internal_id=album.id,
            integration_source="immich_album",
            external_id="album-uuid-2",
        )

        album_journals = await journal_repository.get_all(
            USER_ID, journal_type="PHOTO_ALBUM"
        )

        ids = {j.id for j in album_journals}
        assert album.id in ids
        assert plain.id not in ids

    async def test_filter_by_note_excludes_album_journals(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A PHOTO_ALBUM journal is excluded from the NOTE filter."""
        plain = await journal_repository.save(_make_journal(title="Plain"))
        album = await journal_repository.save(_make_journal(title="Album"))
        assert album.id is not None
        await _add_sync_metadata(
            async_connection,
            internal_id=album.id,
            integration_source="immich_album",
            external_id="album-uuid-3",
        )

        note_journals = await journal_repository.get_all(USER_ID, journal_type="NOTE")

        ids = {j.id for j in note_journals}
        assert plain.id in ids
        assert album.id not in ids


@pytest.mark.integration
class TestPhotoAlbumDataMigration:
    """The 0085 migration drops the table and allows the immich_album source."""

    async def test_journal_photo_album_data_table_is_dropped(
        self,
        async_connection: AsyncConnection,
    ):
        """The legacy journal_photo_album_data table no longer exists."""
        result = await async_connection.execute(
            text("SELECT to_regclass('public.journal_photo_album_data') AS reg")
        )
        row = result.fetchone()
        assert row is not None
        assert row.reg is None

    async def test_immich_album_is_an_allowed_sync_source(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A sync_metadata row with integration_source='immich_album' inserts."""
        saved = await journal_repository.save(_make_journal(title="Constraint"))
        assert saved.id is not None

        # Would raise an IntegrityError if the check constraint disallowed it.
        await _add_sync_metadata(
            async_connection,
            internal_id=saved.id,
            integration_source="immich_album",
            external_id="album-uuid-constraint",
        )

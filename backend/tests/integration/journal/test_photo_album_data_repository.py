"""Integration tests for PhotoAlbumDataRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.photo_album_data_repository import (
    SqlPhotoAlbumDataRepository,
)
from app.core.journal.models.photo_album_data import PhotoAlbumData


@pytest.mark.integration
class TestSqlPhotoAlbumDataRepository:
    """Integration tests for SqlPhotoAlbumDataRepository."""

    async def test_find_by_journal_id_not_found(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test finding photo album data that doesn't exist."""
        repo = SqlPhotoAlbumDataRepository(db_connection)

        result = await repo.find_by_journal_id(sample_journal_id)

        assert result is None

    async def test_save_and_find_photo_album_data(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test saving and finding photo album data."""
        repo = SqlPhotoAlbumDataRepository(db_connection)

        # Create photo album data
        photo_album_data = PhotoAlbumData(
            journal_id=sample_journal_id,
            immich_album_id="album-123-456-789",
        )

        # Save photo album data
        saved = await repo.save(photo_album_data)

        # Verify saved data
        assert saved.journal_id == sample_journal_id
        assert saved.immich_album_id == "album-123-456-789"
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # Find photo album data
        found = await repo.find_by_journal_id(sample_journal_id)

        assert found is not None
        assert found.journal_id == sample_journal_id
        assert found.immich_album_id == "album-123-456-789"
        assert found.created_at == saved.created_at
        assert found.updated_at == saved.updated_at

    async def test_update_photo_album_data(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test updating existing photo album data."""
        repo = SqlPhotoAlbumDataRepository(db_connection)

        # Create and save initial photo album data
        initial_data = PhotoAlbumData(
            journal_id=sample_journal_id,
            immich_album_id="album-initial",
        )
        saved_initial = await repo.save(initial_data)

        # Update photo album data
        updated_data = PhotoAlbumData(
            journal_id=sample_journal_id,
            immich_album_id="album-updated",
        )
        saved_updated = await repo.save(updated_data)

        # Verify updated data
        assert saved_updated.journal_id == sample_journal_id
        assert saved_updated.immich_album_id == "album-updated"
        assert saved_updated.created_at == saved_initial.created_at  # Should not change
        assert saved_updated.updated_at is not None
        assert saved_initial.updated_at is not None
        assert saved_updated.updated_at > saved_initial.updated_at  # Should be updated

        # Verify in database
        found = await repo.find_by_journal_id(sample_journal_id)
        assert found is not None
        assert found.immich_album_id == "album-updated"

    async def test_delete_photo_album_data(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test deleting photo album data."""
        repo = SqlPhotoAlbumDataRepository(db_connection)

        # Create and save photo album data
        photo_album_data = PhotoAlbumData(
            journal_id=sample_journal_id,
            immich_album_id="album-to-delete",
        )
        await repo.save(photo_album_data)

        # Verify it exists
        found = await repo.find_by_journal_id(sample_journal_id)
        assert found is not None

        # Delete photo album data
        await repo.delete(sample_journal_id)

        # Verify it's deleted
        found_after_delete = await repo.find_by_journal_id(sample_journal_id)
        assert found_after_delete is None

    async def test_delete_nonexistent_photo_album_data(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test deleting photo album data that doesn't exist (should not raise error)."""
        repo = SqlPhotoAlbumDataRepository(db_connection)

        # Delete non-existent data (should not raise error)
        await repo.delete(sample_journal_id)

        # Verify still doesn't exist
        found = await repo.find_by_journal_id(sample_journal_id)
        assert found is None

    async def test_save_with_long_album_id(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test saving photo album data with maximum length album ID."""
        repo = SqlPhotoAlbumDataRepository(db_connection)

        # Create photo album data with long album ID (within limit)
        long_album_id = "a" * 255  # MAX_IMMICH_ALBUM_ID_LENGTH
        photo_album_data = PhotoAlbumData(
            journal_id=sample_journal_id,
            immich_album_id=long_album_id,
        )

        # Save and verify
        saved = await repo.save(photo_album_data)
        assert saved.immich_album_id == long_album_id

        # Verify in database
        found = await repo.find_by_journal_id(sample_journal_id)
        assert found is not None
        assert found.immich_album_id == long_album_id

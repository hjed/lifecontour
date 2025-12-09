"""Unit tests for PhotoAlbumData entity (PHOTO_ALBUM type)."""

import pytest

from app.core.journal.models.constants import MAX_IMMICH_ALBUM_ID_LENGTH
from app.core.journal.models.exceptions import PhotoAlbumDataValidationError
from app.core.journal.models.photo_album_data import PhotoAlbumData


@pytest.mark.unit
class TestPhotoAlbumData:
    """Test PhotoAlbumData entity."""

    def test_create_photo_album_data_with_immich_id(self):
        """Test creating photo album data with Immich album ID."""
        photo_album = PhotoAlbumData(
            journal_id=1,
            immich_album_id="abc-123-def-456",
        )

        assert photo_album.journal_id == 1
        assert photo_album.immich_album_id == "abc-123-def-456"

    def test_create_photo_album_data_with_uuid_style_id(self):
        """Test creating photo album data with UUID-style Immich album ID."""
        photo_album = PhotoAlbumData(
            journal_id=1,
            immich_album_id="550e8400-e29b-41d4-a716-446655440000",
        )

        assert photo_album.immich_album_id == "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.unit
class TestPhotoAlbumDataValidation:
    """Test PhotoAlbumData validation."""

    def test_invalid_journal_id_zero_raises_error(self):
        """Test that journal_id of 0 raises error."""
        with pytest.raises(
            PhotoAlbumDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            PhotoAlbumData(journal_id=0, immich_album_id="abc-123")

    def test_invalid_journal_id_negative_raises_error(self):
        """Test that negative journal_id raises error."""
        with pytest.raises(
            PhotoAlbumDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            PhotoAlbumData(journal_id=-1, immich_album_id="abc-123")

    def test_empty_immich_album_id_raises_error(self):
        """Test that empty immich_album_id raises error."""
        with pytest.raises(
            PhotoAlbumDataValidationError,
            match="Immich album ID is required",
        ):
            PhotoAlbumData(journal_id=1, immich_album_id="")

    def test_whitespace_only_immich_album_id_raises_error(self):
        """Test that whitespace-only immich_album_id raises error."""
        with pytest.raises(
            PhotoAlbumDataValidationError,
            match="Immich album ID is required",
        ):
            PhotoAlbumData(journal_id=1, immich_album_id="   ")

    def test_immich_album_id_at_max_length(self):
        """Test immich_album_id at max length is valid."""
        max_id = "a" * MAX_IMMICH_ALBUM_ID_LENGTH
        photo_album = PhotoAlbumData(journal_id=1, immich_album_id=max_id)
        assert len(photo_album.immich_album_id) == MAX_IMMICH_ALBUM_ID_LENGTH

    def test_immich_album_id_too_long_raises_error(self):
        """Test that immich_album_id exceeding max length raises error."""
        long_id = "a" * (MAX_IMMICH_ALBUM_ID_LENGTH + 1)
        with pytest.raises(
            PhotoAlbumDataValidationError,
            match=f"Immich album ID cannot exceed {MAX_IMMICH_ALBUM_ID_LENGTH}",
        ):
            PhotoAlbumData(journal_id=1, immich_album_id=long_id)


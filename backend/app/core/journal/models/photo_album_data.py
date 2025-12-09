"""PhotoAlbumData entity for the journal domain.

PhotoAlbumData represents the PHOTO_ALBUM journal type data. A journal has the
PHOTO_ALBUM type if a row exists in the journal_photo_album_data table.

This entity links a journal to an external Immich photo album for integration
with the Immich photo management system (prepared for Iteration 6).
"""

from dataclasses import dataclass
from datetime import datetime

from .constants import MAX_IMMICH_ALBUM_ID_LENGTH
from .exceptions import PhotoAlbumDataValidationError


@dataclass
class PhotoAlbumData:
    """
    PhotoAlbumData entity for PHOTO_ALBUM type journals.

    This entity represents additional data for journals that have the PHOTO_ALBUM type.
    A journal is considered to have the PHOTO_ALBUM type if a row exists in
    journal_photo_album_data for that journal_id.

    The immich_album_id links the journal to an external Immich album for
    photo integration. Photos are fetched from Immich API on-demand.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        immich_album_id: Immich album identifier (required)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    immich_album_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate photo album data properties."""
        self._validate_journal_id()
        self._validate_immich_album_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise PhotoAlbumDataValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_immich_album_id(self) -> None:
        """Validate immich_album_id is provided and within length limit."""
        if not self.immich_album_id or not self.immich_album_id.strip():
            raise PhotoAlbumDataValidationError(
                "immich_album_id", "Immich album ID is required"
            )

        if len(self.immich_album_id) > MAX_IMMICH_ALBUM_ID_LENGTH:
            raise PhotoAlbumDataValidationError(
                "immich_album_id",
                f"Immich album ID cannot exceed {MAX_IMMICH_ALBUM_ID_LENGTH} characters",
            )


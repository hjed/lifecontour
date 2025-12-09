"""SQL implementation of PhotoAlbumDataRepository."""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.exceptions import PhotoAlbumDataValidationError
from app.core.journal.models.photo_album_data import PhotoAlbumData
from app.core.journal.models.repositories import PhotoAlbumDataRepository


class SqlPhotoAlbumDataRepository(PhotoAlbumDataRepository):
    """
    SQL implementation of PhotoAlbumDataRepository using SQLAlchemy Core.

    Uses explicit SQL queries for clarity and performance.
    Handles the journal_photo_album_data table operations.
    """

    def __init__(self, connection: AsyncConnection):
        """
        Initialize the repository with a database connection.

        Args:
            connection: SQLAlchemy async connection
        """
        self.connection = connection

    async def find_by_journal_id(self, journal_id: int) -> PhotoAlbumData | None:
        """
        Find photo album data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The PhotoAlbumData if found (journal has PHOTO_ALBUM type), None otherwise
        """
        query = text("""
            SELECT journal_id, immich_album_id, created_at, updated_at
            FROM journal_photo_album_data
            WHERE journal_id = :journal_id
        """)

        result = await self.connection.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if row is None:
            return None

        return PhotoAlbumData(
            journal_id=row.journal_id,
            immich_album_id=row.immich_album_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, photo_album_data: PhotoAlbumData) -> PhotoAlbumData:
        """
        Save photo album data (insert or update).

        This effectively adds or updates the PHOTO_ALBUM type for a journal.

        Args:
            photo_album_data: The photo album data to save

        Returns:
            The saved photo album data with updated timestamps

        Raises:
            PhotoAlbumDataValidationError: If database constraints are violated
        """
        now = datetime.utcnow()

        # Check if record exists
        existing = await self.find_by_journal_id(photo_album_data.journal_id)

        try:
            if existing is None:
                # Insert new record
                query = text("""
                    INSERT INTO journal_photo_album_data 
                    (journal_id, immich_album_id, created_at, updated_at)
                    VALUES (:journal_id, :immich_album_id, :created_at, :updated_at)
                """)

                await self.connection.execute(
                    query,
                    {
                        "journal_id": photo_album_data.journal_id,
                        "immich_album_id": photo_album_data.immich_album_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                )

                return PhotoAlbumData(
                    journal_id=photo_album_data.journal_id,
                    immich_album_id=photo_album_data.immich_album_id,
                    created_at=now,
                    updated_at=now,
                )
            else:
                # Update existing record
                query = text("""
                    UPDATE journal_photo_album_data
                    SET immich_album_id = :immich_album_id, updated_at = :updated_at
                    WHERE journal_id = :journal_id
                """)

                await self.connection.execute(
                    query,
                    {
                        "journal_id": photo_album_data.journal_id,
                        "immich_album_id": photo_album_data.immich_album_id,
                        "updated_at": now,
                    },
                )

                return PhotoAlbumData(
                    journal_id=photo_album_data.journal_id,
                    immich_album_id=photo_album_data.immich_album_id,
                    created_at=existing.created_at,
                    updated_at=now,
                )

        except IntegrityError as e:
            raise PhotoAlbumDataValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

    async def delete(self, journal_id: int) -> None:
        """
        Delete photo album data by journal ID.

        This effectively removes the PHOTO_ALBUM type from a journal.

        Args:
            journal_id: The journal ID to delete photo album data for
        """
        query = text("""
            DELETE FROM journal_photo_album_data
            WHERE journal_id = :journal_id
        """)

        await self.connection.execute(query, {"journal_id": journal_id})

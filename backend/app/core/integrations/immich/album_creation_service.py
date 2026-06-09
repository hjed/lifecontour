"""On-demand Immich album creation from a journal's date range (ITER11-006).

Unlike album *import* (worker -> outbox -> backend), album *creation* is a
synchronous user action, so it runs entirely in the backend request: search
Immich for photos in the journal's date range, then create an album from the
selected assets and link it back to the journal.

The journal -> album link reuses the same persistence the album-import
processor uses (``SyncMetadataRepository`` + ``AlbumSyncReadRepository``), so a
created album is indistinguishable from an imported one — and, because
PHOTO_ALBUM type is derived from the ``immich_album`` ``sync_metadata`` row,
writing that row is what adds the PHOTO_ALBUM type to the journal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from core_shared.immich_album_hash import compute_album_version_hash
from core_shared.models.journals import Journal
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.integrations.immich.adapters.album_api_client import ImmichAlbumApiClient
from app.core.journal.adapters.sql.album_sync_read_repository import (
    INTEGRATION_SOURCE,
    AlbumSyncReadRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.timezone_utils import resolve_timezone, to_user_tz
from app.infrastructure.auth.immich_token_service import ImmichTokenService

logger = structlog.get_logger(__name__)


class ImmichAlbumCreationError(Exception):
    """Base error for the album-creation flow."""


class JournalNotFoundError(ImmichAlbumCreationError):
    """The journal does not exist or is not owned by the requesting user."""


class ImmichNotConnectedError(ImmichAlbumCreationError):
    """The user has no usable Immich credentials."""


class AlbumAlreadyLinkedError(ImmichAlbumCreationError):
    """The journal already has a linked Immich album."""


class EmptyAlbumSelectionError(ImmichAlbumCreationError):
    """No assets were selected for the album (nothing to create)."""


@dataclass(frozen=True)
class PhotoSearchResult:
    """A photo candidate for album creation, for UI display."""

    asset_id: str
    thumbnail_url: str
    original_file_name: str
    taken_at: str | None


@dataclass(frozen=True)
class AlbumCreationResult:
    """The outcome of creating an album from a journal."""

    album_id: str
    journal_id: int
    shared_link_url: str | None
    asset_count: int


def compute_search_window(
    start: datetime, end: datetime, timezone: str | None
) -> tuple[str, str]:
    """Expand a UTC ``event_date_range`` to full local days, back to UTC.

    Returns ``(taken_after, taken_before)`` as ISO-8601 UTC strings suitable
    for the Immich ``/search/metadata`` ``takenAfter``/``takenBefore`` filters.
    The range covers the start of the first day to the end of the last day in
    the user's timezone, so e.g. a 15 January journal in Sydney captures photos
    taken late on 14 January UTC.
    """
    tz = resolve_timezone(timezone)
    start_local = to_user_tz(start, tz).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end_local = to_user_tz(end, tz).replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    return (
        start_local.astimezone(UTC).isoformat(),
        end_local.astimezone(UTC).isoformat(),
    )


class ImmichAlbumCreationService:
    """Searches Immich photos and creates albums from journal date ranges."""

    def __init__(
        self,
        *,
        connection: AsyncConnection,
        token_service: ImmichTokenService,
        api_client: ImmichAlbumApiClient,
        journal_repo: SqlJournalRepository,
        sync_metadata_repo: SyncMetadataRepository,
        album_link_repo: AlbumSyncReadRepository,
        user_settings_repo: SqlUserSettingsRepository,
    ) -> None:
        self.connection = connection
        self.token_service = token_service
        self.api_client = api_client
        self.journal_repo = journal_repo
        self.sync_metadata_repo = sync_metadata_repo
        self.album_link_repo = album_link_repo
        self.user_settings_repo = user_settings_repo

    async def search_photos(
        self, journal_id: int, user_id: str
    ) -> list[PhotoSearchResult]:
        """Return Immich photos taken within the journal's date range."""
        journal = await self._get_owned_journal(journal_id, user_id)
        server_url, api_key = await self._require_credentials(user_id)

        timezone = await self.user_settings_repo.get_timezone(user_id)
        taken_after, taken_before = compute_search_window(
            journal.event_date_range.start, journal.event_date_range.end, timezone
        )

        assets = await self.api_client.search_metadata(
            server_url,
            api_key,
            taken_after=taken_after,
            taken_before=taken_before,
        )
        return [self._to_photo(asset) for asset in assets if asset.get("id")]

    async def create_album(
        self,
        journal_id: int,
        user_id: str,
        *,
        asset_ids: list[str],
        create_shared_link: bool,
    ) -> AlbumCreationResult:
        """Create an Immich album from ``asset_ids`` and link it to the journal."""
        if not asset_ids:
            raise EmptyAlbumSelectionError(
                "At least one photo must be selected to create an album"
            )

        journal = await self._get_owned_journal(journal_id, user_id)

        if await self.album_link_repo.find_external_links(journal_id):
            raise AlbumAlreadyLinkedError(
                f"Journal {journal_id} already has a linked Immich album"
            )

        server_url, api_key = await self._require_credentials(user_id)

        album = await self.api_client.create_album(
            server_url, api_key, album_name=journal.title, asset_ids=asset_ids
        )
        album_id = album.get("id")
        if not album_id:
            raise ImmichAlbumCreationError("Immich did not return an album id")

        shared_link_url: str | None = None
        if create_shared_link:
            link = await self.api_client.create_shared_link(
                server_url, api_key, album_id=album_id
            )
            key = link.get("key")
            if key:
                shared_link_url = f"{server_url.rstrip('/')}/share/{key}"

        asset_count = album.get("assetCount") or len(asset_ids)
        version_hash = compute_album_version_hash(
            name=journal.title,
            asset_count=asset_count,
            shared_link_url=shared_link_url,
        )

        await self.sync_metadata_repo.upsert(
            integration_source=INTEGRATION_SOURCE,
            external_id=album_id,
            version_hash=version_hash,
            internal_id=journal_id,
        )

        reference_data = self._reference_data(
            server_url=server_url,
            album_id=album_id,
            album_name=album.get("albumName") or journal.title,
            asset_count=asset_count,
            thumbnail_asset_id=album.get("albumThumbnailAssetId"),
            shared_link_url=shared_link_url,
        )
        await self.album_link_repo.upsert_link(
            journal_id, album_id, reference_data, bump_anchor=True
        )

        logger.info(
            "Created Immich album from journal",
            journal_id=journal_id,
            album_id=album_id,
            asset_count=asset_count,
            shared_link=shared_link_url is not None,
        )
        return AlbumCreationResult(
            album_id=album_id,
            journal_id=journal_id,
            shared_link_url=shared_link_url,
            asset_count=asset_count,
        )

    async def _get_owned_journal(self, journal_id: int, user_id: str) -> Journal:
        """Fetch a journal, raising ``JournalNotFoundError`` if not owned."""
        journal = await self.journal_repo.find_by_id(journal_id)
        if journal is None or journal.user_id != user_id:
            raise JournalNotFoundError(f"Journal {journal_id} not found")
        return journal

    async def _require_credentials(self, user_id: str) -> tuple[str, str]:
        """Return decrypted ``(server_url, api_key)`` or raise if unconnected."""
        server_url, api_key = await self.token_service.get_credentials(user_id)
        if not server_url or not api_key:
            raise ImmichNotConnectedError("Immich is not connected for this user")
        return server_url, api_key

    @staticmethod
    def _to_photo(asset: dict[str, Any]) -> PhotoSearchResult:
        asset_id = str(asset["id"])
        taken_at = asset.get("takenAt") or asset.get("fileCreatedAt")
        return PhotoSearchResult(
            asset_id=asset_id,
            thumbnail_url=f"/api/integrations/immich/assets/{asset_id}/thumbnail",
            original_file_name=str(asset.get("originalFileName") or ""),
            taken_at=str(taken_at) if taken_at else None,
        )

    @staticmethod
    def _reference_data(
        *,
        server_url: str,
        album_id: str,
        album_name: str | None,
        asset_count: int,
        thumbnail_asset_id: str | None,
        shared_link_url: str | None,
    ) -> dict[str, Any]:
        """Build the album external-reference display data (drops ``None``)."""
        data: dict[str, Any] = {
            "album_id": album_id,
            "album_name": album_name,
            "asset_count": asset_count,
            "album_url": f"{server_url.rstrip('/')}/albums/{album_id}",
            "thumbnail_asset_id": thumbnail_asset_id,
            "shared_link_url": shared_link_url,
        }
        return {k: v for k, v in data.items() if v is not None}

"""Album cover proxy service for Immich album thumbnails.

Fetches an album's cover photo from Immich using stored credentials, keeping
the Immich server URL and API key hidden from the browser. Mirrors
``AvatarProxyService`` but resolves the cover asset for a PHOTO_ALBUM journal
and fetches the asset thumbnail rather than a person thumbnail. The cover is
fetched on-demand and never persisted locally (see ITER11-004 Phase 2).
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import structlog

from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)
from app.infrastructure.auth.immich_token_service import ImmichTokenService

logger = structlog.get_logger(__name__)


class AlbumCoverNotFoundError(Exception):
    """Raised when the album cover cannot be resolved."""


class AlbumCoverProxyService:
    """Proxy service that fetches Immich album cover thumbnails for the user.

    Args:
        album_repo: Repository for album-link lookups (cover asset resolution).
        immich_token_service: Service for Immich credential management.
    """

    def __init__(
        self,
        album_repo: AlbumSyncReadRepository,
        immich_token_service: ImmichTokenService,
    ) -> None:
        self._album_repo = album_repo
        self._token_service = immich_token_service

    async def get_cover_bytes(self, journal_id: int, user_id: str) -> tuple[bytes, str]:
        """Fetch the Immich album cover thumbnail for a PHOTO_ALBUM journal.

        Args:
            journal_id: Internal journal ID.
            user_id: Internal user ID (for credential lookup).

        Returns:
            Tuple of (raw image bytes, content-type string).

        Raises:
            AlbumCoverNotFoundError: If the journal has no linked album, the
                album has no cover asset, the user has no Immich credentials, or
                the thumbnail fetch fails.
        """
        cover = await self._album_repo.find_cover_asset(journal_id)
        if cover is None:
            raise AlbumCoverNotFoundError(
                f"Journal {journal_id} is not linked to an Immich album"
            )
        _album_id, thumbnail_asset_id = cover
        if not thumbnail_asset_id:
            raise AlbumCoverNotFoundError(
                f"Album for journal {journal_id} has no cover asset"
            )

        server_url, api_key = await self._get_immich_credentials(user_id)
        if server_url is None or api_key is None:
            raise AlbumCoverNotFoundError("Immich is not configured for this user")

        return await self._fetch_thumbnail(server_url, api_key, thumbnail_asset_id)

    async def _get_immich_credentials(
        self, user_id: str
    ) -> tuple[str | None, str | None]:
        """Fetch and decrypt the user's Immich server URL and API key."""
        try:
            return await self._token_service.get_credentials(user_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to retrieve Immich credentials for album cover proxy",
                user_id=user_id,
            )
            return None, None

    @staticmethod
    async def _fetch_thumbnail(
        server_url: str, api_key: str, asset_id: str
    ) -> tuple[bytes, str]:
        """Download an asset thumbnail from Immich.

        Returns:
            Tuple of (image bytes, content-type).

        Raises:
            AlbumCoverNotFoundError: If the Immich API returns an error.
        """
        # Validate the server URL to prevent SSRF.
        parsed = urlparse(server_url)
        if parsed.scheme not in ("http", "https"):
            raise AlbumCoverNotFoundError(
                f"Invalid Immich server URL scheme: {parsed.scheme}"
            )

        url = f"{server_url.rstrip('/')}/api/assets/{asset_id}/thumbnail"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    url,
                    headers={
                        "x-api-key": api_key,
                        "Accept": "application/octet-stream",
                    },
                )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "image/jpeg")
                return response.content, content_type
        except httpx.HTTPStatusError as e:
            logger.warning(
                "Immich album cover request failed",
                asset_id=asset_id,
                status=e.response.status_code,
            )
            raise AlbumCoverNotFoundError(
                f"Immich returned {e.response.status_code} for asset {asset_id}"
            ) from e
        except httpx.RequestError as e:
            logger.warning(
                "Immich album cover request error",
                asset_id=asset_id,
                error=str(e),
            )
            raise AlbumCoverNotFoundError(f"Failed to connect to Immich: {e}") from e

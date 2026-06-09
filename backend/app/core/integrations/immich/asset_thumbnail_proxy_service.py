"""Proxy for arbitrary Immich asset thumbnails (ITER11-006).

When creating an album from a journal date range, the photo-selection UI needs
to render candidate photos. The browser must not see the Immich server URL or
API key, so thumbnails are proxied through the backend using stored
credentials — mirroring ``AlbumCoverProxyService`` but for any asset id (not
just a journal's linked cover). Thumbnails are fetched on demand, never
persisted.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import structlog
from cryptography.fernet import InvalidToken

from app.infrastructure.auth.immich_token_service import (
    ImmichTokenService,
    ImmichTokenStorageError,
)

logger = structlog.get_logger(__name__)


class AssetThumbnailNotFoundError(Exception):
    """Raised when an asset thumbnail cannot be fetched."""


class AssetThumbnailProxyService:
    """Fetches Immich asset thumbnails for the authenticated user."""

    def __init__(self, immich_token_service: ImmichTokenService) -> None:
        self._token_service = immich_token_service

    async def get_thumbnail_bytes(
        self, asset_id: str, user_id: str
    ) -> tuple[bytes, str]:
        """Fetch an asset's thumbnail bytes from Immich.

        Returns:
            Tuple of (image bytes, content-type).

        Raises:
            AssetThumbnailNotFoundError: If the user has no Immich credentials
                or the thumbnail fetch fails.
        """
        server_url, api_key = await self._get_immich_credentials(user_id)
        if not server_url or not api_key:
            raise AssetThumbnailNotFoundError("Immich is not configured for this user")
        return await self._fetch_thumbnail(server_url, api_key, asset_id)

    async def _get_immich_credentials(
        self, user_id: str
    ) -> tuple[str | None, str | None]:
        try:
            return await self._token_service.get_credentials(user_id)
        except ImmichTokenStorageError, InvalidToken:
            # Credential-config problems degrade gracefully to "no thumbnail";
            # unexpected failures (e.g. DB outage) propagate so they aren't
            # masked as a 404.
            logger.warning(
                "Failed to retrieve Immich credentials for asset thumbnail proxy",
                user_id=user_id,
            )
            return None, None

    @staticmethod
    async def _fetch_thumbnail(
        server_url: str, api_key: str, asset_id: str
    ) -> tuple[bytes, str]:
        # Validate the server URL to prevent SSRF.
        parsed = urlparse(server_url)
        if parsed.scheme not in ("http", "https"):
            raise AssetThumbnailNotFoundError(
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
                "Immich asset thumbnail request failed",
                asset_id=asset_id,
                status=e.response.status_code,
            )
            raise AssetThumbnailNotFoundError(
                f"Immich returned {e.response.status_code} for asset {asset_id}"
            ) from e
        except httpx.RequestError as e:
            logger.warning(
                "Immich asset thumbnail request error",
                asset_id=asset_id,
                error=str(e),
            )
            raise AssetThumbnailNotFoundError(
                f"Failed to connect to Immich: {e}"
            ) from e

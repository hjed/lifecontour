"""Backend Immich API client for on-demand album creation (ITER11-006).

Album *import* runs in the isolated Immich worker, but album *creation* is a
synchronous, user-initiated flow (search photos, pick, confirm) that must run
inside the backend request. The backend cannot import the worker package, so
this client talks to Immich directly via ``httpx`` — mirroring
``AvatarProxyService``/``AlbumCoverProxyService`` (SSRF scheme check, fresh
client per call, ``x-api-key`` auth).

It exposes only the three write/search endpoints album creation needs:
``POST /search/metadata``, ``POST /albums`` and ``POST /shared-links``. Asset
thumbnails are served separately by ``AssetThumbnailProxyService``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Immich caps a single metadata-search page at 1000 results; album date ranges
# are narrow so a single page is sufficient. Pagination beyond this is out of
# scope for Phase 1 (a date range with >1000 photos is not expected).
_SEARCH_PAGE_SIZE = 1000


class ImmichAlbumApiError(Exception):
    """Error raised when an Immich album API call fails.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code, or ``None`` for connection/URL errors.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ImmichAlbumApiClient:
    """Async client for the Immich album-creation endpoints.

    Stateless: server URL and API key are passed per call so a single
    app-scoped instance can serve every user. ``transport`` is injectable so
    unit tests can drive the HTTP layer with an ``httpx.MockTransport``.
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._transport = transport

    async def search_metadata(
        self,
        server_url: str,
        api_key: str,
        *,
        taken_after: str,
        taken_before: str,
    ) -> list[dict[str, Any]]:
        """Search assets by capture date via ``POST /search/metadata``.

        Args:
            server_url: Immich server base URL.
            api_key: Immich API key.
            taken_after: ISO-8601 lower bound (inclusive), UTC.
            taken_before: ISO-8601 upper bound (inclusive), UTC.

        Returns:
            The list of matching asset objects (raw Immich JSON dicts).
        """
        payload = {
            "takenAfter": taken_after,
            "takenBefore": taken_before,
            "size": _SEARCH_PAGE_SIZE,
        }
        data = await self._post(server_url, api_key, "search/metadata", payload)
        return self._unwrap_assets(data)

    async def create_album(
        self,
        server_url: str,
        api_key: str,
        *,
        album_name: str,
        asset_ids: list[str],
    ) -> dict[str, Any]:
        """Create an album via ``POST /albums`` and return the created album."""
        payload = {"albumName": album_name, "assetIds": asset_ids}
        data = await self._post(server_url, api_key, "albums", payload)
        if not isinstance(data, dict) or not data.get("id"):
            # Unexpected shape / missing id is an upstream contract break;
            # surface it as an API error (502) rather than a later 500.
            raise ImmichAlbumApiError(
                "Immich returned an unexpected album-creation response"
            )
        return data

    async def create_shared_link(
        self,
        server_url: str,
        api_key: str,
        *,
        album_id: str,
    ) -> dict[str, Any]:
        """Create a public album shared link via ``POST /shared-links``."""
        payload = {"type": "ALBUM", "albumId": album_id}
        data = await self._post(server_url, api_key, "shared-links", payload)
        if not isinstance(data, dict):
            raise ImmichAlbumApiError(
                "Immich returned an unexpected shared-link response"
            )
        return data

    @staticmethod
    def _unwrap_assets(data: Any) -> list[dict[str, Any]]:
        """Pull the asset list out of the ``/search/metadata`` envelope.

        Immich wraps results as ``{"assets": {"items": [...]}}``; tolerate the
        plain-list and bare-``assets`` shapes too.
        """
        assets_data = data.get("assets", data) if isinstance(data, dict) else data
        items = (
            assets_data.get("items", [])
            if isinstance(assets_data, dict)
            else assets_data
        )
        return [item for item in items if isinstance(item, dict)]

    def _build_client(self, server_url: str, api_key: str) -> httpx.AsyncClient:
        """Construct an ``httpx.AsyncClient`` bound to the Immich ``/api`` root."""
        return httpx.AsyncClient(
            base_url=f"{server_url.rstrip('/')}/api/",
            headers={
                "x-api-key": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _post(
        self,
        server_url: str,
        api_key: str,
        path: str,
        payload: dict[str, Any],
    ) -> Any:
        """POST ``payload`` to ``path`` and return the parsed JSON body."""
        # Validate the server URL to prevent SSRF before any request is made.
        parsed = urlparse(server_url)
        if parsed.scheme not in ("http", "https"):
            raise ImmichAlbumApiError(
                f"Invalid Immich server URL scheme: {parsed.scheme}"
            )

        try:
            async with self._build_client(server_url, api_key) as client:
                response = await client.post(path, json=payload)
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError as e:
                    # Non-JSON body (e.g. an HTML error page from a reverse
                    # proxy) — surface as an Immich API error, not a 500.
                    logger.warning(
                        "Immich album API returned a non-JSON body", path=path
                    )
                    raise ImmichAlbumApiError(
                        f"Immich returned a non-JSON response for {path}"
                    ) from e
        except httpx.HTTPStatusError as e:
            logger.warning(
                "Immich album API request failed",
                path=path,
                status=e.response.status_code,
            )
            raise ImmichAlbumApiError(
                f"Immich returned {e.response.status_code} for {path}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            logger.warning("Immich album API request error", path=path, error=str(e))
            raise ImmichAlbumApiError(f"Failed to connect to Immich: {e}") from e

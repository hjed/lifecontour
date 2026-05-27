"""
Immich REST API async client.

Provides typed methods for the Immich REST API endpoints needed for
contact/album sync. Uses ``httpx.AsyncClient`` with ``x-api-key`` header
authentication.

The base URL is dynamic (self-hosted instances) and provided at
construction time from the user's Immich configuration.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from immich_models import (
    ImmichAlbum,
    ImmichAsset,
    ImmichPeopleResponse,
    ImmichPerson,
    ImmichServerInfo,
    ImmichSharedLink,
)

logger = structlog.get_logger(__name__)


class ImmichApiError(Exception):
    """Error from an Immich API call.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code, or ``None`` for non-HTTP errors.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ImmichApiClient:
    """Async client for the Immich REST API.

    Uses an injected ``httpx.AsyncClient`` with ``x-api-key`` header
    authentication.

    Args:
        client: Pre-configured ``httpx.AsyncClient`` (injected for testability).
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @classmethod
    def create(
        cls,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
    ) -> ImmichApiClient:
        """Factory: create a client with a new ``httpx.AsyncClient``.

        Convenience constructor for production use. For testing, inject
        the client directly via the constructor.

        Args:
            base_url: Immich server base URL
                (e.g. ``https://immich.example.com``).
            api_key: Immich API key.
            timeout: Request timeout in seconds.
        """
        client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/api/",
            headers={
                "x-api-key": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        return cls(client)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # -- Server info --

    async def get_server_info(self) -> ImmichServerInfo:
        """Get Immich server version and license info.

        Calls ``GET /server/about``.

        Returns:
            Parsed server info.
        """
        data = await self._get("server/about")
        return ImmichServerInfo.model_validate(data)

    # -- People --

    async def get_all_people(
        self,
        *,
        with_hidden: bool = False,
        page: int = 1,
        size: int = 500,
    ) -> ImmichPeopleResponse:
        """Get all people (face clusters).

        Calls ``GET /people``.

        Args:
            with_hidden: Include hidden people.
            page: Page number (1-based).
            size: Number of results per page.

        Returns:
            Paginated people response.
        """
        params: dict[str, Any] = {
            "withHidden": str(with_hidden).lower(),
            "page": page,
            "size": size,
        }
        data = await self._get("people", params=params)
        return ImmichPeopleResponse.model_validate(data)

    async def get_person(self, person_id: str) -> ImmichPerson:
        """Get a single person by ID.

        Calls ``GET /people/{id}``.

        Args:
            person_id: Immich person UUID.

        Returns:
            Parsed person.
        """
        data = await self._get(f"people/{person_id}")
        return ImmichPerson.model_validate(data)

    async def update_person(
        self, person_id: str, update_data: dict[str, Any]
    ) -> ImmichPerson:
        """Update a person's metadata.

        Calls ``PUT /people/{id}``.

        Args:
            person_id: Immich person UUID.
            update_data: Fields to update (e.g. ``name``, ``birthDate``).

        Returns:
            Updated person.
        """
        data = await self._put(f"people/{person_id}", json_data=update_data)
        return ImmichPerson.model_validate(data)

    async def get_person_thumbnail(self, person_id: str) -> bytes:
        """Download a person's face thumbnail.

        Calls ``GET /people/{id}/thumbnail``.

        Args:
            person_id: Immich person UUID.

        Returns:
            Raw thumbnail bytes.
        """
        return await self._get_bytes(f"people/{person_id}/thumbnail")

    # -- Albums --

    async def get_all_albums(
        self,
        *,
        shared: bool | None = None,
    ) -> list[ImmichAlbum]:
        """Get all albums.

        Calls ``GET /albums``.

        Args:
            shared: Filter by shared status. ``None`` for all albums.

        Returns:
            List of albums.
        """
        params: dict[str, Any] = {}
        if shared is not None:
            params["shared"] = str(shared).lower()

        data = await self._get("albums", params=params)
        return [ImmichAlbum.model_validate(item) for item in data]

    async def get_album(self, album_id: str) -> ImmichAlbum:
        """Get a single album by ID with full asset list.

        Calls ``GET /albums/{id}``.

        Args:
            album_id: Immich album UUID.

        Returns:
            Parsed album with assets populated.
        """
        data = await self._get(f"albums/{album_id}")
        return ImmichAlbum.model_validate(data)

    async def create_album(self, album_data: dict[str, Any]) -> ImmichAlbum:
        """Create a new album.

        Calls ``POST /albums``.

        Args:
            album_data: Album creation payload (e.g. ``albumName``).

        Returns:
            Created album.
        """
        data = await self._post("albums", json_data=album_data)
        return ImmichAlbum.model_validate(data)

    # -- Assets / Search --

    async def search_assets(self, filters: dict[str, Any]) -> list[ImmichAsset]:
        """Search assets using metadata filters.

        Calls ``POST /search/metadata``.

        Args:
            filters: Search filter payload.

        Returns:
            List of matching assets.
        """
        data = await self._post("search/metadata", json_data=filters)
        # The search response wraps assets in a nested structure
        if isinstance(data, dict):
            assets_data = data.get("assets", data)
        else:
            assets_data = data
        if isinstance(assets_data, dict):
            items = assets_data.get("items", [])
        else:
            items = assets_data
        return [ImmichAsset.model_validate(item) for item in items]

    async def get_asset_thumbnail(
        self,
        asset_id: str,
        *,
        size: str = "preview",
    ) -> bytes:
        """Download an asset thumbnail.

        Calls ``GET /assets/{id}/thumbnail``.

        Args:
            asset_id: Immich asset UUID.
            size: Thumbnail size (``preview`` or ``thumbnail``).

        Returns:
            Raw thumbnail bytes.
        """
        return await self._get_bytes(
            f"assets/{asset_id}/thumbnail",
            params={"size": size},
        )

    # -- Shared Links --

    async def get_shared_links(self) -> list[ImmichSharedLink]:
        """Get all shared links.

        Calls ``GET /shared-links``.

        Returns:
            List of shared links.
        """
        data = await self._get("shared-links")
        return [ImmichSharedLink.model_validate(item) for item in data]

    async def create_shared_link(self, link_data: dict[str, Any]) -> ImmichSharedLink:
        """Create a new shared link.

        Calls ``POST /shared-links``.

        Args:
            link_data: Shared link creation payload.

        Returns:
            Created shared link.
        """
        data = await self._post("shared-links", json_data=link_data)
        return ImmichSharedLink.model_validate(data)

    # -- Internal HTTP helpers --

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a GET request and return parsed JSON.

        Args:
            path: API path relative to base URL (e.g. ``server/about``).
                Must NOT start with ``/``.
            params: Optional query parameters.

        Returns:
            Parsed JSON response body.
        """
        response = await self._client.get(path, params=params)
        self._raise_for_status(response)
        return response.json()

    async def _get_bytes(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """Execute a GET request and return raw response bytes.

        Args:
            path: API path relative to base URL.
            params: Optional query parameters.

        Returns:
            Raw response content.
        """
        response = await self._client.get(
            path,
            params=params,
            headers={"Accept": "application/octet-stream"},
        )
        self._raise_for_status(response)
        return response.content

    async def _post(
        self,
        path: str,
        json_data: dict[str, Any],
    ) -> Any:
        """Execute a POST request and return parsed JSON.

        Args:
            path: API path relative to base URL.
            json_data: JSON payload.

        Returns:
            Parsed JSON response body.
        """
        response = await self._client.post(path, json=json_data)
        self._raise_for_status(response)
        return response.json()

    async def _put(
        self,
        path: str,
        json_data: dict[str, Any],
    ) -> Any:
        """Execute a PUT request and return parsed JSON.

        Args:
            path: API path relative to base URL.
            json_data: JSON payload.

        Returns:
            Parsed JSON response body.
        """
        response = await self._client.put(path, json=json_data)
        self._raise_for_status(response)
        return response.json()

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Raise ``ImmichApiError`` for non-2xx responses.

        Args:
            response: The HTTP response to check.

        Raises:
            ImmichApiError: For any non-2xx status code.
        """
        if response.is_success:
            return

        if response.status_code == 401:
            raise ImmichApiError(
                "Immich authentication failed (invalid API key)",
                status_code=401,
            )

        # Try to extract error message from response body
        try:
            body = response.json()
            message = body.get("message", response.reason_phrase or "Unknown error")
        except Exception:  # noqa: BLE001
            message = response.reason_phrase or f"HTTP {response.status_code}"

        raise ImmichApiError(
            f"Immich API error: {message}",
            status_code=response.status_code,
        )

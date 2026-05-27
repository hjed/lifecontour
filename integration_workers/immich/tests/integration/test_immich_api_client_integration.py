"""Integration tests for the ImmichApiClient using httpx MockTransport.

These tests verify full request-response cycles with realistic API payloads,
testing the entire flow from client method → HTTP request → response parsing.
"""

import json
from typing import Any

import httpx
import pytest

from immich_api_client import ImmichApiClient, ImmichApiError
from immich_models import (
    ImmichAlbum,
    ImmichAsset,
    ImmichPeopleResponse,
    ImmichPerson,
    ImmichServerInfo,
    ImmichSharedLink,
)

# ---------------------------------------------------------------------------
# Realistic API response fixtures (matching Immich OpenAPI spec)
# ---------------------------------------------------------------------------

API_KEY = "integration-test-api-key"
BASE_URL = "https://immich.example.com/api/"

REALISTIC_SERVER_ABOUT = {
    "version": "v1.134.0",
    "versionUrl": "https://github.com/immich-app/immich/releases/tag/v1.134.0",
    "licensed": True,
    "build": "abc1234",
    "buildUrl": "https://github.com/immich-app/immich/commit/abc1234",
    "repository": "immich-app/immich",
    "repositoryUrl": "https://github.com/immich-app/immich",
    "sourceRef": "v1.134.0",
    "sourceCommit": "abc1234",
    "sourceUrl": "https://github.com/immich-app/immich/tree/v1.134.0",
    "nodejs": "22.15.0",
    "exiftool": "12.50",
    "ffmpeg": "6.0",
    "imagemagick": "7.1.1-15",
    "libvips": "8.14.2",
}

REALISTIC_PERSON = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Alice Johnson",
    "birthDate": "1990-05-15",
    "thumbnailPath": "/api/people/550e8400/thumbnail",
    "isHidden": False,
    "color": "#FF5733",
    "isFavorite": True,
    "updatedAt": "2024-06-15T12:00:00.000Z",
}

REALISTIC_PERSON_NO_BIRTHDAY = {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "name": "",
    "birthDate": None,
    "thumbnailPath": "/api/people/660e8400/thumbnail",
    "isHidden": True,
}

REALISTIC_PEOPLE_RESPONSE = {
    "people": [REALISTIC_PERSON, REALISTIC_PERSON_NO_BIRTHDAY],
    "total": 42,
    "hidden": 5,
    "hasNextPage": True,
}

REALISTIC_ASSET = {
    "id": "770e8400-e29b-41d4-a716-446655440002",
    "type": "IMAGE",
    "originalFileName": "DSC_0042.jpg",
    "takenAt": "2024-03-15T14:30:00.000Z",
    "people": [
        {"id": "550e8400-e29b-41d4-a716-446655440000", "name": "Alice Johnson"},
    ],
    "exifInfo": {
        "dateTimeOriginal": "2024-03-15T14:30:00.000Z",
        "timezone": "Australia/Sydney",
        "make": "Nikon",
        "model": "Z6",
        "lensModel": "NIKKOR Z 24-70mm f/4 S",
    },
    "originalPath": "/uploads/library/alice/2024/03/DSC_0042.jpg",
    "thumbhash": "abc123",
    "checksum": "def456",
}

REALISTIC_ALBUM = {
    "id": "880e8400-e29b-41d4-a716-446655440003",
    "albumName": "Japan Trip 2024",
    "description": "Two weeks in Tokyo and Kyoto",
    "albumThumbnailAssetId": "770e8400-e29b-41d4-a716-446655440002",
    "assetCount": 342,
    "updatedAt": "2024-06-20T08:30:00.000Z",
    "createdAt": "2024-03-01T00:00:00.000Z",
    "shared": True,
    "hasSharedLink": True,
    "isActivityEnabled": True,
    "albumUsers": [
        {
            "user": {"id": "user-1", "name": "Alice"},
            "role": "owner",
        }
    ],
}

REALISTIC_ALBUM_WITH_ASSETS = {
    **REALISTIC_ALBUM,
    "assets": [REALISTIC_ASSET],
}

REALISTIC_SHARED_LINK: dict[str, Any] = {
    "id": "990e8400-e29b-41d4-a716-446655440004",
    "key": "xYz789AbCdEfGhIjKlMnOpQrStUvWx",
    "type": "ALBUM",
    "createdAt": "2024-06-20T10:00:00.000Z",
    "description": "Family holiday photos",
    "album": REALISTIC_ALBUM,
    "assets": [],
    "password": None,
    "expiresAt": "2025-06-20T10:00:00.000Z",
    "allowDownload": True,
    "allowUpload": False,
    "showMetadata": True,
}

REALISTIC_SEARCH_RESPONSE = {
    "assets": {
        "items": [REALISTIC_ASSET],
        "nextPage": "page-2-token",
    }
}

THUMBNAIL_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10"
    b"\x00\x00\x00\x10\x08\x06\x00\x00\x00\x1f\xf3\xffa"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_router() -> dict[tuple[str, str], Any]:
    """Build a path→response mapping for the mock transport."""
    return {
        ("GET", "/api/server/about"): (200, REALISTIC_SERVER_ABOUT),
        ("GET", "/api/people"): (200, REALISTIC_PEOPLE_RESPONSE),
        ("GET", "/api/people/550e8400-e29b-41d4-a716-446655440000"): (
            200,
            REALISTIC_PERSON,
        ),
        ("PUT", "/api/people/550e8400-e29b-41d4-a716-446655440000"): (
            200,
            REALISTIC_PERSON,
        ),
        ("GET", "/api/albums"): (200, [REALISTIC_ALBUM]),
        ("GET", "/api/albums/880e8400-e29b-41d4-a716-446655440003"): (
            200,
            REALISTIC_ALBUM_WITH_ASSETS,
        ),
        ("POST", "/api/albums"): (201, REALISTIC_ALBUM),
        ("POST", "/api/search/metadata"): (200, REALISTIC_SEARCH_RESPONSE),
        ("GET", "/api/shared-links"): (200, [REALISTIC_SHARED_LINK]),
        ("POST", "/api/shared-links"): (201, REALISTIC_SHARED_LINK),
    }


def _create_integration_client() -> ImmichApiClient:
    """Create an ImmichApiClient with a mock transport that routes requests."""
    routes = _build_router()

    # Track requests for assertion
    request_log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)

        # Thumbnail endpoints return bytes
        path = request.url.path
        if path.endswith("/thumbnail"):
            return httpx.Response(
                200,
                content=THUMBNAIL_BYTES,
                headers={"content-type": "image/jpeg"},
            )

        key = (request.method, path)
        if key in routes:
            status, body = routes[key]
            return httpx.Response(status, json=body)

        # Default: 404
        return httpx.Response(404, json={"message": "Not found"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        base_url=BASE_URL,
        headers={
            "x-api-key": API_KEY,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        transport=transport,
    )

    client = ImmichApiClient(http_client)
    # Attach request log for assertions
    client._request_log = request_log  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestServerInfoIntegration:
    """Integration test for server info endpoint."""

    async def test_full_cycle(self) -> None:
        """Get server info returns parsed result with extra fields ignored."""
        client = _create_integration_client()
        info = await client.get_server_info()

        assert isinstance(info, ImmichServerInfo)
        assert info.version == "v1.134.0"
        assert info.licensed is True

        # Verify API key was sent
        assert client._request_log[0].headers["x-api-key"] == API_KEY  # type: ignore[attr-defined]


@pytest.mark.asyncio
class TestPeopleIntegration:
    """Integration tests for people endpoints."""

    async def test_get_all_people(self) -> None:
        """Get all people returns paginated response."""
        client = _create_integration_client()
        result = await client.get_all_people()

        assert isinstance(result, ImmichPeopleResponse)
        assert len(result.people) == 2
        assert result.total == 42
        assert result.hidden == 5
        assert result.has_next_page is True

        # Verify named person
        alice = result.people[0]
        assert alice.name == "Alice Johnson"
        assert alice.birth_date == "1990-05-15"
        assert alice.is_hidden is False

        # Verify unnamed person
        unnamed = result.people[1]
        assert unnamed.name == ""
        assert unnamed.birth_date is None
        assert unnamed.is_hidden is True

    async def test_get_person(self) -> None:
        """Get single person returns parsed result."""
        client = _create_integration_client()
        person = await client.get_person("550e8400-e29b-41d4-a716-446655440000")

        assert isinstance(person, ImmichPerson)
        assert person.id == "550e8400-e29b-41d4-a716-446655440000"
        assert person.name == "Alice Johnson"

    async def test_update_person(self) -> None:
        """Update person sends PUT and returns parsed result."""
        client = _create_integration_client()
        result = await client.update_person(
            "550e8400-e29b-41d4-a716-446655440000",
            {"name": "Alice Smith", "birthDate": "1990-06-01"},
        )

        assert isinstance(result, ImmichPerson)
        # Verify the request was a PUT
        request = client._request_log[-1]  # type: ignore[attr-defined]
        assert request.method == "PUT"
        body = json.loads(request.content)
        assert body["name"] == "Alice Smith"

    async def test_get_person_thumbnail(self) -> None:
        """Get person thumbnail returns raw bytes."""
        client = _create_integration_client()
        result = await client.get_person_thumbnail(
            "550e8400-e29b-41d4-a716-446655440000"
        )

        assert isinstance(result, bytes)
        assert len(result) > 0


@pytest.mark.asyncio
class TestAlbumsIntegration:
    """Integration tests for album endpoints."""

    async def test_get_all_albums(self) -> None:
        """Get all albums returns list."""
        client = _create_integration_client()
        albums = await client.get_all_albums()

        assert len(albums) == 1
        assert isinstance(albums[0], ImmichAlbum)
        assert albums[0].album_name == "Japan Trip 2024"
        assert albums[0].asset_count == 342
        assert albums[0].shared is True

    async def test_get_album_with_assets(self) -> None:
        """Get single album includes full asset list."""
        client = _create_integration_client()
        album = await client.get_album("880e8400-e29b-41d4-a716-446655440003")

        assert isinstance(album, ImmichAlbum)
        assert len(album.assets) == 1
        assert album.assets[0].original_file_name == "DSC_0042.jpg"
        assert len(album.assets[0].people) == 1

    async def test_create_album(self) -> None:
        """Create album sends POST and returns parsed result."""
        client = _create_integration_client()
        album = await client.create_album(
            {"albumName": "New Album", "description": "Test"}
        )

        assert isinstance(album, ImmichAlbum)
        request = client._request_log[-1]  # type: ignore[attr-defined]
        assert request.method == "POST"


@pytest.mark.asyncio
class TestSearchAssetsIntegration:
    """Integration tests for asset search."""

    async def test_search_assets(self) -> None:
        """Search assets with filters returns parsed results."""
        client = _create_integration_client()
        assets = await client.search_assets(
            {"personIds": ["550e8400-e29b-41d4-a716-446655440000"]}
        )

        assert len(assets) == 1
        assert isinstance(assets[0], ImmichAsset)
        assert assets[0].original_file_name == "DSC_0042.jpg"
        assert assets[0].exif_info is not None
        assert assets[0].exif_info.timezone == "Australia/Sydney"

    async def test_get_asset_thumbnail(self) -> None:
        """Get asset thumbnail returns raw bytes."""
        client = _create_integration_client()
        result = await client.get_asset_thumbnail(
            "770e8400-e29b-41d4-a716-446655440002"
        )

        assert isinstance(result, bytes)
        assert len(result) > 0


@pytest.mark.asyncio
class TestSharedLinksIntegration:
    """Integration tests for shared link endpoints."""

    async def test_get_shared_links(self) -> None:
        """Get shared links returns list."""
        client = _create_integration_client()
        links = await client.get_shared_links()

        assert len(links) == 1
        assert isinstance(links[0], ImmichSharedLink)
        assert links[0].key == "xYz789AbCdEfGhIjKlMnOpQrStUvWx"
        assert links[0].type == "ALBUM"
        assert links[0].album is not None
        assert links[0].allow_download is True

    async def test_create_shared_link(self) -> None:
        """Create shared link sends POST and returns parsed result."""
        client = _create_integration_client()
        link = await client.create_shared_link(
            {"type": "ALBUM", "albumId": "album-1", "allowDownload": True}
        )

        assert isinstance(link, ImmichSharedLink)
        request = client._request_log[-1]  # type: ignore[attr-defined]
        assert request.method == "POST"


@pytest.mark.asyncio
class TestErrorHandlingIntegration:
    """Integration tests for error handling across the full flow."""

    async def test_404_for_unknown_person(self) -> None:
        """Requesting a non-existent person raises ImmichApiError."""
        client = _create_integration_client()

        with pytest.raises(ImmichApiError) as exc_info:
            await client.get_person("nonexistent-uuid")

        assert exc_info.value.status_code == 404

    async def test_404_for_unknown_album(self) -> None:
        """Requesting a non-existent album raises ImmichApiError."""
        client = _create_integration_client()

        with pytest.raises(ImmichApiError) as exc_info:
            await client.get_album("nonexistent-album-uuid")

        assert exc_info.value.status_code == 404

    async def test_401_authentication_error(self) -> None:
        """401 response raises ImmichApiError with auth message."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "Unauthorized"})

        transport = httpx.MockTransport(handler)
        http_client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"x-api-key": "invalid-key"},
            transport=transport,
        )
        client = ImmichApiClient(http_client)

        with pytest.raises(ImmichApiError) as exc_info:
            await client.get_server_info()

        assert exc_info.value.status_code == 401
        assert "authentication failed" in str(exc_info.value).lower()

    async def test_500_server_error(self) -> None:
        """500 response raises ImmichApiError."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "Internal server error"})

        transport = httpx.MockTransport(handler)
        http_client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"x-api-key": API_KEY},
            transport=transport,
        )
        client = ImmichApiClient(http_client)

        with pytest.raises(ImmichApiError) as exc_info:
            await client.get_all_people()

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestApiKeyPropagation:
    """Verify API key header is present on all request types."""

    async def test_all_requests_include_api_key(self) -> None:
        """Every request made by the client includes x-api-key header."""
        client = _create_integration_client()

        # Make various types of requests
        await client.get_server_info()
        await client.get_all_people()
        await client.get_person("550e8400-e29b-41d4-a716-446655440000")
        await client.get_all_albums()

        # Verify all requests had the API key
        for request in client._request_log:  # type: ignore[attr-defined]
            assert request.headers.get("x-api-key") == API_KEY, (
                f"Missing API key on {request.method} {request.url.path}"
            )

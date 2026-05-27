"""Unit tests for the ImmichApiClient.

Uses httpx.MockTransport to verify:
- API key header injection on every request
- Correct HTTP methods and paths
- Response model parsing
- Error handling (401, 404, 500)
"""

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
# Test fixtures / helpers
# ---------------------------------------------------------------------------

API_KEY = "test-api-key-12345"
BASE_URL = "https://immich.example.com/api/"

# Sample JSON payloads matching the Immich OpenAPI spec (camelCase)
SERVER_INFO_JSON = {"version": "v1.106.4", "licensed": False}

PERSON_JSON = {
    "id": "person-uuid-1",
    "name": "Alice Smith",
    "birthDate": "1990-05-15",
    "thumbnailPath": "/person/uuid/thumb.jpg",
    "isHidden": False,
}

PEOPLE_RESPONSE_JSON = {
    "people": [PERSON_JSON],
    "total": 1,
    "hidden": 0,
    "hasNextPage": False,
}

ALBUM_JSON = {
    "id": "album-uuid-1",
    "albumName": "Holiday 2024",
    "description": "Trip to Japan",
    "albumThumbnailAssetId": "asset-1",
    "assetCount": 3,
    "updatedAt": "2024-06-15T12:00:00.000Z",
    "shared": True,
}

ASSET_JSON = {
    "id": "asset-uuid-1",
    "type": "IMAGE",
    "originalFileName": "photo.jpg",
    "takenAt": "2024-01-15T10:30:00.000Z",
    "people": [{"id": "person-uuid-1", "name": "Alice"}],
    "exifInfo": {
        "dateTimeOriginal": "2024-01-15T10:30:00.000Z",
        "timezone": "Australia/Sydney",
    },
}

SEARCH_RESPONSE_JSON = {
    "assets": {
        "items": [ASSET_JSON],
        "nextPage": None,
    }
}

SHARED_LINK_JSON = {
    "id": "link-uuid-1",
    "key": "abc123key",
    "type": "ALBUM",
    "createdAt": "2024-03-10T08:00:00.000Z",
    "description": "Shared photos",
    "album": ALBUM_JSON,
    "assets": [],
    "allowDownload": True,
    "allowUpload": False,
}

THUMBNAIL_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _create_mock_handler(
    *,
    expected_path: str | None = None,
    expected_method: str = "GET",
    response_json: Any = None,
    response_bytes: bytes | None = None,
    status_code: int = 200,
    check_api_key: bool = True,
) -> httpx.MockTransport:
    """Create a MockTransport that validates requests and returns responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Verify API key header
        if check_api_key:
            assert request.headers.get("x-api-key") == API_KEY

        # Verify path
        if expected_path is not None:
            actual_path = request.url.path
            assert actual_path.endswith(expected_path), (
                f"Expected path ending with '{expected_path}', got '{actual_path}'"
            )

        # Verify method
        assert request.method == expected_method

        if response_bytes is not None:
            return httpx.Response(
                status_code,
                content=response_bytes,
                headers={"content-type": "application/octet-stream"},
            )

        return httpx.Response(
            status_code,
            json=response_json,
        )

    return httpx.MockTransport(handler)


def _create_client(transport: httpx.MockTransport) -> ImmichApiClient:
    """Create an ImmichApiClient with the given mock transport.

    Note: The underlying httpx.AsyncClient uses MockTransport, which
    holds no real connections. Callers should still call
    ``await client.close()`` when practical, but resource leaks are
    not a concern in this test context.
    """
    http_client = httpx.AsyncClient(
        base_url=BASE_URL,
        headers={
            "x-api-key": API_KEY,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        transport=transport,
    )
    return ImmichApiClient(http_client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestApiKeyHeaderInjection:
    """Verify x-api-key header is sent on every request."""

    async def test_api_key_on_get(self) -> None:
        """GET requests include the x-api-key header."""
        transport = _create_mock_handler(
            response_json=SERVER_INFO_JSON,
            check_api_key=True,
        )
        client = _create_client(transport)
        await client.get_server_info()

    async def test_api_key_on_post(self) -> None:
        """POST requests include the x-api-key header."""
        transport = _create_mock_handler(
            expected_method="POST",
            response_json=SEARCH_RESPONSE_JSON,
            check_api_key=True,
        )
        client = _create_client(transport)
        await client.search_assets({"personIds": ["p1"]})

    async def test_api_key_on_put(self) -> None:
        """PUT requests include the x-api-key header."""
        transport = _create_mock_handler(
            expected_method="PUT",
            response_json=PERSON_JSON,
            check_api_key=True,
        )
        client = _create_client(transport)
        await client.update_person("person-uuid-1", {"name": "Updated"})


@pytest.mark.asyncio
class TestErrorHandling:
    """Verify error handling for non-2xx responses."""

    async def test_401_raises_auth_error(self) -> None:
        """401 response raises ImmichApiError with auth message."""
        transport = _create_mock_handler(
            status_code=401,
            response_json={"message": "Unauthorized"},
        )
        client = _create_client(transport)

        with pytest.raises(ImmichApiError) as exc_info:
            await client.get_server_info()

        assert exc_info.value.status_code == 401
        assert "authentication failed" in str(exc_info.value).lower()

    async def test_404_raises_api_error(self) -> None:
        """404 response raises ImmichApiError."""
        transport = _create_mock_handler(
            status_code=404,
            response_json={"message": "Person not found"},
        )
        client = _create_client(transport)

        with pytest.raises(ImmichApiError) as exc_info:
            await client.get_person("nonexistent")

        assert exc_info.value.status_code == 404

    async def test_500_raises_api_error(self) -> None:
        """500 response raises ImmichApiError."""
        transport = _create_mock_handler(
            status_code=500,
            response_json={"message": "Internal server error"},
        )
        client = _create_client(transport)

        with pytest.raises(ImmichApiError) as exc_info:
            await client.get_all_albums()

        assert exc_info.value.status_code == 500

    async def test_error_without_json_body(self) -> None:
        """Non-JSON error response still raises ImmichApiError."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                502,
                content=b"Bad Gateway",
                headers={"content-type": "text/plain"},
            )

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        with pytest.raises(ImmichApiError) as exc_info:
            await client.get_server_info()

        assert exc_info.value.status_code == 502


@pytest.mark.asyncio
class TestGetServerInfo:
    """Tests for get_server_info()."""

    async def test_returns_parsed_model(self) -> None:
        """Response is parsed into ImmichServerInfo."""
        transport = _create_mock_handler(
            expected_path="/api/server/about",
            response_json=SERVER_INFO_JSON,
        )
        client = _create_client(transport)

        result = await client.get_server_info()

        assert isinstance(result, ImmichServerInfo)
        assert result.version == "v1.106.4"
        assert result.licensed is False


@pytest.mark.asyncio
class TestGetAllPeople:
    """Tests for get_all_people()."""

    async def test_returns_people_response(self) -> None:
        """Response is parsed into ImmichPeopleResponse."""
        transport = _create_mock_handler(
            expected_path="/api/people",
            response_json=PEOPLE_RESPONSE_JSON,
        )
        client = _create_client(transport)

        result = await client.get_all_people()

        assert isinstance(result, ImmichPeopleResponse)
        assert len(result.people) == 1
        assert result.people[0].name == "Alice Smith"
        assert result.total == 1

    async def test_passes_query_params(self) -> None:
        """Query parameters are passed to the API."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("withHidden") == "true"
            assert request.url.params.get("page") == "2"
            assert request.url.params.get("size") == "100"
            return httpx.Response(200, json=PEOPLE_RESPONSE_JSON)

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        await client.get_all_people(with_hidden=True, page=2, size=100)


@pytest.mark.asyncio
class TestGetPerson:
    """Tests for get_person()."""

    async def test_returns_person(self) -> None:
        """Response is parsed into ImmichPerson."""
        transport = _create_mock_handler(
            expected_path="/api/people/person-uuid-1",
            response_json=PERSON_JSON,
        )
        client = _create_client(transport)

        result = await client.get_person("person-uuid-1")

        assert isinstance(result, ImmichPerson)
        assert result.id == "person-uuid-1"
        assert result.birth_date == "1990-05-15"


@pytest.mark.asyncio
class TestUpdatePerson:
    """Tests for update_person()."""

    async def test_sends_put_with_payload(self) -> None:
        """PUT request is sent with the correct payload."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PUT"
            import json

            body = json.loads(request.content)
            assert body["name"] == "Alice Updated"
            assert body["birthDate"] == "1990-06-01"
            return httpx.Response(200, json=PERSON_JSON)

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        result = await client.update_person(
            "person-uuid-1",
            {"name": "Alice Updated", "birthDate": "1990-06-01"},
        )

        assert isinstance(result, ImmichPerson)


@pytest.mark.asyncio
class TestGetPersonThumbnail:
    """Tests for get_person_thumbnail()."""

    async def test_returns_bytes(self) -> None:
        """Thumbnail is returned as raw bytes."""
        transport = _create_mock_handler(
            expected_path="/api/people/person-uuid-1/thumbnail",
            response_bytes=THUMBNAIL_BYTES,
        )
        client = _create_client(transport)

        result = await client.get_person_thumbnail("person-uuid-1")

        assert isinstance(result, bytes)
        assert result == THUMBNAIL_BYTES
        await client.close()

    async def test_accept_header_override(self) -> None:
        """Binary requests override Accept header to application/octet-stream."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("accept") == "application/octet-stream"
            return httpx.Response(
                200,
                content=THUMBNAIL_BYTES,
                headers={"content-type": "image/jpeg"},
            )

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        await client.get_person_thumbnail("person-uuid-1")
        await client.close()


@pytest.mark.asyncio
class TestGetAllAlbums:
    """Tests for get_all_albums()."""

    async def test_returns_album_list(self) -> None:
        """Response is parsed into a list of ImmichAlbum."""
        transport = _create_mock_handler(
            expected_path="/api/albums",
            response_json=[ALBUM_JSON],
        )
        client = _create_client(transport)

        result = await client.get_all_albums()

        assert len(result) == 1
        assert isinstance(result[0], ImmichAlbum)
        assert result[0].album_name == "Holiday 2024"

    async def test_shared_filter_param(self) -> None:
        """shared parameter is sent as query string."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("shared") == "true"
            return httpx.Response(200, json=[])

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        await client.get_all_albums(shared=True)


@pytest.mark.asyncio
class TestGetAlbum:
    """Tests for get_album()."""

    async def test_returns_album(self) -> None:
        """Response is parsed into ImmichAlbum."""
        transport = _create_mock_handler(
            expected_path="/api/albums/album-uuid-1",
            response_json=ALBUM_JSON,
        )
        client = _create_client(transport)

        result = await client.get_album("album-uuid-1")

        assert isinstance(result, ImmichAlbum)
        assert result.id == "album-uuid-1"


@pytest.mark.asyncio
class TestCreateAlbum:
    """Tests for create_album()."""

    async def test_sends_post(self) -> None:
        """POST request is sent with album data."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            import json

            body = json.loads(request.content)
            assert body["albumName"] == "New Album"
            return httpx.Response(201, json=ALBUM_JSON)

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        result = await client.create_album({"albumName": "New Album"})

        assert isinstance(result, ImmichAlbum)


@pytest.mark.asyncio
class TestSearchAssets:
    """Tests for search_assets()."""

    async def test_returns_asset_list(self) -> None:
        """Response is parsed from the nested search response structure."""
        transport = _create_mock_handler(
            expected_method="POST",
            expected_path="/api/search/metadata",
            response_json=SEARCH_RESPONSE_JSON,
        )
        client = _create_client(transport)

        result = await client.search_assets({"personIds": ["person-uuid-1"]})

        assert len(result) == 1
        assert isinstance(result[0], ImmichAsset)
        assert result[0].id == "asset-uuid-1"

    async def test_sends_filter_payload(self) -> None:
        """Filter payload is sent in the POST body."""

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content)
            assert body["personIds"] == ["p1", "p2"]
            assert body["type"] == "IMAGE"
            return httpx.Response(200, json=SEARCH_RESPONSE_JSON)

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        await client.search_assets({"personIds": ["p1", "p2"], "type": "IMAGE"})


@pytest.mark.asyncio
class TestGetAssetThumbnail:
    """Tests for get_asset_thumbnail()."""

    async def test_returns_bytes(self) -> None:
        """Thumbnail is returned as raw bytes."""
        transport = _create_mock_handler(
            expected_path="/api/assets/asset-uuid-1/thumbnail",
            response_bytes=THUMBNAIL_BYTES,
        )
        client = _create_client(transport)

        result = await client.get_asset_thumbnail("asset-uuid-1")

        assert isinstance(result, bytes)

    async def test_size_param(self) -> None:
        """Size parameter is sent as query string."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("size") == "thumbnail"
            return httpx.Response(200, content=THUMBNAIL_BYTES)

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        await client.get_asset_thumbnail("asset-uuid-1", size="thumbnail")
        await client.close()

    async def test_accept_header_override(self) -> None:
        """Asset thumbnail requests use octet-stream Accept header."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("accept") == "application/octet-stream"
            return httpx.Response(
                200,
                content=THUMBNAIL_BYTES,
                headers={"content-type": "image/jpeg"},
            )

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        await client.get_asset_thumbnail("asset-uuid-1")
        await client.close()


@pytest.mark.asyncio
class TestGetSharedLinks:
    """Tests for get_shared_links()."""

    async def test_returns_shared_link_list(self) -> None:
        """Response is parsed into a list of ImmichSharedLink."""
        transport = _create_mock_handler(
            expected_path="/api/shared-links",
            response_json=[SHARED_LINK_JSON],
        )
        client = _create_client(transport)

        result = await client.get_shared_links()

        assert len(result) == 1
        assert isinstance(result[0], ImmichSharedLink)
        assert result[0].key == "abc123key"


@pytest.mark.asyncio
class TestCreateSharedLink:
    """Tests for create_shared_link()."""

    async def test_sends_post(self) -> None:
        """POST request is sent with link data."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            import json

            body = json.loads(request.content)
            assert body["type"] == "ALBUM"
            assert body["albumId"] == "album-uuid-1"
            return httpx.Response(201, json=SHARED_LINK_JSON)

        transport = httpx.MockTransport(handler)
        client = _create_client(transport)

        result = await client.create_shared_link(
            {"type": "ALBUM", "albumId": "album-uuid-1"}
        )

        assert isinstance(result, ImmichSharedLink)


@pytest.mark.asyncio
class TestFactoryMethod:
    """Tests for the create() factory method."""

    async def test_create_sets_headers(self) -> None:
        """Factory creates client with correct base URL and headers."""
        client = ImmichApiClient.create(
            base_url="https://immich.example.com",
            api_key="my-api-key",
        )

        # Verify headers on the underlying client
        assert client._client.headers.get("x-api-key") == "my-api-key"
        assert str(client._client.base_url) == "https://immich.example.com/api/"

        await client.close()

    async def test_create_strips_trailing_slash(self) -> None:
        """Factory strips trailing slash from base URL."""
        client = ImmichApiClient.create(
            base_url="https://immich.example.com/",
            api_key="key",
        )

        assert str(client._client.base_url) == "https://immich.example.com/api/"
        await client.close()

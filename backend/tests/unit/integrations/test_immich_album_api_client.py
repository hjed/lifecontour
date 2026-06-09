"""Unit tests for the backend Immich album API client.

The client talks to Immich directly (the backend cannot import the isolated
worker package), mirroring the avatar/album-cover proxies. These tests use an
``httpx.MockTransport`` to assert the request that is sent (path, headers,
payload) and to drive error handling, without any network access.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.integrations.immich_album_api_client import (
    ImmichAlbumApiClient,
    ImmichAlbumApiError,
)

SERVER_URL = "https://immich.example.com"
API_KEY = "secret-key"


def _client_with(handler: Any) -> ImmichAlbumApiClient:
    """Build a client whose HTTP layer is driven by ``handler``."""
    return ImmichAlbumApiClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_search_metadata_sends_taken_after_before_and_unwraps_items() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["api_key"] = request.headers.get("x-api-key")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "assets": {
                    "total": 2,
                    "count": 2,
                    "items": [
                        {"id": "asset-1", "originalFileName": "a.jpg"},
                        {"id": "asset-2", "originalFileName": "b.jpg"},
                    ],
                }
            },
        )

    client = _client_with(handler)
    items = await client.search_metadata(
        SERVER_URL,
        API_KEY,
        taken_after="2026-01-14T13:00:00+00:00",
        taken_before="2026-01-15T12:59:59.999999+00:00",
    )

    assert captured["method"] == "POST"
    assert captured["url"] == f"{SERVER_URL}/api/search/metadata"
    assert captured["api_key"] == API_KEY
    assert captured["body"]["takenAfter"] == "2026-01-14T13:00:00+00:00"
    assert captured["body"]["takenBefore"] == "2026-01-15T12:59:59.999999+00:00"
    assert [a["id"] for a in items] == ["asset-1", "asset-2"]


@pytest.mark.asyncio
async def test_create_album_sends_album_name_and_asset_ids() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={"id": "album-1", "albumName": "Trip", "assetCount": 2},
        )

    client = _client_with(handler)
    album = await client.create_album(
        SERVER_URL, API_KEY, album_name="Trip", asset_ids=["asset-1", "asset-2"]
    )

    assert captured["url"] == f"{SERVER_URL}/api/albums"
    assert captured["body"] == {"albumName": "Trip", "assetIds": ["asset-1", "asset-2"]}
    assert album["id"] == "album-1"


@pytest.mark.asyncio
async def test_create_shared_link_sends_album_type_and_id() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "link-1", "key": "abc123"})

    client = _client_with(handler)
    link = await client.create_shared_link(SERVER_URL, API_KEY, album_id="album-1")

    assert captured["url"] == f"{SERVER_URL}/api/shared-links"
    assert captured["body"] == {"type": "ALBUM", "albumId": "album-1"}
    assert link["key"] == "abc123"


@pytest.mark.asyncio
async def test_invalid_scheme_rejected_before_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    client = _client_with(handler)
    with pytest.raises(ImmichAlbumApiError, match="scheme"):
        await client.create_album(
            "file:///etc/passwd", API_KEY, album_name="x", asset_ids=[]
        )
    assert called is False


@pytest.mark.parametrize("status_code", [401, 404, 500])
@pytest.mark.asyncio
async def test_http_errors_raise_api_error(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "boom"})

    client = _client_with(handler)
    with pytest.raises(ImmichAlbumApiError) as exc_info:
        await client.create_album(SERVER_URL, API_KEY, album_name="x", asset_ids=["a"])
    assert exc_info.value.status_code == status_code


@pytest.mark.asyncio
async def test_connection_error_raises_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    client = _client_with(handler)
    with pytest.raises(ImmichAlbumApiError):
        await client.search_metadata(
            SERVER_URL, API_KEY, taken_after="a", taken_before="b"
        )

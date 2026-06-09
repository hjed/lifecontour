"""Unit tests for ``AssetThumbnailProxyService``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.core.integrations.immich.asset_thumbnail_proxy_service import (
    AssetThumbnailNotFoundError,
    AssetThumbnailProxyService,
)

SERVER_URL = "https://immich.example.com"
API_KEY = "key"


def _service(credentials: tuple[str | None, str | None]) -> AssetThumbnailProxyService:
    token_service = MagicMock()
    token_service.get_credentials = AsyncMock(return_value=credentials)
    return AssetThumbnailProxyService(immich_token_service=token_service)


@pytest.mark.asyncio
async def test_returns_thumbnail_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service((SERVER_URL, API_KEY))

    async def fake_fetch(
        server_url: str, api_key: str, asset_id: str
    ) -> tuple[bytes, str]:
        assert server_url == SERVER_URL
        assert asset_id == "asset-1"
        return (b"jpegbytes", "image/jpeg")

    monkeypatch.setattr(service, "_fetch_thumbnail", staticmethod(fake_fetch))

    data, content_type = await service.get_thumbnail_bytes("asset-1", "user-1")

    assert data == b"jpegbytes"
    assert content_type == "image/jpeg"


@pytest.mark.asyncio
async def test_not_connected_raises() -> None:
    service = _service((None, None))

    with pytest.raises(AssetThumbnailNotFoundError):
        await service.get_thumbnail_bytes("asset-1", "user-1")


@pytest.mark.asyncio
async def test_invalid_scheme_raises() -> None:
    with pytest.raises(AssetThumbnailNotFoundError, match="scheme"):
        await AssetThumbnailProxyService._fetch_thumbnail(
            "file:///etc", API_KEY, "asset-1"
        )


@pytest.mark.asyncio
async def test_http_error_raises() -> None:
    import respx

    with respx.mock:
        respx.get(f"{SERVER_URL}/api/assets/asset-1/thumbnail").mock(
            return_value=httpx.Response(404)
        )
        with pytest.raises(AssetThumbnailNotFoundError):
            await AssetThumbnailProxyService._fetch_thumbnail(
                SERVER_URL, API_KEY, "asset-1"
            )

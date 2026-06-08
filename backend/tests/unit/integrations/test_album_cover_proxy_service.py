"""Unit tests for the AlbumCoverProxyService.

Mirrors the AvatarProxyService tests: the service resolves the album cover
asset for a journal, fetches credentials, and streams the thumbnail from Immich
while keeping the server URL and API key hidden from the browser.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.integrations.album_cover_proxy_service import (
    AlbumCoverNotFoundError,
    AlbumCoverProxyService,
)


@pytest.fixture
def mock_album_repo() -> AsyncMock:
    """Provide a mock AlbumSyncReadRepository."""
    return AsyncMock()


@pytest.fixture
def mock_token_service() -> AsyncMock:
    """Provide a mock ImmichTokenService."""
    return AsyncMock()


@pytest.fixture
def service(
    mock_album_repo: AsyncMock,
    mock_token_service: AsyncMock,
) -> AlbumCoverProxyService:
    """Provide an AlbumCoverProxyService with mocked dependencies."""
    return AlbumCoverProxyService(
        album_repo=mock_album_repo,
        immich_token_service=mock_token_service,
    )


class TestFetchThumbnail:
    """Tests for the asset-thumbnail fetch path."""

    async def test_fetches_bytes_and_content_type_from_assets_endpoint(self) -> None:
        fake_image = b"\xff\xd8\xff\xe0fake-jpeg-data"

        with patch(
            "app.core.integrations.album_cover_proxy_service.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = fake_image
            mock_response.headers = {"content-type": "image/webp"}
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            image_bytes, content_type = await AlbumCoverProxyService._fetch_thumbnail(
                "https://immich.example.com",
                "test-api-key",
                "asset-uuid",
            )

            assert image_bytes == fake_image
            assert content_type == "image/webp"
            call_args = mock_client.get.call_args
            assert "assets/asset-uuid/thumbnail" in call_args[0][0]

    async def test_defaults_to_jpeg_content_type(self) -> None:
        with patch(
            "app.core.integrations.album_cover_proxy_service.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = b"data"
            mock_response.headers = {}
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            _, content_type = await AlbumCoverProxyService._fetch_thumbnail(
                "https://immich.example.com", "k", "asset-uuid"
            )

            assert content_type == "image/jpeg"

    async def test_raises_on_http_error(self) -> None:
        with patch(
            "app.core.integrations.album_cover_proxy_service.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Not found",
                request=httpx.Request("GET", "http://test"),
                response=mock_response,
            )
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            with pytest.raises(AlbumCoverNotFoundError):
                await AlbumCoverProxyService._fetch_thumbnail(
                    "https://immich.example.com", "k", "asset-uuid"
                )

    async def test_raises_on_connection_error(self) -> None:
        with patch(
            "app.core.integrations.album_cover_proxy_service.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.RequestError("boom")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            with pytest.raises(AlbumCoverNotFoundError):
                await AlbumCoverProxyService._fetch_thumbnail(
                    "https://immich.example.com", "k", "asset-uuid"
                )

    async def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(AlbumCoverNotFoundError, match="Invalid.*scheme"):
            await AlbumCoverProxyService._fetch_thumbnail(
                "file:///etc/passwd", "k", "asset-uuid"
            )


class TestGetCoverBytes:
    """End-to-end resolution for get_cover_bytes."""

    async def test_raises_when_journal_not_an_album(
        self,
        service: AlbumCoverProxyService,
        mock_album_repo: AsyncMock,
    ) -> None:
        mock_album_repo.find_cover_asset.return_value = None

        with pytest.raises(AlbumCoverNotFoundError):
            await service.get_cover_bytes(journal_id=7, user_id="user1")

    async def test_raises_when_no_thumbnail_asset(
        self,
        service: AlbumCoverProxyService,
        mock_album_repo: AsyncMock,
    ) -> None:
        # Album linked but no cover asset id recorded.
        mock_album_repo.find_cover_asset.return_value = ("album-1", None)

        with pytest.raises(AlbumCoverNotFoundError):
            await service.get_cover_bytes(journal_id=7, user_id="user1")

    async def test_raises_when_no_credentials(
        self,
        service: AlbumCoverProxyService,
        mock_album_repo: AsyncMock,
        mock_token_service: AsyncMock,
    ) -> None:
        mock_album_repo.find_cover_asset.return_value = ("album-1", "asset-uuid")
        mock_token_service.get_credentials.side_effect = Exception("Not found")

        with pytest.raises(AlbumCoverNotFoundError, match="not configured"):
            await service.get_cover_bytes(journal_id=7, user_id="user1")

    async def test_returns_bytes_and_content_type(
        self,
        service: AlbumCoverProxyService,
        mock_album_repo: AsyncMock,
        mock_token_service: AsyncMock,
    ) -> None:
        mock_album_repo.find_cover_asset.return_value = ("album-1", "asset-uuid")
        mock_token_service.get_credentials.return_value = (
            "https://immich.example.com",
            "test-api-key",
        )

        fake_image = b"\xff\xd8\xff\xe0fake-jpeg-data"
        with patch(
            "app.core.integrations.album_cover_proxy_service.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = fake_image
            mock_response.headers = {"content-type": "image/png"}
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            image_bytes, content_type = await service.get_cover_bytes(
                journal_id=7, user_id="user1"
            )

            assert image_bytes == fake_image
            assert content_type == "image/png"

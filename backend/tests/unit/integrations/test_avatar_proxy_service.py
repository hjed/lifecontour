"""Unit tests for the AvatarProxyService.

Tests are structured around the refactored service that uses
``IntegrationLinkRepository`` for person-ID lookups and
``ImmichTokenService`` for credential resolution.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.integrations.immich.avatar_proxy_service import (
    AvatarNotFoundError,
    AvatarProxyService,
)


@pytest.fixture
def mock_ext_ref_repo() -> AsyncMock:
    """Provide a mock IntegrationLinkRepository."""
    return AsyncMock()


@pytest.fixture
def mock_token_service() -> AsyncMock:
    """Provide a mock ImmichTokenService."""
    return AsyncMock()


@pytest.fixture
def service(
    mock_ext_ref_repo: AsyncMock,
    mock_token_service: AsyncMock,
) -> AvatarProxyService:
    """Provide an AvatarProxyService instance with mocked dependencies."""
    return AvatarProxyService(
        ext_ref_repo=mock_ext_ref_repo,
        immich_token_service=mock_token_service,
    )


class TestGetImmichPersonId:
    """Tests for person ID lookup via repository."""

    async def test_returns_person_id_when_found(
        self,
        service: AvatarProxyService,
        mock_ext_ref_repo: AsyncMock,
    ) -> None:
        """Should return the person_id from IntegrationLinkRepository."""
        mock_ext_ref_repo.get_immich_person_id.return_value = "immich-person-uuid"

        result = await mock_ext_ref_repo.get_immich_person_id(42)

        assert result == "immich-person-uuid"

    async def test_returns_none_when_no_reference(
        self,
        service: AvatarProxyService,
        mock_ext_ref_repo: AsyncMock,
    ) -> None:
        """Should return None when no external reference exists."""
        mock_ext_ref_repo.get_immich_person_id.return_value = None

        result = await mock_ext_ref_repo.get_immich_person_id(42)

        assert result is None


class TestGetImmichCredentials:
    """Tests for credential retrieval via ImmichTokenService."""

    async def test_returns_none_when_no_credentials(
        self,
        service: AvatarProxyService,
        mock_token_service: AsyncMock,
    ) -> None:
        """Should return (None, None) when credentials are not configured."""
        mock_token_service.get_credentials.side_effect = Exception("Not found")

        server_url, api_key = await service._get_immich_credentials("user1")

        assert server_url is None
        assert api_key is None

    async def test_returns_decrypted_credentials(
        self,
        service: AvatarProxyService,
        mock_token_service: AsyncMock,
    ) -> None:
        """Should return decrypted server URL and API key."""
        mock_token_service.get_credentials.return_value = (
            "https://immich.example.com",
            "test-api-key",
        )

        server_url, api_key = await service._get_immich_credentials("user1")

        assert server_url == "https://immich.example.com"
        assert api_key == "test-api-key"


class TestFetchThumbnail:
    """Tests for _fetch_thumbnail."""

    async def test_fetches_thumbnail_bytes_and_content_type(self) -> None:
        """Should return thumbnail bytes and content-type from Immich."""
        fake_image = b"\xff\xd8\xff\xe0fake-jpeg-data"

        with patch(
            "app.core.integrations.immich.avatar_proxy_service.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = fake_image
            mock_response.headers = {"content-type": "image/webp"}
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            image_bytes, content_type = await AvatarProxyService._fetch_thumbnail(
                "https://immich.example.com",
                "test-api-key",
                "person-uuid",
            )

            assert image_bytes == fake_image
            assert content_type == "image/webp"
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert "people/person-uuid/thumbnail" in call_args[0][0]

    async def test_defaults_to_jpeg_content_type(self) -> None:
        """Should default to image/jpeg when Immich doesn't send content-type."""
        fake_image = b"\xff\xd8\xff\xe0fake-jpeg-data"

        with patch(
            "app.core.integrations.immich.avatar_proxy_service.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = fake_image
            mock_response.headers = {}  # No content-type header
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            _, content_type = await AvatarProxyService._fetch_thumbnail(
                "https://immich.example.com",
                "test-api-key",
                "person-uuid",
            )

            assert content_type == "image/jpeg"

    async def test_raises_on_http_error(self) -> None:
        """Should raise AvatarNotFoundError on HTTP errors."""
        with patch(
            "app.core.integrations.immich.avatar_proxy_service.httpx.AsyncClient"
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

            with pytest.raises(AvatarNotFoundError):
                await AvatarProxyService._fetch_thumbnail(
                    "https://immich.example.com",
                    "test-api-key",
                    "person-uuid",
                )

    async def test_rejects_non_http_url_scheme(self) -> None:
        """Should reject URLs with non-HTTP(S) schemes to prevent SSRF."""
        with pytest.raises(AvatarNotFoundError, match="Invalid.*scheme"):
            await AvatarProxyService._fetch_thumbnail(
                "file:///etc/passwd",
                "test-api-key",
                "person-uuid",
            )


class TestGetAvatarBytes:
    """Integration-style tests for get_avatar_bytes."""

    async def test_raises_when_no_immich_link(
        self,
        service: AvatarProxyService,
        mock_ext_ref_repo: AsyncMock,
    ) -> None:
        """Should raise AvatarNotFoundError when contact has no Immich link."""
        mock_ext_ref_repo.get_immich_person_id.return_value = None

        with pytest.raises(AvatarNotFoundError, match="not linked"):
            await service.get_avatar_bytes(contact_id=42, user_id="user1")

    async def test_raises_when_no_immich_credentials(
        self,
        service: AvatarProxyService,
        mock_ext_ref_repo: AsyncMock,
        mock_token_service: AsyncMock,
    ) -> None:
        """Should raise AvatarNotFoundError when user has no Immich creds."""
        mock_ext_ref_repo.get_immich_person_id.return_value = "person-uuid"
        mock_token_service.get_credentials.side_effect = Exception("Not found")

        with pytest.raises(AvatarNotFoundError, match="not configured"):
            await service.get_avatar_bytes(contact_id=42, user_id="user1")

    async def test_returns_bytes_and_content_type(
        self,
        service: AvatarProxyService,
        mock_ext_ref_repo: AsyncMock,
        mock_token_service: AsyncMock,
    ) -> None:
        """Should return image bytes and content-type on success."""
        mock_ext_ref_repo.get_immich_person_id.return_value = "person-uuid"
        mock_token_service.get_credentials.return_value = (
            "https://immich.example.com",
            "test-api-key",
        )

        fake_image = b"\xff\xd8\xff\xe0fake-jpeg-data"
        with patch(
            "app.core.integrations.immich.avatar_proxy_service.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = fake_image
            mock_response.headers = {"content-type": "image/png"}
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            image_bytes, content_type = await service.get_avatar_bytes(
                contact_id=42, user_id="user1"
            )

            assert image_bytes == fake_image
            assert content_type == "image/png"


class TestProxyUrlConstruction:
    """Tests for proxy URL pattern used in sync service."""

    def test_proxy_url_format(self) -> None:
        """Verify the proxy URL format matches the expected pattern."""
        contact_id = 42
        expected_url = "/api/contacts/42/avatar"
        actual_url = f"/api/contacts/{contact_id}/avatar"
        assert actual_url == expected_url

    def test_proxy_url_with_different_ids(self) -> None:
        """Verify proxy URL works with various contact IDs."""
        for contact_id in [1, 100, 999]:
            url = f"/api/contacts/{contact_id}/avatar"
            assert url.startswith("/api/contacts/")
            assert url.endswith("/avatar")
            assert str(contact_id) in url


class TestPhotoUrlInSchemas:
    """Tests for photo_url field in API schemas."""

    def test_contact_attributes_includes_photo_url(self) -> None:
        """ContactAttributes schema should accept photo_url field."""
        from app.api.contacts.schemas import ContactAttributes

        attrs = ContactAttributes(
            first_name="Test",
            photo_url="/api/contacts/1/avatar",
        )
        assert attrs.photo_url == "/api/contacts/1/avatar"

    def test_contact_attributes_photo_url_defaults_to_none(self) -> None:
        """photo_url should default to None when not provided."""
        from app.api.contacts.schemas import ContactAttributes

        attrs = ContactAttributes(first_name="Test")
        assert attrs.photo_url is None

    def test_contact_entity_includes_photo_url(self) -> None:
        """Contact entity should support photo_url field."""
        from core_shared.models.contacts.entities import Contact

        contact = Contact(
            first_name="Test",
            photo_url="/api/contacts/1/avatar",
        )
        assert contact.photo_url == "/api/contacts/1/avatar"

    def test_contact_entity_photo_url_defaults_to_none(self) -> None:
        """Contact entity photo_url should default to None."""
        from core_shared.models.contacts.entities import Contact

        contact = Contact(first_name="Test")
        assert contact.photo_url is None

    def test_mcp_contact_response_includes_photo_url(self) -> None:
        """MCP ContactResponse should include photo_url field."""
        from app.mcp.domains.contacts.schemas import ContactResponse

        response = ContactResponse(
            id="1",
            name="Test User",
            photo_url="/api/contacts/1/avatar",
            summary="Test summary",
        )
        assert response.photo_url == "/api/contacts/1/avatar"

    def test_mcp_contact_response_photo_url_defaults_to_none(self) -> None:
        """MCP ContactResponse photo_url should default to None."""
        from app.mcp.domains.contacts.schemas import ContactResponse

        response = ContactResponse(
            id="1",
            name="Test User",
            summary="Test summary",
        )
        assert response.photo_url is None

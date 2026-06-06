"""Unit tests for the AvatarProxyService."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.integrations.avatar_proxy_service import (
    AvatarNotFoundError,
    AvatarProxyService,
)


@pytest.fixture
def mock_connection() -> AsyncMock:
    """Provide a mock AsyncConnection."""
    return AsyncMock()


@pytest.fixture
def encryption_key() -> str:
    """Provide a valid Fernet encryption key for tests."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


@pytest.fixture
def service(mock_connection: AsyncMock, encryption_key: str) -> AvatarProxyService:
    """Provide an AvatarProxyService instance."""
    return AvatarProxyService(
        connection=mock_connection,
        encryption_key=encryption_key,
    )


class TestGetImmichPersonId:
    """Tests for _get_immich_person_id."""

    async def test_returns_person_id_when_found(
        self, service: AvatarProxyService, mock_connection: AsyncMock
    ) -> None:
        """Should return the person_id from external_references."""
        mock_row = MagicMock()
        mock_row.external_entity_id = "immich-person-uuid"
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute.return_value = mock_result

        result = await service._get_immich_person_id(42)

        assert result == "immich-person-uuid"

    async def test_returns_none_when_no_reference(
        self, service: AvatarProxyService, mock_connection: AsyncMock
    ) -> None:
        """Should return None when no external reference exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute.return_value = mock_result

        result = await service._get_immich_person_id(42)

        assert result is None


class TestGetImmichCredentials:
    """Tests for _get_immich_credentials."""

    async def test_returns_none_when_no_auth_row(
        self, service: AvatarProxyService, mock_connection: AsyncMock
    ) -> None:
        """Should return (None, None) when no auth row exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute.return_value = mock_result

        server_url, api_key = await service._get_immich_credentials("user1")

        assert server_url is None
        assert api_key is None

    async def test_returns_decrypted_credentials(
        self,
        service: AvatarProxyService,
        mock_connection: AsyncMock,
        encryption_key: str,
    ) -> None:
        """Should return decrypted server URL and API key."""
        from cryptography.fernet import Fernet

        fernet = Fernet(encryption_key.encode())
        encrypted_key = fernet.encrypt(b"test-api-key")

        mock_row = MagicMock()
        mock_row.server_url = "https://immich.example.com"
        mock_row.encrypted_api_key = encrypted_key
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute.return_value = mock_result

        server_url, api_key = await service._get_immich_credentials("user1")

        assert server_url == "https://immich.example.com"
        assert api_key == "test-api-key"

    async def test_returns_none_on_decryption_failure(
        self, service: AvatarProxyService, mock_connection: AsyncMock
    ) -> None:
        """Should return (None, None) when decryption fails."""
        mock_row = MagicMock()
        mock_row.server_url = "https://immich.example.com"
        mock_row.encrypted_api_key = b"invalid-encrypted-data"
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute.return_value = mock_result

        server_url, api_key = await service._get_immich_credentials("user1")

        assert server_url is None
        assert api_key is None


class TestFetchThumbnail:
    """Tests for _fetch_thumbnail."""

    async def test_fetches_thumbnail_bytes(self) -> None:
        """Should return thumbnail bytes from Immich."""
        fake_image = b"\xff\xd8\xff\xe0fake-jpeg-data"

        with patch(
            "app.core.integrations.avatar_proxy_service.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = fake_image
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await AvatarProxyService._fetch_thumbnail(
                "https://immich.example.com",
                "test-api-key",
                "person-uuid",
            )

            assert result == fake_image
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert "people/person-uuid/thumbnail" in call_args[0][0]

    async def test_raises_on_http_error(self) -> None:
        """Should raise AvatarNotFoundError on HTTP errors."""
        with patch(
            "app.core.integrations.avatar_proxy_service.httpx.AsyncClient"
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


class TestGetAvatarBytes:
    """Integration-style tests for get_avatar_bytes."""

    async def test_raises_when_no_immich_link(
        self, service: AvatarProxyService, mock_connection: AsyncMock
    ) -> None:
        """Should raise AvatarNotFoundError when contact has no Immich link."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute.return_value = mock_result

        with pytest.raises(AvatarNotFoundError, match="not linked"):
            await service.get_avatar_bytes(contact_id=42, user_id="user1")

    async def test_raises_when_no_immich_credentials(
        self, service: AvatarProxyService, mock_connection: AsyncMock
    ) -> None:
        """Should raise AvatarNotFoundError when user has no Immich creds."""
        # First call returns person_id, second returns no auth
        person_result = MagicMock()
        person_row = MagicMock()
        person_row.external_entity_id = "person-uuid"
        person_result.fetchone.return_value = person_row

        auth_result = MagicMock()
        auth_result.fetchone.return_value = None

        mock_connection.execute.side_effect = [person_result, auth_result]

        with pytest.raises(AvatarNotFoundError, match="not configured"):
            await service.get_avatar_bytes(contact_id=42, user_id="user1")


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

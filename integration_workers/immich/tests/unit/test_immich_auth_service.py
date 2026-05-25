"""Unit tests for the Immich auth service."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine import CursorResult

from immich_auth_service import ImmichAuthService


@pytest.fixture
def valid_fernet_key() -> str:
    """Return a valid base64-encoded Fernet key."""
    return Fernet.generate_key().decode()


@pytest.fixture
def auth_service(valid_fernet_key: str) -> ImmichAuthService:
    """Return a configured auth service instance."""
    return ImmichAuthService(valid_fernet_key)


@pytest.mark.asyncio
class TestImmichAuthService:
    """Tests for the ImmichAuthService."""

    def test_encrypt_decrypt_roundtrip(self, auth_service: ImmichAuthService) -> None:
        """Test that encryption and decryption are reversible."""
        original = "secret_api_key_123"
        encrypted = auth_service.encrypt(original)

        assert encrypted != original.encode()

        decrypted = auth_service.decrypt(encrypted)
        assert decrypted == original

    async def test_get_api_key_returns_decrypted_key(
        self, auth_service: ImmichAuthService
    ) -> None:
        """Test that a valid encrypted key is decrypted and returned."""
        api_key = "super_secret_key"
        encrypted_key = auth_service.encrypt(api_key)

        mock_row = MagicMock()
        mock_row.encrypted_api_key = encrypted_key

        mock_result = MagicMock(spec=CursorResult)
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_api_key("user-1", mock_session)

        assert result == api_key

    async def test_get_api_key_no_row_returns_none(
        self, auth_service: ImmichAuthService
    ) -> None:
        """Test that missing auth row returns None."""
        mock_result = MagicMock(spec=CursorResult)
        mock_result.fetchone.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_api_key("user-1", mock_session)

        assert result is None

    async def test_decrypt_invalid_token_returns_none(
        self, auth_service: ImmichAuthService
    ) -> None:
        """Test that corrupted encrypted data returns None gracefully."""
        mock_row = MagicMock()
        mock_row.encrypted_api_key = b"invalid_token_data"

        mock_result = MagicMock(spec=CursorResult)
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_api_key("user-1", mock_session)

        assert result is None

    async def test_get_server_url_returns_url(
        self, auth_service: ImmichAuthService
    ) -> None:
        """Test that server url is returned."""
        url = "https://immich.example.com"

        mock_row = MagicMock()
        mock_row.server_url = url

        mock_result = MagicMock(spec=CursorResult)
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_server_url("user-1", mock_session)

        assert result == url

    async def test_get_server_url_no_row_returns_none(
        self, auth_service: ImmichAuthService
    ) -> None:
        """Test that missing auth row returns None for server URL."""
        mock_result = MagicMock(spec=CursorResult)
        mock_result.fetchone.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_server_url("user-1", mock_session)

        assert result is None

# ruff: noqa: E402
"""Tests for Snipe-IT auth service (API key retrieval and decryption)."""

import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"
    )
os.environ["ENCRYPTION_KEY"] = "testkey"

from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from snipeit_auth_service import SnipeItAuthService


@pytest.fixture
def encryption_key() -> str:
    """Generate a valid Fernet encryption key."""
    return Fernet.generate_key().decode()


@pytest.fixture
def auth_service(encryption_key: str) -> SnipeItAuthService:
    """Create an auth service with a valid encryption key."""
    return SnipeItAuthService(encryption_key=encryption_key)


class TestSnipeItAuthServiceEncryption:
    """Tests for API key encryption/decryption."""

    def test_encrypt_decrypt_roundtrip(self, auth_service: SnipeItAuthService) -> None:
        """Encrypting and decrypting a value returns the original."""
        original = "my-secret-api-key"
        encrypted = auth_service.encrypt(original)
        decrypted = auth_service.decrypt(encrypted)
        assert decrypted == original

    def test_encrypted_value_is_different(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """Encrypted value is not the same as the original."""
        original = "my-secret-api-key"
        encrypted = auth_service.encrypt(original)
        assert encrypted != original.encode()


class TestSnipeItAuthServiceGetApiKey:
    """Tests for retrieving API key from the database."""

    @pytest.mark.asyncio
    async def test_get_api_key_returns_decrypted_key(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_api_key returns decrypted API key when row exists."""
        encrypted_key = auth_service.encrypt("my-api-key-123")

        mock_row = MagicMock()
        mock_row.encrypted_api_key = encrypted_key
        mock_row.needs_reauth = False

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_api_key("user-1", mock_session)
        assert result == "my-api-key-123"

    @pytest.mark.asyncio
    async def test_get_api_key_returns_none_when_no_row(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_api_key returns None when no auth row exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_api_key("nonexistent", mock_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_api_key_returns_none_when_needs_reauth(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_api_key returns None when needs_reauth is True."""
        encrypted_key = auth_service.encrypt("my-api-key")

        mock_row = MagicMock()
        mock_row.encrypted_api_key = encrypted_key
        mock_row.needs_reauth = True

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_api_key("user-1", mock_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_api_key_returns_none_when_invalid_data(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_api_key returns None when decryption fails (corrupted data)."""
        mock_row = MagicMock()
        mock_row.encrypted_api_key = b"invalid-fernet-data"
        mock_row.needs_reauth = False

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_api_key("user-1", mock_session)
        assert result is None


class TestSnipeItAuthServiceGetBaseUrl:
    """Tests for retrieving the base URL from settings."""

    @pytest.mark.asyncio
    async def test_get_base_url_returns_url(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_base_url returns the configured base URL."""
        mock_row = MagicMock()
        mock_row.base_url = "https://snipeit.example.com"

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_base_url("user-1", mock_session)
        assert result == "https://snipeit.example.com"

    @pytest.mark.asyncio
    async def test_get_base_url_returns_none_when_no_settings(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_base_url returns None when no settings row exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_base_url("user-1", mock_session)
        assert result is None

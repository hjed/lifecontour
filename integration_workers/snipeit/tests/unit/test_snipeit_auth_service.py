# ruff: noqa: E402
"""Tests for Snipe-IT auth service (token retrieval and refresh)."""

import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"
    )
os.environ["ENCRYPTION_KEY"] = "testkey"

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from snipeit_auth_service import SnipeItAuthService, SnipeItTokenData


@pytest.fixture
def encryption_key() -> str:
    """Generate a valid Fernet encryption key."""
    return Fernet.generate_key().decode()


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Create a mock httpx.AsyncClient."""
    return AsyncMock()


@pytest.fixture
def auth_service(
    encryption_key: str, mock_http_client: AsyncMock
) -> SnipeItAuthService:
    """Create an auth service with a valid encryption key and injected client."""
    return SnipeItAuthService(
        encryption_key=encryption_key,
        http_client=mock_http_client,
    )


class TestSnipeItAuthServiceTokenData:
    """Tests for SnipeItTokenData dataclass."""

    def test_token_data_fields(self) -> None:
        """Token data holds all expected fields."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        data = SnipeItTokenData(
            access_token="access",
            refresh_token="refresh",
            expires_at=expires,
        )
        assert data.access_token == "access"
        assert data.refresh_token == "refresh"
        assert data.expires_at == expires


class TestSnipeItAuthServiceEncryption:
    """Tests for token encryption/decryption."""

    def test_encrypt_decrypt_roundtrip(self, auth_service: SnipeItAuthService) -> None:
        """Encrypting and decrypting a value returns the original."""
        original = "my-secret-token"
        encrypted = auth_service.encrypt(original)
        decrypted = auth_service.decrypt(encrypted)
        assert decrypted == original

    def test_encrypted_value_is_different(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """Encrypted value is not the same as the original."""
        original = "my-secret-token"
        encrypted = auth_service.encrypt(original)
        assert encrypted != original.encode()


class TestSnipeItAuthServiceGetTokens:
    """Tests for retrieving tokens from the database."""

    @pytest.mark.asyncio
    async def test_get_tokens_returns_data(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_tokens returns decrypted token data when row exists."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        encrypted_access = auth_service.encrypt("access-tok")
        encrypted_refresh = auth_service.encrypt("refresh-tok")

        mock_row = MagicMock()
        mock_row.encrypted_access_token = encrypted_access
        mock_row.encrypted_refresh_token = encrypted_refresh
        mock_row.token_expires_at = expires
        mock_row.needs_reauth = False

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_tokens("user-1", mock_session)
        assert result is not None
        assert result.access_token == "access-tok"
        assert result.refresh_token == "refresh-tok"
        assert result.expires_at == expires

    @pytest.mark.asyncio
    async def test_get_tokens_returns_none_when_no_row(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_tokens returns None when no auth row exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_tokens("nonexistent", mock_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tokens_returns_none_when_needs_reauth(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_tokens returns None when needs_reauth is True."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        encrypted_access = auth_service.encrypt("access-tok")
        encrypted_refresh = auth_service.encrypt("refresh-tok")

        mock_row = MagicMock()
        mock_row.encrypted_access_token = encrypted_access
        mock_row.encrypted_refresh_token = encrypted_refresh
        mock_row.token_expires_at = expires
        mock_row.needs_reauth = True

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_tokens("user-1", mock_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tokens_returns_none_when_invalid_token(
        self, auth_service: SnipeItAuthService
    ) -> None:
        """get_tokens returns None and catches InvalidToken when decryption fails."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        # Use a string that is not a valid fernet token
        invalid_encrypted_access = b"invalid-token-data"
        invalid_encrypted_refresh = b"invalid-token-data"

        mock_row = MagicMock()
        mock_row.encrypted_access_token = invalid_encrypted_access
        mock_row.encrypted_refresh_token = invalid_encrypted_refresh
        mock_row.token_expires_at = expires
        mock_row.needs_reauth = False

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await auth_service.get_tokens("user-1", mock_session)
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


class TestSnipeItAuthServiceRefreshToken:
    """Tests for token refresh using injected httpx client."""

    @pytest.mark.asyncio
    async def test_refresh_token_calls_injected_client(
        self, auth_service: SnipeItAuthService, mock_http_client: AsyncMock
    ) -> None:
        """refresh_token uses the injected HTTP client, not a new one."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response

        result = await auth_service.refresh_token(
            base_url="https://snipeit.example.com",
            refresh_token_value="old-refresh",
            client_id="test-id",
            client_secret="test-secret",
        )

        mock_http_client.post.assert_called_once()
        assert result.access_token == "new-access"
        assert result.refresh_token == "new-refresh"

    @pytest.mark.asyncio
    async def test_refresh_token_posts_correct_url(
        self, auth_service: SnipeItAuthService, mock_http_client: AsyncMock
    ) -> None:
        """refresh_token posts to the correct OAuth token endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "a",
            "refresh_token": "r",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response

        await auth_service.refresh_token(
            base_url="https://snipeit.example.com/",
            refresh_token_value="tok",
            client_id="cid",
            client_secret="csec",
        )

        call_args = mock_http_client.post.call_args
        assert call_args.args[0] == "https://snipeit.example.com/oauth/token"

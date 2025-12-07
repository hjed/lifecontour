"""
Unit tests for GoogleOAuthService.

Tests OAuth flow management including state creation, authorization URL
generation, token exchange, and account management.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.integrations.encryption import EncryptionService
from app.core.integrations.google_oauth.exceptions import (
    GoogleAccountNotFoundError,
    GoogleOAuthConfigurationError,
    GoogleOAuthStateError,
    GoogleOAuthTokenError,
)
from app.core.integrations.google_oauth.models import (
    GOOGLE_OAUTH_STATE_MAX_AGE_SECONDS,
    GoogleAccount,
    GoogleOAuthState,
    GoogleOAuthTokens,
)
from app.core.integrations.google_oauth.repository import GoogleOAuthRepository
from app.core.integrations.google_oauth.service import GoogleOAuthService
from app.infrastructure.config import Settings


@pytest.fixture
def mock_settings() -> Settings:
    """Create mock settings with Google OAuth configured."""
    return Settings(
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        google_encryption_key="test-key-32-bytes-long-for-fernet!",
    )


@pytest.fixture
def mock_settings_unconfigured() -> Settings:
    """Create mock settings without Google OAuth configured."""
    return Settings(
        google_client_id="",
        google_client_secret="",
    )


@pytest.fixture
def mock_repository() -> AsyncMock:
    """Create mock repository."""
    return AsyncMock(spec=GoogleOAuthRepository)


@pytest.fixture
def mock_encryption() -> MagicMock:
    """Create mock encryption service."""
    mock = MagicMock(spec=EncryptionService)
    mock.encrypt.return_value = b"encrypted_data"
    mock.decrypt.return_value = '{"user_id": "test-user", "nonce": "abc", "created_at": "2024-01-01T00:00:00+00:00"}'
    return mock


@pytest.fixture
def service(
    mock_repository: AsyncMock,
    mock_encryption: MagicMock,
    mock_settings: Settings,
) -> GoogleOAuthService:
    """Create GoogleOAuthService instance for testing."""
    return GoogleOAuthService(
        repository=mock_repository,
        encryption_service=mock_encryption,
        settings=mock_settings,
    )


class TestGoogleOAuthStateManagement:
    """Tests for OAuth state creation and validation."""

    def test_create_oauth_state(self, service: GoogleOAuthService):
        """Test creating a new OAuth state."""
        state = service.create_oauth_state(
            user_id="test-user",
            redirect_url="/integrations",
        )

        assert state.user_id == "test-user"
        assert state.redirect_url == "/integrations"
        assert state.nonce is not None
        assert len(state.nonce) > 0
        assert state.created_at is not None
        assert not state.is_expired()

    def test_oauth_state_expiration(self):
        """Test OAuth state expiration check."""
        # State created 11 minutes ago should be expired (max 10 min)
        old_state = GoogleOAuthState(
            user_id="test-user",
            nonce="test-nonce",
            created_at=datetime.now(UTC) - timedelta(minutes=11),
        )

        assert old_state.is_expired(GOOGLE_OAUTH_STATE_MAX_AGE_SECONDS)

    def test_encode_and_decode_state(
        self,
        service: GoogleOAuthService,
        mock_encryption: MagicMock,
    ):
        """Test state encoding and decoding round-trip."""
        # Setup mock to return valid JSON for decoding
        state = service.create_oauth_state(user_id="test-user")

        # When encoding
        mock_encryption.encrypt.return_value = b"encrypted_state"
        encoded = service.encode_state(state)

        assert encoded is not None
        assert mock_encryption.encrypt.called

    def test_decode_invalid_state_raises_error(
        self,
        service: GoogleOAuthService,
        mock_encryption: MagicMock,
    ):
        """Test that invalid state raises error."""
        mock_encryption.decrypt.side_effect = Exception("Decryption failed")

        with pytest.raises(GoogleOAuthStateError) as exc_info:
            service.decode_state("invalid-state")

        assert "Invalid OAuth state" in str(exc_info.value)

    def test_decode_expired_state_raises_error(
        self,
        service: GoogleOAuthService,
        mock_encryption: MagicMock,
    ):
        """Test that expired state raises error."""
        import base64

        # Return state from 11 minutes ago
        old_time = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
        mock_encryption.decrypt.return_value = (
            f'{{"user_id": "test-user", "nonce": "abc", "created_at": "{old_time}"}}'
        )

        # Create a valid base64-encoded state for testing
        valid_base64 = base64.urlsafe_b64encode(b"encrypted_data").decode("utf-8")

        with pytest.raises(GoogleOAuthStateError) as exc_info:
            service.decode_state(valid_base64)

        assert "expired" in str(exc_info.value).lower()


class TestGoogleOAuthAuthorization:
    """Tests for OAuth authorization URL generation."""

    def test_get_authorization_url(self, service: GoogleOAuthService):
        """Test generating authorization URL."""
        state = service.create_oauth_state(user_id="test-user")

        url = service.get_authorization_url(
            state=state,
            callback_url="http://localhost:3000/integrations/callback",
        )

        assert "https://accounts.google.com" in url
        assert "client_id=test-client-id" in url
        assert "redirect_uri=" in url
        assert "response_type=code" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "state=" in url

    def test_authorization_url_includes_scopes(self, service: GoogleOAuthService):
        """Test authorization URL includes requested scopes."""
        state = service.create_oauth_state(user_id="test-user")

        url = service.get_authorization_url(
            state=state,
            callback_url="http://localhost:3000/callback",
            scopes=["https://www.googleapis.com/auth/contacts"],
        )

        assert "scope=" in url
        assert "contacts" in url

    def test_authorization_url_unconfigured_raises_error(
        self,
        mock_repository: AsyncMock,
        mock_encryption: MagicMock,
        mock_settings_unconfigured: Settings,
    ):
        """Test that unconfigured OAuth raises error."""
        service = GoogleOAuthService(
            repository=mock_repository,
            encryption_service=mock_encryption,
            settings=mock_settings_unconfigured,
        )
        state = GoogleOAuthState(
            user_id="test-user",
            nonce="test-nonce",
            created_at=datetime.now(UTC),
        )

        with pytest.raises(GoogleOAuthConfigurationError):
            service.get_authorization_url(
                state=state,
                callback_url="http://localhost:3000/callback",
            )


class TestGoogleOAuthTokenExchange:
    """Tests for OAuth token exchange."""

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_success(
        self,
        service: GoogleOAuthService,
    ):
        """Test successful token exchange."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "contacts.readonly",
            }
            mock_client.post.return_value = mock_response

            tokens = await service.exchange_code_for_tokens(
                code="auth-code-123",
                callback_url="http://localhost:3000/callback",
            )

            assert tokens.access_token == "test-access-token"
            assert tokens.refresh_token == "test-refresh-token"
            assert tokens.expires_in == 3600

    @pytest.mark.asyncio
    async def test_exchange_code_failure_raises_error(
        self,
        service: GoogleOAuthService,
    ):
        """Test token exchange failure."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "error": "invalid_grant",
                "error_description": "Code has expired",
            }
            mock_client.post.return_value = mock_response

            with pytest.raises(GoogleOAuthTokenError) as exc_info:
                await service.exchange_code_for_tokens(
                    code="expired-code",
                    callback_url="http://localhost:3000/callback",
                )

            assert "expired" in str(exc_info.value).lower()


class TestGoogleAccountManagement:
    """Tests for Google account CRUD operations."""

    @pytest.mark.asyncio
    async def test_save_account(
        self,
        service: GoogleOAuthService,
        mock_repository: AsyncMock,
    ):
        """Test saving a new Google account."""
        mock_account = GoogleAccount(
            id=1,
            user_id="test-user",
            email="user@gmail.com",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        mock_repository.save_tokens.return_value = mock_account

        tokens = GoogleOAuthTokens(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=3600,
            token_type="Bearer",
            scope="contacts.readonly",
        )

        account = await service.save_account(
            user_id="test-user",
            tokens=tokens,
            email="user@gmail.com",
        )

        assert account.email == "user@gmail.com"
        mock_repository.save_tokens.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_accounts(
        self,
        service: GoogleOAuthService,
        mock_repository: AsyncMock,
    ):
        """Test getting all connected accounts."""
        mock_accounts = [
            GoogleAccount(
                id=1,
                user_id="test-user",
                email="user1@gmail.com",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            GoogleAccount(
                id=2,
                user_id="test-user",
                email="user2@gmail.com",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        ]
        mock_repository.get_accounts_for_user.return_value = mock_accounts

        accounts = await service.get_accounts(user_id="test-user")

        assert len(accounts) == 2
        assert accounts[0].email == "user1@gmail.com"
        mock_repository.get_accounts_for_user.assert_called_once_with("test-user")

    @pytest.mark.asyncio
    async def test_disconnect_account(
        self,
        service: GoogleOAuthService,
        mock_repository: AsyncMock,
    ):
        """Test disconnecting a Google account."""
        mock_repository.delete_account.return_value = True

        result = await service.disconnect_account(
            user_id="test-user",
            email="user@gmail.com",
        )

        assert result is True
        mock_repository.delete_account.assert_called_once_with(
            "test-user", "user@gmail.com"
        )

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_account_raises_error(
        self,
        service: GoogleOAuthService,
        mock_repository: AsyncMock,
    ):
        """Test disconnecting non-existent account raises error."""
        mock_repository.delete_account.side_effect = GoogleAccountNotFoundError(
            "nonexistent@gmail.com"
        )

        with pytest.raises(GoogleAccountNotFoundError):
            await service.disconnect_account(
                user_id="test-user",
                email="nonexistent@gmail.com",
            )

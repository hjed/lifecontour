"""
Unit tests for Google Token Service.

Tests the Google token storage and management functionality
with mocked database connections.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from app.infrastructure.auth.google_token_service import (
    GoogleTokenNotFoundError,
    GoogleTokenService,
    TokenStorageError,
)


class TestGoogleTokenService:
    """Unit tests for GoogleTokenService."""

    @pytest.fixture
    def encryption_key(self) -> str:
        """Generate test encryption key."""
        return Fernet.generate_key().decode()

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        """Create mock database connection.

        ``info`` is a real dict (not an auto-generated child mock) so the
        service-layer :func:`unit_of_work` helper — which reads/writes the
        connection's ``info`` for re-entrancy bookkeeping — behaves correctly.
        With no external-transaction marker present, the unit of work takes the
        production path and awaits ``connection.commit()`` (a no-op AsyncMock).
        """
        connection = AsyncMock()
        connection.info = {}
        return connection

    @pytest.fixture
    def service(
        self, mock_connection: AsyncMock, encryption_key: str
    ) -> GoogleTokenService:
        """Create GoogleTokenService instance with mocked dependencies."""
        return GoogleTokenService(mock_connection, encryption_key)

    async def test_store_tokens_success(
        self, service: GoogleTokenService, mock_connection: AsyncMock
    ):
        """Test successful token storage."""
        # Arrange
        user_id = "test_user_123"
        google_email = "test@gmail.com"
        access_token = "access_token_123"
        refresh_token = "refresh_token_456"
        expires_in = 3600

        mock_connection.execute.return_value = None

        # Act
        await service.store_tokens(
            user_id=user_id,
            google_email=google_email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

        # Assert
        assert mock_connection.execute.call_count == 1
        call_args = mock_connection.execute.call_args

        # Verify SQL contains UPSERT logic
        sql = str(call_args[0][0])
        assert "INSERT INTO user_google_auth" in sql
        assert "ON CONFLICT" in sql

        # Verify parameters
        params = call_args[0][1]
        assert params["user_id"] == user_id
        assert params["google_account_email"] == google_email
        # Tokens should be encrypted (not plain text)
        assert params["encrypted_access_token"] != access_token.encode()
        assert params["encrypted_refresh_token"] != refresh_token.encode()

    async def test_store_tokens_database_error(
        self, service: GoogleTokenService, mock_connection: AsyncMock
    ):
        """Test token storage with database error."""
        # Arrange
        mock_connection.execute.side_effect = Exception("Database connection failed")

        # Act & Assert
        with pytest.raises(TokenStorageError, match="Failed to store Google tokens"):
            await service.store_tokens(
                user_id="test_user",
                google_email="test@gmail.com",
                access_token="access_token",
                refresh_token="refresh_token",
                expires_in=3600,
            )

    async def test_get_tokens_success(
        self, service: GoogleTokenService, mock_connection: AsyncMock
    ):
        """Test successful token retrieval."""
        # Arrange
        user_id = "test_user_123"
        google_email = "test@gmail.com"

        # Mock encrypted tokens (encrypt real tokens for test)
        access_token = "access_token_123"
        refresh_token = "refresh_token_456"
        encrypted_access = service.encrypt(access_token)
        encrypted_refresh = service.encrypt(refresh_token)
        expires_at = datetime.now(UTC) + timedelta(hours=1)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(
            encrypted_access_token=encrypted_access,
            encrypted_refresh_token=encrypted_refresh,
            expires_at=expires_at,
        )
        mock_connection.execute.return_value = mock_result

        # Act
        tokens = await service.get_tokens(user_id, google_email)

        # Assert
        assert tokens["access_token"] == access_token
        assert tokens["refresh_token"] == refresh_token
        assert tokens["expires_at"] == expires_at
        assert tokens["is_expired"] is False

    async def test_get_tokens_not_found(
        self, service: GoogleTokenService, mock_connection: AsyncMock
    ):
        """Test token retrieval when tokens not found."""
        # Arrange
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute.return_value = mock_result

        # Act & Assert
        with pytest.raises(GoogleTokenNotFoundError):
            await service.get_tokens("nonexistent_user", "test@gmail.com")

    async def test_delete_tokens_success(
        self, service: GoogleTokenService, mock_connection: AsyncMock
    ):
        """Test successful token deletion."""
        # Arrange
        user_id = "test_user_123"
        google_email = "test@gmail.com"

        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_connection.execute.return_value = mock_result

        # Act
        result = await service.delete_tokens(user_id, google_email)

        # Assert
        assert result is True
        mock_connection.execute.assert_called_once()

    async def test_delete_tokens_not_found(
        self, service: GoogleTokenService, mock_connection: AsyncMock
    ):
        """Test token deletion when tokens not found."""
        # Arrange
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_connection.execute.return_value = mock_result

        # Act
        result = await service.delete_tokens("nonexistent_user", "test@gmail.com")

        # Assert
        assert result is False

    async def test_has_valid_tokens_true(
        self, service: GoogleTokenService, mock_connection: AsyncMock
    ):
        """Test checking for valid tokens when they exist and are not expired."""
        # Arrange
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(
            expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
        mock_connection.execute.return_value = mock_result

        # Act
        result = await service.has_valid_tokens("test_user", "test@gmail.com")

        # Assert
        assert result is True

    async def test_has_valid_tokens_false_expired(
        self, service: GoogleTokenService, mock_connection: AsyncMock
    ):
        """Test checking for valid tokens when they are expired."""
        # Arrange
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(
            expires_at=datetime.now(UTC) - timedelta(hours=1)
        )
        mock_connection.execute.return_value = mock_result

        # Act
        result = await service.has_valid_tokens("test_user", "test@gmail.com")

        # Assert
        assert result is False

    async def test_has_valid_tokens_false_not_found(
        self, service: GoogleTokenService, mock_connection: AsyncMock
    ):
        """Test checking for valid tokens when they don't exist."""
        # Arrange
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute.return_value = mock_result

        # Act
        result = await service.has_valid_tokens("test_user", "test@gmail.com")

        # Assert
        assert result is False

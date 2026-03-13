"""
Google Token Service for managing OAuth tokens in core API.

Provides secure storage and retrieval of Google OAuth tokens with
encryption and proper database management.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger()


class GoogleTokenNotFoundError(Exception):
    """Raised when Google OAuth tokens are not found for a user."""

    pass


class TokenStorageError(Exception):
    """Raised when token storage operations fail."""

    pass


class GoogleTokenService:
    """
    Service for managing Google OAuth tokens in core API.

    Provides secure storage and retrieval of Google OAuth tokens with
    automatic encryption/decryption and proper error handling.
    """

    def __init__(self, connection: AsyncConnection, encryption_key: str):
        """
        Initialize the Google Token Service.

        Args:
            connection: Database connection
            encryption_key: Base64-encoded encryption key for token encryption
        """
        self.connection = connection
        self.fernet = Fernet(encryption_key.encode())

    def encrypt(self, data: str) -> bytes:
        """Encrypt sensitive data."""
        return self.fernet.encrypt(data.encode())

    def decrypt(self, encrypted_data: bytes) -> str:
        """Decrypt sensitive data."""
        return self.fernet.decrypt(encrypted_data).decode()

    async def store_tokens(
        self,
        user_id: str,
        google_email: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        granted_scopes: str | None = None,
    ) -> None:
        """
        Store Google OAuth tokens for a user.

        Args:
            user_id: User ID
            google_email: Google account email
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            expires_in: Token expiration time in seconds
            granted_scopes: Space-separated list of granted OAuth scopes

        Raises:
            TokenStorageError: If storage operation fails
        """
        try:
            # Calculate expiration time
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

            # Encrypt tokens
            encrypted_access_token = self.encrypt(access_token)
            encrypted_refresh_token = self.encrypt(refresh_token)

            # Use UPSERT to handle existing tokens
            stmt = text("""
                INSERT INTO user_google_auth (
                    user_id, google_account_email, encrypted_access_token,
                    encrypted_refresh_token, expires_at, created_at, updated_at,
                    granted_scopes
                )
                VALUES (
                    :user_id, :google_account_email, :encrypted_access_token,
                    :encrypted_refresh_token, :expires_at, :created_at, :updated_at,
                    :granted_scopes
                )
                ON CONFLICT (user_id, google_account_email)
                DO UPDATE SET
                    encrypted_access_token = EXCLUDED.encrypted_access_token,
                    encrypted_refresh_token = EXCLUDED.encrypted_refresh_token,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = EXCLUDED.updated_at,
                    granted_scopes = EXCLUDED.granted_scopes
            """)

            now = datetime.now(UTC)
            await self.connection.execute(
                stmt,
                {
                    "user_id": user_id,
                    "google_account_email": google_email,
                    "encrypted_access_token": encrypted_access_token,
                    "encrypted_refresh_token": encrypted_refresh_token,
                    "expires_at": expires_at,
                    "created_at": now,
                    "updated_at": now,
                    "granted_scopes": granted_scopes,
                },
            )

            logger.info(
                "Stored Google OAuth tokens",
                user_id=user_id,
                google_email=google_email,
                expires_at=expires_at.isoformat(),
            )

        except Exception as e:
            logger.error(
                "Failed to store Google tokens",
                user_id=user_id,
                google_email=google_email,
                error=str(e),
                exc_info=True,
            )
            raise TokenStorageError(f"Failed to store Google tokens: {str(e)}") from e

    async def get_tokens(self, user_id: str, google_email: str) -> dict[str, Any]:
        """
        Get Google OAuth tokens for a user.

        Args:
            user_id: User ID
            google_email: Google account email

        Returns:
            Dictionary containing decrypted tokens and metadata

        Raises:
            GoogleTokenNotFoundError: If tokens not found
        """
        stmt = text("""
            SELECT encrypted_access_token, encrypted_refresh_token, expires_at
            FROM user_google_auth
            WHERE user_id = :user_id AND google_account_email = :google_email
        """)

        result = await self.connection.execute(
            stmt, {"user_id": user_id, "google_email": google_email}
        )
        token_record = result.fetchone()

        if not token_record:
            raise GoogleTokenNotFoundError(
                f"No Google tokens found for user {user_id} with email {google_email}"
            )

        # Decrypt tokens
        access_token = self.decrypt(token_record.encrypted_access_token)
        refresh_token = self.decrypt(token_record.encrypted_refresh_token)

        # Check if token is expired
        is_expired = datetime.now(UTC) >= token_record.expires_at

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": token_record.expires_at,
            "is_expired": is_expired,
        }

    async def delete_tokens(self, user_id: str, google_email: str) -> bool:
        """
        Delete Google OAuth tokens for a user.

        Args:
            user_id: User ID
            google_email: Google account email

        Returns:
            True if tokens were deleted, False if not found
        """
        stmt = text("""
            DELETE FROM user_google_auth
            WHERE user_id = :user_id AND google_account_email = :google_email
        """)

        result = await self.connection.execute(
            stmt, {"user_id": user_id, "google_email": google_email}
        )

        deleted = result.rowcount > 0
        if deleted:
            logger.info(
                "Deleted Google OAuth tokens",
                user_id=user_id,
                google_email=google_email,
            )

        return deleted

    async def has_valid_tokens(self, user_id: str, google_email: str) -> bool:
        """
        Check if user has valid (non-expired) Google OAuth tokens.

        Args:
            user_id: User ID
            google_email: Google account email

        Returns:
            True if valid tokens exist, False otherwise
        """
        stmt = text("""
            SELECT expires_at
            FROM user_google_auth
            WHERE user_id = :user_id AND google_account_email = :google_email
        """)

        result = await self.connection.execute(
            stmt, {"user_id": user_id, "google_email": google_email}
        )
        token_record = result.fetchone()

        if not token_record:
            return False

        # Check if token is still valid
        expires_at: datetime = token_record.expires_at
        return datetime.now(UTC) < expires_at

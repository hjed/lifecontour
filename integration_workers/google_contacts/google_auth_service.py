"""
Google authentication service for managing OAuth tokens in worker.

Migrated from backend/app/core/integrations/google_contacts/service.py
and adapted for worker environment with simplified dependencies.
"""

from datetime import UTC, datetime, timedelta

import httpx
import structlog
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# Site user ID constant (single-user system)
SITE_USER_ID = 1


class GoogleAuthTokensNotFoundError(Exception):
    """Raised when no Google OAuth tokens are found for the user."""

    pass


class TokenRefreshFailedError(Exception):
    """Raised when Google token refresh fails permanently."""

    pass


class GoogleAuthService:
    """
    Service for managing Google OAuth credentials in worker.

    Provides secure storage and retrieval of Google OAuth tokens with
    automatic encryption/decryption and concurrency-safe token refresh.
    Adapted for worker environment.
    """

    def __init__(
        self,
        session: AsyncSession,
        encryption_key: str,
        google_client_id: str,
        google_client_secret: str,
    ) -> None:
        """
        Initialize Google auth service.

        Args:
            session: Database session
            encryption_key: Key for encrypting/decrypting tokens
            google_client_id: Google OAuth client ID
            google_client_secret: Google OAuth client secret
        """
        self.session = session
        self.encryption_key = encryption_key
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self._fernet = Fernet(encryption_key.encode())

    def encrypt(self, value: str) -> str:
        """Encrypt a string value."""
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, encrypted_value: str) -> str:
        """Decrypt an encrypted string value."""
        return self._fernet.decrypt(encrypted_value.encode()).decode()

    async def get_access_token(self, google_account_email: str) -> str:
        """
        Get decrypted access token for a Google account.

        Args:
            google_account_email: Google account email address

        Returns:
            Decrypted access token

        Raises:
            GoogleAuthTokensNotFoundError: If no tokens found for the account
        """
        stmt = text("""
            SELECT encrypted_access_token, expires_at
            FROM user_google_auth
            WHERE user_id = :user_id AND google_account_email = :email
        """)
        result = await self.session.execute(
            stmt, {"user_id": SITE_USER_ID, "email": google_account_email}
        )
        auth_record = result.fetchone()

        if not auth_record:
            raise GoogleAuthTokensNotFoundError(
                f"No Google auth found for {google_account_email}"
            )

        # Check if token is expired
        if auth_record.expires_at and auth_record.expires_at <= datetime.now(UTC):
            logger.info(
                "Access token expired, refreshing",
                google_account_email=google_account_email,
            )
            return await self.refresh_access_token(google_account_email)

        return self.decrypt(auth_record.encrypted_access_token)

    async def refresh_access_token(self, google_account_email: str) -> str:
        """
        Refresh Google access token using refresh token.

        Args:
            google_account_email: Google account email address

        Returns:
            New access token

        Raises:
            TokenRefreshFailedError: If refresh fails permanently
            GoogleAuthTokensNotFoundError: If no tokens found for the account
        """
        # Lock the record to prevent concurrent refresh attempts
        stmt = text("""
            SELECT id, encrypted_refresh_token, expires_at
            FROM user_google_auth
            WHERE user_id = :user_id
            AND google_account_email = :email
            FOR UPDATE
        """)

        result = await self.session.execute(
            stmt, {"user_id": SITE_USER_ID, "email": google_account_email}
        )
        auth_record = result.fetchone()

        if not auth_record:
            raise GoogleAuthTokensNotFoundError(
                f"No Google auth found for {google_account_email}"
            )

        if not auth_record.encrypted_refresh_token:
            raise TokenRefreshFailedError(
                f"No refresh token available for {google_account_email}"
            )

        # Decrypt refresh token
        refresh_token = self.decrypt(auth_record.encrypted_refresh_token)

        # Make token refresh request
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": self.google_client_id,
            "client_secret": self.google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        logger.info(
            "Refreshing Google access token", google_account_email=google_account_email
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)

            if response.status_code != 200:
                error_msg = (
                    f"Token refresh failed: {response.status_code} {response.text}"
                )
                logger.error(
                    "Failed to refresh Google access token",
                    google_account_email=google_account_email,
                    status_code=response.status_code,
                    error=response.text,
                )
                raise TokenRefreshFailedError(error_msg)

            token_data = response.json()
            new_access_token = str(token_data["access_token"])
            expires_in = token_data.get("expires_in", 3600)
            new_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

            # Update the access token and expiration
            encrypted_access_token = self.encrypt(new_access_token)

            update_stmt = text("""
                UPDATE user_google_auth
                SET encrypted_access_token = :access_token,
                    expires_at = :expires_at,
                    updated_at = :updated_at
                WHERE user_id = :user_id
                AND google_account_email = :email
            """)

            await self.session.execute(
                update_stmt,
                {
                    "access_token": encrypted_access_token,
                    "expires_at": new_expires_at,
                    "updated_at": datetime.now(UTC),
                    "user_id": SITE_USER_ID,
                    "email": google_account_email,
                },
            )

            logger.info(
                "Successfully refreshed Google access token",
                google_account_email=google_account_email,
                expires_at=new_expires_at.isoformat(),
            )

            return new_access_token

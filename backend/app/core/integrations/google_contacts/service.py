"""
Google authentication service for managing OAuth tokens.

Handles CRUD operations for Google OAuth credentials with encryption
and concurrency safety for token refresh operations.
"""

from datetime import UTC, datetime, timedelta

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.encryption import EncryptionService
from app.core.integrations.google_contacts.models import SITE_USER_ID

logger = structlog.get_logger()


class GoogleAuthTokensNotFoundError(Exception):
    """Raised when no Google OAuth tokens are found for the user."""

    pass


class TokenRefreshFailedError(Exception):
    """Raised when Google token refresh fails permanently."""

    pass


class GoogleAuthService:
    """
    Service for managing Google OAuth credentials.

    Provides secure storage and retrieval of Google OAuth tokens with
    automatic encryption/decryption and concurrency-safe token refresh.
    """

    def __init__(
        self,
        connection: AsyncConnection,
        encryption_service: EncryptionService,
        google_client_id: str,
        google_client_secret: str,
    ) -> None:
        """
        Initialize Google auth service.

        Args:
            connection: Database connection
            encryption_service: Service for encrypting/decrypting tokens
            google_client_id: Google OAuth client ID
            google_client_secret: Google OAuth client secret
        """
        self.connection = connection
        self.encryption_service = encryption_service
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret

    async def store_tokens(
        self,
        google_account_email: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime,
    ) -> None:
        """
        Store or update Google OAuth tokens for an account.

        Args:
            google_account_email: Google account email address
            access_token: Google access token
            refresh_token: Google refresh token (optional)
            expires_at: Access token expiration timestamp
        """
        try:
            # Encrypt tokens
            encrypted_access_token = self.encryption_service.encrypt(access_token)
            encrypted_refresh_token = (
                self.encryption_service.encrypt(refresh_token)
                if refresh_token
                else None
            )

            # Check if record exists
            stmt = text("""
                SELECT id FROM user_google_auth
                WHERE user_id = :user_id AND google_account_email = :email
            """)
            result = await self.connection.execute(
                stmt, {"user_id": SITE_USER_ID, "email": google_account_email}
            )
            existing_auth = result.fetchone()

            if existing_auth:
                # Update existing record
                update_stmt = text("""
                    UPDATE user_google_auth
                    SET encrypted_access_token = :access_token,
                        encrypted_refresh_token = :refresh_token,
                        expires_at = :expires_at,
                        updated_at = :updated_at
                    WHERE user_id = :user_id
                    AND google_account_email = :email
                """)

                await self.connection.execute(
                    update_stmt,
                    {
                        "access_token": encrypted_access_token,
                        "refresh_token": encrypted_refresh_token,
                        "expires_at": expires_at,
                        "updated_at": datetime.now(UTC),
                        "user_id": SITE_USER_ID,
                        "email": google_account_email,
                    },
                )
            else:
                # Insert new record
                insert_stmt = text("""
                    INSERT INTO user_google_auth
                    (user_id, google_account_email, encrypted_access_token,
                     encrypted_refresh_token, expires_at, created_at, updated_at)
                    VALUES (:user_id, :email, :access_token, :refresh_token,
                            :expires_at, :created_at, :updated_at)
                """)

                now = datetime.now(UTC)
                await self.connection.execute(
                    insert_stmt,
                    {
                        "user_id": SITE_USER_ID,
                        "email": google_account_email,
                        "access_token": encrypted_access_token,
                        "refresh_token": encrypted_refresh_token,
                        "expires_at": expires_at,
                        "created_at": now,
                        "updated_at": now,
                    },
                )

            logger.info(
                "Stored Google OAuth tokens",
                google_account_email=google_account_email,
                expires_at=expires_at,
            )

        except Exception as e:
            logger.error(
                "Failed to store Google OAuth tokens",
                google_account_email=google_account_email,
                error=str(e),
            )
            raise

    async def get_access_token(self, google_account_email: str) -> str:
        """
        Get decrypted access token for a Google account.

        Args:
            google_account_email: Google account email address

        Returns:
            Decrypted access token

        Raises:
            ValueError: If no tokens found for the account
        """
        stmt = text("""
            SELECT encrypted_access_token
            FROM user_google_auth
            WHERE user_id = :user_id AND google_account_email = :email
        """)
        result = await self.connection.execute(
            stmt, {"user_id": SITE_USER_ID, "email": google_account_email}
        )
        auth_record = result.fetchone()

        if not auth_record:
            raise GoogleAuthTokensNotFoundError(
                f"No Google auth found for {google_account_email}"
            )

        return self.encryption_service.decrypt(auth_record.encrypted_access_token)

    async def refresh_access_token(self, google_account_email: str) -> str:
        """
        Refresh Google access token using refresh token.

        Uses SELECT FOR UPDATE to prevent concurrent refresh attempts.

        Args:
            google_account_email: Google account email address

        Returns:
            New access token

        Raises:
            TokenRefreshFailedError: If refresh fails permanently
            ValueError: If no tokens found for the account
        """
        # Lock the record to prevent concurrent refresh attempts
        stmt = text("""
            SELECT id, encrypted_refresh_token, expires_at
            FROM user_google_auth
            WHERE user_id = :user_id
            AND google_account_email = :email
            FOR UPDATE
        """)

        result = await self.connection.execute(
            stmt, {"user_id": SITE_USER_ID, "email": google_account_email}
        )
        row = result.fetchone()

        if not row:
            raise GoogleAuthTokensNotFoundError(
                f"No Google auth found for {google_account_email}"
            )

        if not row.encrypted_refresh_token:
            raise TokenRefreshFailedError(
                f"No refresh token available for {google_account_email}"
            )

        try:
            # Decrypt refresh token
            refresh_token = self.encryption_service.decrypt(row.encrypted_refresh_token)

            # Call Google token refresh endpoint
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": self.google_client_id,
                        "client_secret": self.google_client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code != 200:
                    logger.error(
                        "Google token refresh failed",
                        status_code=response.status_code,
                        response_text=response.text,
                        google_account_email=google_account_email,
                    )
                    raise TokenRefreshFailedError(
                        f"Google token refresh failed: {response.status_code}"
                    )

                token_data = response.json()
                new_access_token = str(token_data["access_token"])
                expires_in = token_data.get("expires_in", 3600)
                new_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

                # Update the access token and expiration
                encrypted_access_token = self.encryption_service.encrypt(
                    new_access_token
                )

                update_stmt = text("""
                    UPDATE user_google_auth
                    SET encrypted_access_token = :access_token,
                        expires_at = :expires_at,
                        updated_at = :updated_at
                    WHERE user_id = :user_id
                    AND google_account_email = :email
                """)

                await self.connection.execute(
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
                    new_expires_at=new_expires_at,
                )

                return new_access_token

        except TokenRefreshFailedError:
            raise
        except Exception as e:
            logger.error(
                "Failed to refresh Google access token",
                google_account_email=google_account_email,
                error=str(e),
            )
            raise TokenRefreshFailedError(
                f"Token refresh failed for {google_account_email}: {str(e)}"
            ) from e

"""
Strava Token Service for managing OAuth tokens in core API.

Provides secure storage and retrieval of Strava OAuth tokens with
encryption via Fernet and proper database management. Token exchange
and refresh are delegated to the Strava auth endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.unit_of_work import unit_of_work

logger = structlog.get_logger()


class StravaTokenNotFoundError(Exception):
    """Raised when Strava OAuth tokens are not found for a user."""


class StravaTokenStorageError(Exception):
    """Raised when token storage operations fail."""


class StravaTokenService:
    """
    Service for managing Strava OAuth tokens in the main API.

    Provides encrypted token CRUD operations against the ``user_strava_auth``
    table. Actual token exchange and refresh are handled by the Strava auth
    endpoints, which call this service to persist the results.
    """

    def __init__(self, connection: AsyncConnection, encryption_key: str) -> None:
        """
        Initialize the Strava Token Service.

        Args:
            connection: Database connection for token operations.
            encryption_key: Base64-encoded Fernet key for token encryption.
                May be empty if Strava is not configured; operations that
                require encryption will raise ``StravaTokenStorageError``.
        """
        self.connection = connection
        self._encryption_key = encryption_key
        self._fernet: Fernet | None = None

    @property
    def fernet(self) -> Fernet:
        """Lazily initialise Fernet so the service can be created even when
        ``strava_encryption_key`` is empty (unconfigured environments)."""
        if self._fernet is None:
            if not self._encryption_key:
                raise StravaTokenStorageError("Strava encryption key is not configured")
            try:
                self._fernet = Fernet(self._encryption_key.encode())
            except (ValueError, Exception) as e:
                raise StravaTokenStorageError(
                    f"Invalid Strava encryption key: {e!s}"
                ) from e
        return self._fernet

    def encrypt(self, data: str) -> bytes:
        """Encrypt sensitive data."""
        return self.fernet.encrypt(data.encode())

    def decrypt(self, encrypted_data: bytes) -> str:
        """Decrypt sensitive data."""
        return self.fernet.decrypt(encrypted_data).decode()

    async def store_tokens(
        self,
        user_id: str,
        athlete_id: int,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
    ) -> None:
        """
        Store Strava OAuth tokens for a user.

        Uses UPSERT to handle re-connection: if the user already has a
        Strava auth row, it updates the tokens rather than inserting a
        duplicate.

        Args:
            user_id: Authenticated user's ID.
            athlete_id: Strava's numeric athlete identifier.
            access_token: OAuth access token (will be encrypted).
            refresh_token: OAuth refresh token (will be encrypted).
            expires_at: UTC datetime when the access token expires.

        Raises:
            StravaTokenStorageError: If storage operation fails.
        """
        try:
            encrypted_access_token = self.encrypt(access_token)
            encrypted_refresh_token = self.encrypt(refresh_token)

            stmt = text("""
                INSERT INTO user_strava_auth (
                    user_id, athlete_id, encrypted_access_token,
                    encrypted_refresh_token, expires_at,
                    needs_reauth, created_at, updated_at
                )
                VALUES (
                    :user_id, :athlete_id, :encrypted_access_token,
                    :encrypted_refresh_token, :expires_at,
                    FALSE, :now, :now
                )
                ON CONFLICT (user_id)
                DO UPDATE SET
                    athlete_id = EXCLUDED.athlete_id,
                    encrypted_access_token = EXCLUDED.encrypted_access_token,
                    encrypted_refresh_token = EXCLUDED.encrypted_refresh_token,
                    expires_at = EXCLUDED.expires_at,
                    needs_reauth = FALSE,
                    updated_at = EXCLUDED.updated_at
            """)

            now = datetime.now(UTC)
            async with unit_of_work(self.connection):
                await self.connection.execute(
                    stmt,
                    {
                        "user_id": user_id,
                        "athlete_id": athlete_id,
                        "encrypted_access_token": encrypted_access_token,
                        "encrypted_refresh_token": encrypted_refresh_token,
                        "expires_at": expires_at,
                        "now": now,
                    },
                )

            logger.info(
                "Stored Strava OAuth tokens",
                user_id=user_id,
                athlete_id=athlete_id,
                expires_at=expires_at.isoformat(),
            )

        except Exception as e:
            logger.error(
                "Failed to store Strava tokens",
                user_id=user_id,
                athlete_id=athlete_id,
                error=str(e),
                exc_info=True,
            )
            raise StravaTokenStorageError(
                f"Failed to store Strava tokens: {e!s}"
            ) from e

    async def get_auth(self, user_id: str) -> dict[str, Any] | None:
        """
        Get Strava auth data for a user.

        Args:
            user_id: User ID.

        Returns:
            Dictionary with decrypted tokens and metadata, or None if not found.
        """
        stmt = text("""
            SELECT athlete_id, encrypted_access_token, encrypted_refresh_token,
                   expires_at, needs_reauth, strava_webhook_subscription_id
            FROM user_strava_auth
            WHERE user_id = :user_id
        """)

        result = await self.connection.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if not row:
            return None

        return {
            "athlete_id": row.athlete_id,
            "access_token": self.decrypt(row.encrypted_access_token),
            "refresh_token": self.decrypt(row.encrypted_refresh_token),
            "expires_at": row.expires_at,
            "needs_reauth": row.needs_reauth,
            "is_expired": datetime.now(UTC) >= row.expires_at,
            "strava_webhook_subscription_id": row.strava_webhook_subscription_id,
        }

    async def delete_tokens(self, user_id: str) -> bool:
        """
        Delete Strava OAuth tokens for a user.

        Args:
            user_id: User ID.

        Returns:
            True if tokens were deleted, False if not found.
        """
        stmt = text("""
            DELETE FROM user_strava_auth
            WHERE user_id = :user_id
        """)

        async with unit_of_work(self.connection):
            result = await self.connection.execute(stmt, {"user_id": user_id})
            deleted = result.rowcount > 0

        if deleted:
            logger.info("Deleted Strava OAuth tokens", user_id=user_id)

        return deleted

    async def is_connected(self, user_id: str) -> bool:
        """
        Check whether a user has a Strava connection.

        Args:
            user_id: User ID.

        Returns:
            True if a Strava auth row exists for the user.
        """
        stmt = text("""
            SELECT 1 FROM user_strava_auth WHERE user_id = :user_id
        """)
        result = await self.connection.execute(stmt, {"user_id": user_id})
        return result.fetchone() is not None

    async def set_webhook_subscription(
        self,
        user_id: str,
        subscription_id: int | None,
        verify_token: str | None,
    ) -> None:
        """
        Store or clear the Strava webhook subscription data.

        Args:
            user_id: User ID.
            subscription_id: Strava push subscription ID, or None to clear.
            verify_token: Verify token used during subscription handshake,
                or None to clear.
        """
        stmt = text("""
            UPDATE user_strava_auth
            SET strava_webhook_subscription_id = :subscription_id,
                strava_webhook_verify_token = :verify_token,
                updated_at = :now
            WHERE user_id = :user_id
        """)
        async with unit_of_work(self.connection):
            await self.connection.execute(
                stmt,
                {
                    "user_id": user_id,
                    "subscription_id": subscription_id,
                    "verify_token": verify_token,
                    "now": datetime.now(UTC),
                },
            )
        logger.info(
            "Updated Strava webhook subscription",
            user_id=user_id,
            subscription_id=subscription_id,
        )

    async def set_webhook_verify_token(
        self,
        user_id: str,
        verify_token: str,
    ) -> None:
        """
        Store the webhook verify token without overwriting subscription_id.

        Used before calling Strava's subscribe API so the handshake GET
        can look up the verify token. Preserves any existing subscription_id
        to avoid losing a valid ID if subscribe() subsequently fails.

        Args:
            user_id: User ID.
            verify_token: Verify token for subscription handshake.
        """
        stmt = text("""
            UPDATE user_strava_auth
            SET strava_webhook_verify_token = :verify_token,
                updated_at = :now
            WHERE user_id = :user_id
        """)
        async with unit_of_work(self.connection):
            await self.connection.execute(
                stmt,
                {
                    "user_id": user_id,
                    "verify_token": verify_token,
                    "now": datetime.now(UTC),
                },
            )
        logger.info(
            "Updated Strava webhook verify token",
            user_id=user_id,
        )

    async def is_valid_webhook_verify_token(self, token: str) -> bool:
        """
        Check whether a given webhook verify token exists.

        Used during Strava's validation handshake to confirm the token
        matches one we've generated, without assuming a single token for
        all users.

        Args:
            token: The verify token to check.

        Returns:
            True if the token exists, False otherwise.
        """
        stmt = text("""
            SELECT 1
            FROM user_strava_auth
            WHERE strava_webhook_verify_token = :token
            LIMIT 1
        """)
        result = await self.connection.execute(stmt, {"token": token})
        return result.fetchone() is not None

    async def has_subscription_id(self, subscription_id: int) -> bool:
        """
        Check whether a given Strava webhook subscription ID is stored.

        Used by the webhook POST endpoint to validate that incoming events
        come from a known subscription before enqueuing work.

        Args:
            subscription_id: The subscription ID from the webhook event.

        Returns:
            True if the subscription ID is found in any auth row.
        """
        stmt = text("""
            SELECT 1
            FROM user_strava_auth
            WHERE strava_webhook_subscription_id = :sub_id
            LIMIT 1
        """)
        result = await self.connection.execute(stmt, {"sub_id": subscription_id})
        return result.fetchone() is not None

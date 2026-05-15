"""
Snipe-IT Token Service for managing OAuth tokens in core API.

Provides secure storage and retrieval of Snipe-IT OAuth tokens with
encryption via Fernet and proper database management. Token exchange
and refresh are delegated to the Snipe-IT auth endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger()


class SnipeItTokenNotFoundError(Exception):
    """Raised when Snipe-IT OAuth tokens are not found for a user."""


class SnipeItTokenStorageError(Exception):
    """Raised when token storage operations fail."""


class SnipeItTokenService:
    """
    Service for managing Snipe-IT OAuth tokens in the main API.

    Provides encrypted token CRUD operations against the ``user_snipe_it_auth``
    table. Actual token exchange and refresh are handled by the Snipe-IT auth
    endpoints, which call this service to persist the results.
    """

    def __init__(self, connection: AsyncConnection, encryption_key: str) -> None:
        """
        Initialize the Snipe-IT Token Service.

        Args:
            connection: Database connection for token operations.
            encryption_key: Base64-encoded Fernet key for token encryption.
                May be empty if Snipe-IT is not configured; operations that
                require encryption will raise ``SnipeItTokenStorageError``.
        """
        self.connection = connection
        self._encryption_key = encryption_key
        self._fernet: Fernet | None = None

    @property
    def fernet(self) -> Fernet:
        """Lazily initialise Fernet so the service can be created even when
        ``snipeit_encryption_key`` is empty (unconfigured environments)."""
        if self._fernet is None:
            if not self._encryption_key:
                raise SnipeItTokenStorageError(
                    "Snipe-IT encryption key is not configured"
                )
            try:
                self._fernet = Fernet(self._encryption_key.encode())
            except (ValueError, Exception) as e:
                raise SnipeItTokenStorageError(
                    f"Invalid Snipe-IT encryption key: {e!s}"
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
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
    ) -> None:
        """
        Store Snipe-IT OAuth tokens for a user.

        Uses UPSERT to handle re-connection: if the user already has a
        Snipe-IT auth row, it updates the tokens rather than inserting a
        duplicate.

        Args:
            user_id: Authenticated user's ID.
            access_token: OAuth access token (will be encrypted).
            refresh_token: OAuth refresh token (will be encrypted).
            token_expires_at: UTC datetime when the access token expires.

        Raises:
            SnipeItTokenStorageError: If storage operation fails.
        """
        try:
            encrypted_access_token = self.encrypt(access_token)
            encrypted_refresh_token = self.encrypt(refresh_token)

            stmt = text("""
                INSERT INTO user_snipe_it_auth (
                    user_id, encrypted_access_token,
                    encrypted_refresh_token, token_expires_at,
                    needs_reauth, created_at, updated_at
                )
                VALUES (
                    :user_id, :encrypted_access_token,
                    :encrypted_refresh_token, :token_expires_at,
                    FALSE, :now, :now
                )
                ON CONFLICT (user_id)
                DO UPDATE SET
                    encrypted_access_token = EXCLUDED.encrypted_access_token,
                    encrypted_refresh_token = EXCLUDED.encrypted_refresh_token,
                    token_expires_at = EXCLUDED.token_expires_at,
                    needs_reauth = FALSE,
                    updated_at = EXCLUDED.updated_at
            """)

            now = datetime.now(UTC)
            await self.connection.execute(
                stmt,
                {
                    "user_id": user_id,
                    "encrypted_access_token": encrypted_access_token,
                    "encrypted_refresh_token": encrypted_refresh_token,
                    "token_expires_at": token_expires_at,
                    "now": now,
                },
            )

            logger.info(
                "Stored Snipe-IT OAuth tokens",
                user_id=user_id,
                token_expires_at=token_expires_at.isoformat(),
            )

        except SnipeItTokenStorageError:
            raise
        except Exception as e:
            logger.error(
                "Failed to store Snipe-IT tokens",
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            raise SnipeItTokenStorageError(
                f"Failed to store Snipe-IT tokens: {e!s}"
            ) from e

    async def get_auth(self, user_id: str) -> dict[str, Any] | None:
        """
        Get Snipe-IT auth data for a user.

        Args:
            user_id: User ID.

        Returns:
            Dictionary with decrypted tokens and metadata, or None if not found.
        """
        stmt = text("""
            SELECT encrypted_access_token, encrypted_refresh_token,
                   token_expires_at, needs_reauth
            FROM user_snipe_it_auth
            WHERE user_id = :user_id
        """)

        result = await self.connection.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if not row:
            return None

        return {
            "access_token": self.decrypt(row.encrypted_access_token),
            "refresh_token": self.decrypt(row.encrypted_refresh_token),
            "token_expires_at": row.token_expires_at,
            "needs_reauth": row.needs_reauth,
            "is_expired": datetime.now(UTC) >= row.token_expires_at,
        }

    async def delete_tokens(self, user_id: str) -> bool:
        """
        Delete Snipe-IT OAuth tokens for a user.

        Args:
            user_id: User ID.

        Returns:
            True if tokens were deleted, False if not found.
        """
        stmt = text("""
            DELETE FROM user_snipe_it_auth
            WHERE user_id = :user_id
        """)

        result = await self.connection.execute(stmt, {"user_id": user_id})
        deleted = result.rowcount > 0

        if deleted:
            logger.info("Deleted Snipe-IT OAuth tokens", user_id=user_id)

        return deleted

    async def is_connected(self, user_id: str) -> bool:
        """
        Check whether a user has a Snipe-IT OAuth connection.

        Args:
            user_id: User ID.

        Returns:
            True if a Snipe-IT auth row exists for the user.
        """
        stmt = text("""
            SELECT 1 FROM user_snipe_it_auth WHERE user_id = :user_id
        """)
        result = await self.connection.execute(stmt, {"user_id": user_id})
        return result.fetchone() is not None

    async def commit(self) -> None:
        """
        Explicitly commit the current transaction.

        Used to flush pending writes so that concurrent requests can
        see the data.
        """
        await self.connection.commit()

"""
Snipe-IT Token Service for managing API keys in core API.

Provides secure storage and retrieval of Snipe-IT API keys with
encryption via Fernet and proper database management.
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
    """Raised when Snipe-IT API key is not found for a user."""


class SnipeItTokenStorageError(Exception):
    """Raised when API key storage operations fail."""


class SnipeItTokenService:
    """
    Service for managing Snipe-IT API keys in the main API.

    Provides encrypted CRUD operations against the ``user_snipe_it_auth``
    table. The API key is a personal access token generated in the
    Snipe-IT admin panel.
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

    async def store_api_key(
        self,
        user_id: str,
        api_key: str,
    ) -> None:
        """
        Store a Snipe-IT API key for a user.

        Uses UPSERT to handle re-connection: if the user already has a
        Snipe-IT auth row, it updates the key rather than inserting a
        duplicate.

        Args:
            user_id: Authenticated user's ID.
            api_key: Snipe-IT personal access token (will be encrypted).

        Raises:
            SnipeItTokenStorageError: If storage operation fails.
        """
        try:
            encrypted_api_key = self.encrypt(api_key)

            stmt = text("""
                INSERT INTO user_snipe_it_auth (
                    user_id, encrypted_api_key,
                    needs_reauth, created_at, updated_at
                )
                VALUES (
                    :user_id, :encrypted_api_key,
                    FALSE, :now, :now
                )
                ON CONFLICT (user_id)
                DO UPDATE SET
                    encrypted_api_key = EXCLUDED.encrypted_api_key,
                    needs_reauth = FALSE,
                    updated_at = EXCLUDED.updated_at
            """)

            now = datetime.now(UTC)
            await self.connection.execute(
                stmt,
                {
                    "user_id": user_id,
                    "encrypted_api_key": encrypted_api_key,
                    "now": now,
                },
            )

            logger.info("Stored Snipe-IT API key", user_id=user_id)

        except SnipeItTokenStorageError:
            raise
        except Exception as e:
            logger.error(
                "Failed to store Snipe-IT API key",
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            raise SnipeItTokenStorageError(
                f"Failed to store Snipe-IT API key: {e!s}"
            ) from e

    async def get_auth(self, user_id: str) -> dict[str, Any] | None:
        """
        Get Snipe-IT auth data for a user.

        Args:
            user_id: User ID.

        Returns:
            Dictionary with decrypted API key and metadata, or None if not found.
        """
        stmt = text("""
            SELECT encrypted_api_key, needs_reauth
            FROM user_snipe_it_auth
            WHERE user_id = :user_id
        """)

        result = await self.connection.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if not row:
            return None

        return {
            "api_key": self.decrypt(row.encrypted_api_key),
            "needs_reauth": row.needs_reauth,
        }

    async def delete_tokens(self, user_id: str) -> bool:
        """
        Delete Snipe-IT API key for a user.

        Args:
            user_id: User ID.

        Returns:
            True if the key was deleted, False if not found.
        """
        stmt = text("""
            DELETE FROM user_snipe_it_auth
            WHERE user_id = :user_id
        """)

        result = await self.connection.execute(stmt, {"user_id": user_id})
        deleted = result.rowcount > 0

        if deleted:
            logger.info("Deleted Snipe-IT API key", user_id=user_id)

        return deleted

    async def is_connected(self, user_id: str) -> bool:
        """
        Check whether a user has a Snipe-IT API key stored.

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

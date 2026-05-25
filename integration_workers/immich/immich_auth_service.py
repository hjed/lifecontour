"""
Immich API key authentication service for the worker.

Manages API key retrieval from the database and Fernet decryption.
This service runs inside the worker container and reads from the
``user_immich_auth`` table.
"""

from __future__ import annotations

from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

logger = structlog.get_logger()


class ImmichAuthService:
    """Manages Immich API key retrieval with encrypted storage.

    Provides encryption/decryption utilities and database API key retrieval
    for the worker process.

    Args:
        encryption_key: Fernet-compatible encryption key string.
    """

    def __init__(self, encryption_key: str) -> None:
        self._fernet = Fernet(encryption_key.encode())

    def encrypt(self, value: str) -> bytes:
        """Encrypt a string value using Fernet.

        Args:
            value: Plaintext string to encrypt.

        Returns:
            Encrypted bytes.
        """
        return self._fernet.encrypt(value.encode())

    def decrypt(self, encrypted: bytes) -> str:
        """Decrypt Fernet-encrypted bytes.

        Args:
            encrypted: Fernet-encrypted bytes.

        Returns:
            Original plaintext string.
        """
        return self._fernet.decrypt(encrypted).decode()

    async def get_api_key(self, user_id: str, session: Any) -> str | None:
        """Retrieve and decrypt Immich API key for a user.

        Args:
            user_id: Internal user ID.
            session: Database session (AsyncSession or AsyncConnection).

        Returns:
            Decrypted API key string, or ``None`` if no auth row exists
            or decryption fails.
        """
        stmt = text("""
            SELECT encrypted_api_key
            FROM user_immich_auth
            WHERE user_id = :user_id
        """)

        result = await session.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if row is None:
            logger.info("No Immich auth found for user", user_id=user_id)
            return None

        try:
            return self.decrypt(row.encrypted_api_key)
        except InvalidToken:
            logger.warning(
                "Immich API key failed decryption (invalid key or corrupted data)",
                user_id=user_id,
            )
            return None

    async def get_server_url(self, user_id: str, session: Any) -> str | None:
        """Retrieve the Immich server URL from user settings.

        Args:
            user_id: Internal user ID.
            session: Database session.

        Returns:
            Server URL string, or ``None`` if not configured.
        """
        stmt = text("""
            SELECT server_url
            FROM user_immich_auth
            WHERE user_id = :user_id
        """)

        result = await session.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if row is None or row.server_url is None:
            return None

        return str(row.server_url)

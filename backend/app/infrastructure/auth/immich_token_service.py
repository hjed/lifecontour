"""
Immich API Key Authentication Service.

Handles encrypting and saving the Immich API key to the database,
and validating it against the Immich instance.
"""

import httpx
import structlog
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger()


class ImmichAuthException(Exception):
    """Base exception for Immich auth errors."""


class ImmichValidationException(ImmichAuthException):
    """Raised when the Immich server or API key is invalid."""


class ImmichTokenStorageError(ImmichAuthException):
    """Raised when encryption/decryption operations fail."""


class ImmichTokenService:
    """Service for managing Immich API keys."""

    def __init__(self, connection: AsyncConnection, encryption_key: str) -> None:
        """Initialize the service.

        Args:
            connection: Database connection
            encryption_key: Base64-encoded Fernet key for token encryption.
                May be empty if Immich is not configured; operations that
                require encryption will raise ``ImmichTokenStorageError``.
        """
        self._connection = connection
        self._encryption_key = encryption_key
        self._fernet: Fernet | None = None

    @property
    def fernet(self) -> Fernet:
        """Lazily initialise Fernet so the service can be created even when
        ``immich_encryption_key`` is empty (unconfigured environments)."""
        if self._fernet is None:
            if not self._encryption_key:
                raise ImmichTokenStorageError("Immich encryption key is not configured")
            try:
                self._fernet = Fernet(self._encryption_key.encode())
            except (ValueError, Exception) as e:
                raise ImmichTokenStorageError(
                    f"Invalid Immich encryption key: {e!s}"
                ) from e
        return self._fernet

    async def validate_and_save_credentials(
        self, user_id: str, server_url: str, api_key: str
    ) -> None:
        """Validate the API key against the server and save it.

        Args:
            user_id: The internal user ID
            server_url: The Immich server URL
            api_key: The Immich API key

        Raises:
            ImmichValidationException: If validation fails
        """
        # Normalize inputs
        server_url = server_url.strip().rstrip("/")
        api_key = api_key.strip()

        if not api_key:
            raise ImmichValidationException("API key must not be empty")

        # Validate with the server
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{server_url}/api/server/about",
                    headers={"Accept": "application/json", "x-api-key": api_key},
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            raise ImmichValidationException(
                f"Invalid server URL or API key: {e}"
            ) from e

        # Encrypt the API key
        encrypted_key = self.fernet.encrypt(api_key.encode())

        # UPSERT the credentials
        stmt = text("""
            INSERT INTO user_immich_auth (user_id, server_url, encrypted_api_key, created_at, updated_at)
            VALUES (:user_id, :server_url, :encrypted_api_key, now(), now())
            ON CONFLICT (user_id) DO UPDATE SET
                server_url = EXCLUDED.server_url,
                encrypted_api_key = EXCLUDED.encrypted_api_key,
                updated_at = now()
        """)
        await self._connection.execute(
            stmt,
            {
                "user_id": user_id,
                "server_url": server_url,
                "encrypted_api_key": encrypted_key,
            },
        )

    async def disconnect(self, user_id: str) -> None:
        """Disconnect the integration by removing the credentials.

        Args:
            user_id: The internal user ID
        """
        stmt = text("DELETE FROM user_immich_auth WHERE user_id = :user_id")
        await self._connection.execute(stmt, {"user_id": user_id})

    async def get_credentials(self, user_id: str) -> tuple[str | None, str | None]:
        """Fetch and decrypt the user's Immich server URL and API key.

        Args:
            user_id: The internal user ID.

        Returns:
            Tuple of (server_url, api_key), or (None, None) if not configured.

        Raises:
            ImmichTokenStorageError: If decryption fails.
        """
        query = text("""
            SELECT server_url, encrypted_api_key
            FROM user_immich_auth
            WHERE user_id = :user_id
        """)
        result = await self._connection.execute(query, {"user_id": user_id})
        row = result.fetchone()
        if row is None:
            return None, None

        api_key = self.fernet.decrypt(row.encrypted_api_key).decode()
        return row.server_url, api_key

    async def get_server_url(self, user_id: str) -> str | None:
        """Fetch the user's Immich server URL without decrypting the API key.

        Used to build external links for display, where only the server URL is
        needed. Avoids decryption so link display never fails on a decrypt error.

        Args:
            user_id: The internal user ID.

        Returns:
            The Immich server URL, or None if not configured.
        """
        query = text("""
            SELECT server_url
            FROM user_immich_auth
            WHERE user_id = :user_id
        """)
        result = await self._connection.execute(query, {"user_id": user_id})
        row = result.fetchone()
        if row is None:
            return None
        server_url: str | None = row.server_url
        return server_url

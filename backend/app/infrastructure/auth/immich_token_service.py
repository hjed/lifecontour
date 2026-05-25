"""
Immich API Key Authentication Service.

Handles encrypting and saving the Immich API key to the database,
and validating it against the Immich instance.
"""

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class ImmichAuthException(Exception):
    """Base exception for Immich auth errors."""


class ImmichValidationException(ImmichAuthException):
    """Raised when the Immich server or API key is invalid."""


class ImmichTokenService:
    """Service for managing Immich API keys."""

    def __init__(self, connection: AsyncConnection, encryption_key: str) -> None:
        """Initialize the service.

        Args:
            connection: Database connection
            encryption_key: Fernet-compatible encryption key string
        """
        self._connection = connection
        self._fernet = Fernet(encryption_key.encode())

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
        # Normalize URL
        server_url = server_url.rstrip("/")

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
        encrypted_key = self._fernet.encrypt(api_key.encode())

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

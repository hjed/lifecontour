"""
Snipe-IT OAuth authentication service for the worker.

Manages token retrieval from the database, Fernet encryption/decryption,
and token refresh via the Snipe-IT OAuth endpoint. This service runs
inside the worker container and reads from the ``user_snipe_it_auth``
and ``snipeit_settings`` tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

logger = structlog.get_logger()


@dataclass(frozen=True)
class SnipeItTokenData:
    """Parsed Snipe-IT OAuth token data.

    Attributes:
        access_token: Short-lived access token for API calls.
        refresh_token: Long-lived token for obtaining new access tokens.
        expires_at: UTC datetime when the access token expires.
    """

    access_token: str
    refresh_token: str
    expires_at: datetime


class SnipeItAuthService:
    """Manages Snipe-IT OAuth tokens with encrypted storage.

    Provides encryption/decryption utilities, database token retrieval,
    base URL lookup, and token refresh for the worker process.

    The ``httpx.AsyncClient`` used for token refresh is injected for
    testability and timeout control.

    Args:
        encryption_key: Fernet-compatible encryption key string.
        http_client: Injected async HTTP client for OAuth requests.
            If ``None``, a default client with 30 s timeout is created.
    """

    def __init__(
        self,
        encryption_key: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._fernet = Fernet(encryption_key.encode())
        self._http_client = http_client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = http_client is None

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

    async def get_tokens(self, user_id: str, session: Any) -> SnipeItTokenData | None:
        """Retrieve and decrypt Snipe-IT OAuth tokens for a user.

        Args:
            user_id: Internal user ID.
            session: Database session (AsyncSession or AsyncConnection).

        Returns:
            Decrypted ``SnipeItTokenData``, or ``None`` if no auth row
            exists or the user needs re-authentication.
        """
        stmt = text("""
            SELECT encrypted_access_token, encrypted_refresh_token,
                   token_expires_at, needs_reauth
            FROM user_snipe_it_auth
            WHERE user_id = :user_id
        """)

        result = await session.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if row is None:
            logger.info("No Snipe-IT auth found for user", user_id=user_id)
            return None

        if row.needs_reauth:
            logger.warning(
                "Snipe-IT auth needs re-authentication",
                user_id=user_id,
            )
            return None

        try:
            access_token = self.decrypt(row.encrypted_access_token)
            refresh_token = self.decrypt(row.encrypted_refresh_token)
        except InvalidToken:
            logger.warning(
                "Snipe-IT auth tokens failed decryption (invalid key or corrupted data)",
                user_id=user_id,
            )
            return None

        return SnipeItTokenData(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=row.token_expires_at,
        )

    async def get_base_url(self, user_id: str, session: Any) -> str | None:
        """Retrieve the Snipe-IT base URL from user settings.

        Args:
            user_id: Internal user ID.
            session: Database session.

        Returns:
            Base URL string, or ``None`` if not configured.
        """
        stmt = text("""
            SELECT base_url
            FROM snipeit_settings
            WHERE user_id = :user_id
        """)

        result = await session.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if row is None or row.base_url is None:
            return None

        return str(row.base_url)

    async def refresh_token(
        self,
        base_url: str,
        refresh_token_value: str,
        client_id: str,
        client_secret: str,
    ) -> SnipeItTokenData:
        """Refresh an expired access token via the Snipe-IT OAuth endpoint.

        Uses the injected ``http_client`` (with bounded timeout) to
        prevent indefinite blocking.

        Args:
            base_url: Snipe-IT instance base URL.
            refresh_token_value: Current refresh token.
            client_id: OAuth application client ID.
            client_secret: OAuth application client secret.

        Returns:
            New ``SnipeItTokenData`` with refreshed tokens.

        Raises:
            httpx.HTTPStatusError: If the refresh request fails.
        """
        token_url = f"{base_url.rstrip('/')}/oauth/token"

        response = await self._http_client.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token_value,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        response.raise_for_status()
        data = response.json()

        expires_in = int(data.get("expires_in", 3600))
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        logger.info("Refreshed Snipe-IT access token")

        return SnipeItTokenData(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=expires_at,
        )

    async def close(self) -> None:
        """Close the HTTP client if this service owns it."""
        if self._owns_client:
            await self._http_client.aclose()

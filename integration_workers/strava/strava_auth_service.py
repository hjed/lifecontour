"""
Strava OAuth authentication service.

Manages Strava OAuth 2.0 token lifecycle: authorization URL generation,
code exchange, token refresh, and revocation. Provides Fernet encryption
for secure token storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
import structlog
from cryptography.fernet import Fernet

logger = structlog.get_logger()

# Strava OAuth endpoints
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"

# Required scope per product specification
STRAVA_SCOPE = "activity:read_all"


@dataclass(frozen=True)
class StravaTokenData:
    """
    Parsed Strava OAuth token response data.

    Attributes:
        access_token: Short-lived access token for API calls.
        refresh_token: Long-lived token for obtaining new access tokens.
        expires_at: UTC datetime when the access token expires.
        athlete_id: Strava's numeric athlete identifier.
    """

    access_token: str
    refresh_token: str
    expires_at: datetime
    athlete_id: int


class StravaAuthService:
    """
    Manages Strava OAuth 2.0 tokens with encrypted storage.

    Handles authorization URL generation, authorization code exchange,
    token refresh, and token revocation. All sensitive values are encrypted
    using Fernet symmetric encryption before storage.
    """

    def __init__(
        self,
        encryption_key: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        """
        Initialize the Strava auth service.

        Args:
            encryption_key: Fernet-compatible encryption key for token storage.
            client_id: Strava OAuth application client ID.
            client_secret: Strava OAuth application client secret.
        """
        self._fernet = Fernet(encryption_key.encode())
        self._client_id = client_id
        self._client_secret = client_secret

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

    def build_authorization_url(self, redirect_uri: str, state: str) -> str:
        """
        Build the Strava OAuth authorization URL.

        Generates a URL that redirects the user to Strava's consent screen
        with the ``activity:read_all`` scope.

        Args:
            redirect_uri: URL to redirect back to after authorization.
            state: CSRF state parameter for security.

        Returns:
            Full Strava authorization URL with query parameters.
        """
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": STRAVA_SCOPE,
            "state": state,
            "approval_prompt": "auto",
        }
        return f"{STRAVA_AUTHORIZE_URL}?{urlencode(params)}"

    def parse_token_response(self, data: dict[str, object]) -> StravaTokenData:
        """
        Parse a Strava token exchange response.

        Extracts the access token, refresh token, expiration, and athlete ID
        from the JSON response returned by Strava's ``/oauth/token`` endpoint.

        Args:
            data: Parsed JSON response from Strava.

        Returns:
            StravaTokenData with extracted fields.

        Raises:
            KeyError: If required fields are missing.
            ValueError: If athlete data is missing or malformed.
        """
        athlete = data.get("athlete")
        if not athlete or not isinstance(athlete, dict):
            raise ValueError("Missing or invalid athlete data in token response")

        expires_at_epoch = data["expires_at"]
        if not isinstance(expires_at_epoch, (int, float)):
            raise ValueError(f"Invalid expires_at value: {expires_at_epoch}")

        return StravaTokenData(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=datetime.fromtimestamp(float(expires_at_epoch), tz=UTC),
            athlete_id=int(athlete["id"]),
        )

    async def exchange_code(self, code: str) -> StravaTokenData:
        """
        Exchange an authorization code for access and refresh tokens.

        Args:
            code: Authorization code from the OAuth callback.

        Returns:
            StravaTokenData with tokens and athlete info.

        Raises:
            httpx.HTTPStatusError: If the token exchange fails.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                STRAVA_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            token_data = response.json()

        result = self.parse_token_response(token_data)

        logger.info(
            "Exchanged Strava authorization code",
            athlete_id=result.athlete_id,
        )
        return result

    async def refresh_token(self, refresh_token_value: str) -> StravaTokenData:
        """
        Refresh an expired access token.

        Args:
            refresh_token_value: The current refresh token.

        Returns:
            StravaTokenData with new tokens.

        Raises:
            httpx.HTTPStatusError: If the refresh request fails.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                STRAVA_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token_value,
                },
            )
            response.raise_for_status()
            token_data = response.json()

        logger.info("Refreshed Strava access token")
        return self.parse_token_response(token_data)

    async def revoke_token(self, access_token: str) -> None:
        """
        Revoke a Strava OAuth token (deauthorize).

        Calls Strava's deauthorize endpoint to revoke the application's
        access. After this call, the stored tokens are no longer valid.

        Args:
            access_token: The access token to revoke.

        Raises:
            httpx.HTTPStatusError: If the revocation request fails.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                STRAVA_DEAUTHORIZE_URL,
                data={"access_token": access_token},
            )
            response.raise_for_status()

        logger.info("Revoked Strava OAuth token")

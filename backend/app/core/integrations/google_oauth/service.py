"""
Google OAuth service for managing Google account connections.

Provides OAuth2 flow management including authorization URL generation,
token exchange, and account management for Google Contacts integration.
"""

import base64
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import structlog

from app.core.integrations.encryption import EncryptionService
from app.core.integrations.google_oauth.exceptions import (
    GoogleAccountNotFoundError,
    GoogleOAuthConfigurationError,
    GoogleOAuthStateError,
    GoogleOAuthTokenError,
)
from app.core.integrations.google_oauth.models import (
    GOOGLE_CONTACTS_READONLY_SCOPE,
    GOOGLE_OAUTH_AUTHORIZATION_URL,
    GOOGLE_OAUTH_STATE_MAX_AGE_SECONDS,
    GOOGLE_OAUTH_TOKEN_URL,
    GOOGLE_USERINFO_EMAIL_SCOPE,
    GOOGLE_USERINFO_URL,
    GoogleAccount,
    GoogleOAuthState,
    GoogleOAuthTokens,
)
from app.core.integrations.google_oauth.repository import GoogleOAuthRepository
from app.infrastructure.config import Settings

logger = structlog.get_logger()


class GoogleOAuthService:
    """
    Service for managing Google OAuth2 authentication flow.

    Handles authorization URL generation, token exchange, secure token
    storage, and account management.
    """

    def __init__(
        self,
        repository: GoogleOAuthRepository,
        encryption_service: EncryptionService,
        settings: Settings,
    ) -> None:
        """
        Initialize Google OAuth service.

        Args:
            repository: Repository for token storage
            encryption_service: Service for token encryption
            settings: Application settings
        """
        self._repository = repository
        self._encryption = encryption_service
        self._settings = settings

        # Log warning for unconfigured state. We intentionally allow the service
        # to be created without credentials because Google OAuth is an optional
        # feature. Actual validation happens via _ensure_configured() which is
        # called before any OAuth operations that require credentials.
        if not settings.google_client_id or not settings.google_client_secret:
            logger.warning("Google OAuth credentials not configured")

    def _ensure_configured(self) -> None:
        """Raise error if Google OAuth is not configured."""
        if not self._settings.google_client_id:
            raise GoogleOAuthConfigurationError("Google OAuth client ID not configured")
        if not self._settings.google_client_secret:
            raise GoogleOAuthConfigurationError(
                "Google OAuth client secret not configured"
            )

    def create_oauth_state(
        self,
        user_id: str,
        redirect_url: str | None = None,
    ) -> GoogleOAuthState:
        """
        Create a new OAuth state for CSRF protection.

        Args:
            user_id: Current user's ID
            redirect_url: Optional URL to redirect after OAuth completion

        Returns:
            GoogleOAuthState object
        """
        return GoogleOAuthState(
            user_id=user_id,
            nonce=secrets.token_urlsafe(32),
            created_at=datetime.now(UTC),
            redirect_url=redirect_url,
        )

    def encode_state(self, state: GoogleOAuthState) -> str:
        """
        Encode OAuth state for URL parameter.

        Uses encryption to prevent tampering.

        Args:
            state: OAuth state to encode

        Returns:
            Encrypted state string
        """
        state_data = {
            "user_id": state.user_id,
            "nonce": state.nonce,
            "created_at": state.created_at.isoformat(),
            "redirect_url": state.redirect_url,
        }
        state_json = json.dumps(state_data)
        encrypted = self._encryption.encrypt(state_json)
        # Convert bytes to base64 string for URL safety
        return base64.urlsafe_b64encode(encrypted).decode("utf-8")

    def decode_state(self, encoded_state: str) -> GoogleOAuthState:
        """
        Decode and validate OAuth state.

        Args:
            encoded_state: Encrypted state string from callback

        Returns:
            Decoded GoogleOAuthState

        Raises:
            GoogleOAuthStateError: If state is invalid or expired
        """
        try:
            encrypted = base64.urlsafe_b64decode(encoded_state.encode("utf-8"))
            state_json = self._encryption.decrypt(encrypted)
            state_data = json.loads(state_json)

            state = GoogleOAuthState(
                user_id=state_data["user_id"],
                nonce=state_data["nonce"],
                created_at=datetime.fromisoformat(state_data["created_at"]),
                redirect_url=state_data.get("redirect_url"),
            )

            if state.is_expired(GOOGLE_OAUTH_STATE_MAX_AGE_SECONDS):
                raise GoogleOAuthStateError("OAuth state has expired")

            return state

        except GoogleOAuthStateError:
            raise
        except Exception as e:
            logger.error("Failed to decode OAuth state", error=str(e))
            raise GoogleOAuthStateError("Invalid OAuth state") from e

    def get_authorization_url(
        self,
        state: GoogleOAuthState,
        callback_url: str,
        scopes: list[str] | None = None,
    ) -> str:
        """
        Generate Google OAuth authorization URL.

        Args:
            state: OAuth state for CSRF protection
            callback_url: URL for OAuth callback
            scopes: OAuth scopes to request (defaults to contacts readonly)

        Returns:
            Authorization URL to redirect user to
        """
        self._ensure_configured()

        if scopes is None:
            scopes = [GOOGLE_CONTACTS_READONLY_SCOPE, GOOGLE_USERINFO_EMAIL_SCOPE]

        params = {
            "client_id": self._settings.google_client_id,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": self.encode_state(state),
        }

        return f"{GOOGLE_OAUTH_AUTHORIZATION_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(
        self,
        code: str,
        callback_url: str,
    ) -> GoogleOAuthTokens:
        """
        Exchange authorization code for access and refresh tokens.

        Args:
            code: Authorization code from OAuth callback
            callback_url: Callback URL (must match the one used in auth request)

        Returns:
            GoogleOAuthTokens containing access and refresh tokens

        Raises:
            GoogleOAuthTokenError: If token exchange fails
        """
        self._ensure_configured()

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    GOOGLE_OAUTH_TOKEN_URL,
                    data={
                        "client_id": self._settings.google_client_id,
                        "client_secret": self._settings.google_client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": callback_url,
                    },
                )

                if response.status_code != 200:
                    error_data = response.json()
                    error_code = error_data.get("error", "unknown")
                    error_description = error_data.get(
                        "error_description", "Token exchange failed"
                    )
                    logger.error(
                        "Google OAuth token exchange failed",
                        status_code=response.status_code,
                        error=error_code,
                        description=error_description,
                    )
                    raise GoogleOAuthTokenError(
                        message=error_description,
                        error_code=error_code,
                    )

                token_data = response.json()
                return GoogleOAuthTokens(
                    access_token=token_data["access_token"],
                    refresh_token=token_data.get("refresh_token"),
                    expires_in=token_data.get("expires_in", 3600),
                    token_type=token_data.get("token_type", "Bearer"),
                    scope=token_data.get("scope", ""),
                )

            except httpx.RequestError as e:
                logger.error("Google OAuth request failed", error=str(e))
                raise GoogleOAuthTokenError(
                    message="Failed to connect to Google OAuth service"
                ) from e

    async def get_user_email(self, access_token: str) -> str:
        """
        Get the user's email from Google's userinfo endpoint.

        Args:
            access_token: Valid Google access token

        Returns:
            User's Google email address

        Raises:
            GoogleOAuthTokenError: If userinfo request fails
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    raise GoogleOAuthTokenError(
                        message="Failed to get user info from Google"
                    )

                user_data = response.json()
                email = user_data.get("email")

                if not email:
                    raise GoogleOAuthTokenError(
                        message="Email not found in Google user info - ensure email scope is granted"
                    )

                return str(email)

            except httpx.RequestError as e:
                logger.error("Google userinfo request failed", error=str(e))
                raise GoogleOAuthTokenError(
                    message="Failed to connect to Google userinfo service"
                ) from e

    async def save_account(
        self,
        user_id: str,
        tokens: GoogleOAuthTokens,
        email: str,
    ) -> GoogleAccount:
        """
        Save Google account with encrypted tokens.

        Args:
            user_id: Site user ID
            tokens: OAuth tokens from Google
            email: Google account email

        Returns:
            Created or updated GoogleAccount
        """
        # Encrypt tokens
        encrypted_access = self._encryption.encrypt(tokens.access_token)
        encrypted_refresh = (
            self._encryption.encrypt(tokens.refresh_token)
            if tokens.refresh_token
            else None
        )

        # Calculate expiration time
        expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)

        # Save to database
        account = await self._repository.save_tokens(
            user_id=user_id,
            email=email,
            encrypted_access_token=encrypted_access,
            encrypted_refresh_token=encrypted_refresh,
            expires_at=expires_at,
        )

        logger.info(
            "Saved Google account",
            user_id=user_id,
            email=email,
        )

        return account

    async def get_accounts(self, user_id: str) -> list[GoogleAccount]:
        """
        Get all connected Google accounts for a user.

        Args:
            user_id: Site user ID

        Returns:
            List of connected GoogleAccount objects
        """
        return await self._repository.get_accounts_for_user(user_id)

    async def get_account(self, user_id: str, email: str) -> GoogleAccount:
        """
        Get a specific connected Google account.

        Args:
            user_id: Site user ID
            email: Google account email

        Returns:
            GoogleAccount if found

        Raises:
            GoogleAccountNotFoundError: If account not found
        """
        account = await self._repository.get_account_by_email(user_id, email)
        if not account:
            raise GoogleAccountNotFoundError(email)
        return account

    async def disconnect_account(self, user_id: str, email: str) -> bool:
        """
        Disconnect and remove a Google account.

        Args:
            user_id: Site user ID
            email: Google account email to disconnect

        Returns:
            True if account was disconnected

        Raises:
            GoogleAccountNotFoundError: If account not found
        """
        result = await self._repository.delete_account(user_id, email)

        logger.info(
            "Disconnected Google account",
            user_id=user_id,
            email=email,
        )

        return result

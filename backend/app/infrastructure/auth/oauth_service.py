"""
OAuth service for handling OAuth2 authentication with multiple providers.

Provides OAuth2 authentication using Authlib with support for GitHub, Microsoft,
Discord, and generic OAuth2 providers.
"""

import base64
import json
import secrets
from typing import Any

import httpx
import structlog
from authlib.common.security import generate_token
from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.auth.models import OAuthUserInfo
from app.infrastructure.config import Settings

logger = structlog.get_logger()

# OAuth error messages
OAUTH_STATE_DECODE_ERROR = "Failed to decode OAuth state"
OAUTH_REDIRECT_URI_MISMATCH = "OAuth redirect URI mismatch"

# OAuth scopes
OAUTH_BASIC_SCOPE = "openid email profile"
GOOGLE_SCOPE = (
    "openid email profile "
    "https://www.googleapis.com/auth/contacts.readonly "
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.readonly"
)


class OAuthService:
    """OAuth service for handling multiple OAuth providers."""

    def __init__(self, settings: Settings) -> None:
        """Initialize OAuth service with settings."""
        self.settings = settings
        self.oauth = OAuth()
        self._configure_providers()

    def _encode_state(
        self, provider: str, redirect_uri: str, csrf_token: str, flow_type: str = "auth"
    ) -> str:
        """
        Encode OAuth state with provider info, CSRF token, and flow type.

        Args:
            provider: OAuth provider name (e.g., 'google', 'github')
            redirect_uri: Redirect URI for OAuth callback
            csrf_token: CSRF token for state validation
            flow_type: Type of OAuth flow. Valid values are:
                - 'auth': for authentication flows (default)
                - 'integration': for integration flows (e.g., Google sync)

        Returns:
            Base64-encoded JSON state parameter
        """
        state_data = {
            "provider": provider,
            "redirect_uri": redirect_uri,
            "csrf_token": csrf_token,
            "flow_type": flow_type,  # 'auth' for authentication, 'integration' for integration
        }
        # Base64 encode the JSON state data
        state_json = json.dumps(state_data)
        encoded_state = base64.urlsafe_b64encode(state_json.encode()).decode()
        return encoded_state

    def _decode_state(self, encoded_state: str) -> dict[str, str]:
        """Decode OAuth state to extract provider info and CSRF token."""
        try:
            # Base64 decode the state
            state_json = base64.urlsafe_b64decode(encoded_state.encode()).decode()
            state_data: dict[str, str] = json.loads(state_json)

            # Validate required fields
            required_fields = ["provider", "redirect_uri", "csrf_token"]
            if not all(field in state_data for field in required_fields):
                raise ValueError("Missing required fields in state")

            return state_data
        except (ValueError, json.JSONDecodeError, Exception) as e:
            logger.warning(
                OAUTH_STATE_DECODE_ERROR,
                error=str(e),
                has_state=bool(encoded_state),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state parameter",
            ) from e

    def _configure_providers(self) -> None:
        """Configure OAuth providers based on settings."""
        # GitHub provider
        if self.settings.github_client_id and self.settings.github_client_secret:
            try:
                self.oauth.register(
                    name="github",
                    client_id=self.settings.github_client_id,
                    client_secret=self.settings.github_client_secret,
                    authorize_url="https://github.com/login/oauth/authorize",
                    access_token_url="https://github.com/login/oauth/access_token",
                    client_kwargs={"scope": "user:email"},
                    code_challenge_method="S256",
                )
                logger.info("Configured GitHub OAuth provider with PKCE")
            except Exception as e:
                logger.warning(
                    "Failed to configure GitHub OAuth provider", error=str(e)
                )

        # Microsoft provider
        if self.settings.microsoft_client_id and self.settings.microsoft_client_secret:
            try:
                self.oauth.register(
                    name="microsoft",
                    client_id=self.settings.microsoft_client_id,
                    client_secret=self.settings.microsoft_client_secret,
                    authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                    access_token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
                    client_kwargs={"scope": OAUTH_BASIC_SCOPE},
                    code_challenge_method="S256",
                )
                logger.info("Configured Microsoft OAuth provider with PKCE")
            except Exception as e:
                logger.warning(
                    "Failed to configure Microsoft OAuth provider", error=str(e)
                )

        # Discord provider
        if self.settings.discord_client_id and self.settings.discord_client_secret:
            try:
                self.oauth.register(
                    name="discord",
                    client_id=self.settings.discord_client_id,
                    client_secret=self.settings.discord_client_secret,
                    authorize_url="https://discord.com/api/oauth2/authorize",
                    access_token_url="https://discord.com/api/oauth2/token",
                    client_kwargs={"scope": "identify email"},
                    code_challenge_method="S256",
                )
                logger.info("Configured Discord OAuth provider with PKCE")
            except Exception as e:
                logger.warning(
                    "Failed to configure Discord OAuth provider", error=str(e)
                )

        # Google provider for integrations
        if self.settings.google_client_id and self.settings.google_client_secret:
            try:
                self.oauth.register(
                    name="google",
                    client_id=self.settings.google_client_id,
                    client_secret=self.settings.google_client_secret,
                    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                    access_token_url="https://oauth2.googleapis.com/token",
                    client_kwargs={"scope": GOOGLE_SCOPE},
                    code_challenge_method="S256",
                )
                logger.info("Configured Google OAuth provider with PKCE")
            except Exception as e:
                logger.warning(
                    "Failed to configure Google OAuth provider", error=str(e)
                )

        # Generic OAuth2 provider
        if (
            self.settings.oauth_provider_name
            and self.settings.oauth_client_id
            and self.settings.oauth_client_secret
            and self.settings.oauth_authorization_url
            and self.settings.oauth_token_url
        ):
            try:
                # Build client kwargs with userinfo URL if available
                client_kwargs = {"scope": OAUTH_BASIC_SCOPE}
                if self.settings.oauth_userinfo_url:
                    client_kwargs["userinfo_endpoint"] = (
                        self.settings.oauth_userinfo_url
                    )

                self.oauth.register(
                    name=self.settings.oauth_provider_name,
                    client_id=self.settings.oauth_client_id,
                    client_secret=self.settings.oauth_client_secret,
                    authorize_url=self.settings.oauth_authorization_url,
                    access_token_url=self.settings.oauth_token_url,
                    client_kwargs=client_kwargs,
                    code_challenge_method="S256",
                )
                logger.info(
                    "Configured generic OAuth provider with PKCE",
                    provider_name=self.settings.oauth_provider_name,
                    userinfo_url=self.settings.oauth_userinfo_url,
                )
            except Exception as e:
                logger.warning(
                    "Failed to configure generic OAuth provider",
                    provider_name=self.settings.oauth_provider_name,
                    error=str(e),
                )

    def get_available_providers(self) -> list[str]:
        """Get list of available OAuth providers."""
        return list(self.oauth._clients.keys())

    async def get_authorization_url(
        self, request: Request, provider: str, redirect_uri: str
    ) -> str:
        """Get OAuth authorization URL for provider with PKCE support."""
        if provider not in self.oauth._clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth provider '{provider}' not configured",
            )

        client = self.oauth._clients[provider]

        # Generate CSRF token and encode state with provider info
        csrf_token = secrets.token_urlsafe(32)
        encoded_state = self._encode_state(provider, redirect_uri, csrf_token)

        # Generate PKCE code verifier and store in session
        code_verifier = generate_token(48)
        request.session["oauth_code_verifier"] = code_verifier

        # Store CSRF token in session for validation
        request.session["oauth_csrf_token"] = csrf_token

        # Get authorization URL with encoded state and PKCE code verifier
        authorization_url = await client.create_authorization_url(
            redirect_uri, state=encoded_state, code_verifier=code_verifier
        )

        logger.info(
            "Generated OAuth authorization URL with PKCE",
            provider=provider,
            has_state=bool(encoded_state),
            has_csrf_token=bool(csrf_token),
            has_code_verifier=bool(code_verifier),
        )

        return str(authorization_url["url"])

    async def handle_callback(self, request: Request) -> OAuthUserInfo:
        """Handle OAuth callback and extract user information."""
        # Get state and code from query parameters
        state = request.query_params.get("state")
        code = request.query_params.get("code")

        if not state or not code:
            logger.warning(
                "Missing OAuth callback parameters", state=bool(state), code=bool(code)
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing OAuth callback parameters",
            )

        # Decode state to get provider info
        try:
            state_data = self._decode_state(state)
            provider = state_data["provider"]
        except HTTPException:
            # Re-raise HTTPException from _decode_state
            raise
        except Exception as e:
            logger.error(OAUTH_STATE_DECODE_ERROR, error=str(e), context="callback")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state parameter",
            ) from e

        if provider not in self.oauth._clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth provider '{provider}' not configured",
            )

        client = self.oauth._clients[provider]

        try:
            # Get code verifier from session for PKCE
            code_verifier = request.session.get("oauth_code_verifier")

            # Exchange authorization code for access token with PKCE
            if code_verifier:
                # Use code verifier for PKCE flow
                token = await client.authorize_access_token(
                    request, code_verifier=code_verifier
                )
            else:
                # Fallback for non-PKCE flow (backward compatibility)
                token = await client.authorize_access_token(request)

            # Get user information
            user_info = await self._get_user_info(client, token, provider)

            # Clean up session
            request.session.pop("oauth_csrf_token", None)
            request.session.pop("oauth_code_verifier", None)

            logger.info(
                "OAuth authentication successful with PKCE",
                provider=provider,
                user_id=user_info.id,
                email=user_info.email,
                used_pkce=bool(code_verifier),
            )

            return user_info

        except Exception as e:
            logger.error("OAuth callback failed", provider=provider, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth authentication failed",
            ) from e

    async def handle_callback_with_code(
        self, request: Request, provider: str, code: str, state: str, redirect_uri: str
    ) -> OAuthUserInfo:
        """Handle OAuth callback with authorization code and state."""
        # Decode state to get provider info and CSRF token
        try:
            state_data = self._decode_state(state)
            state_provider = state_data["provider"]
            state_redirect_uri = state_data["redirect_uri"]
            state_csrf_token = state_data["csrf_token"]
        except HTTPException:
            # Re-raise HTTPException from _decode_state
            raise
        except Exception as e:
            logger.error(OAUTH_STATE_DECODE_ERROR, error=str(e), has_state=bool(state))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state parameter",
            ) from e

        # Verify CSRF token against session
        stored_csrf_token = request.session.get("oauth_csrf_token")

        # Validate CSRF token
        logger.info(
            "OAuth callback validation",
            provider=provider,
            csrf_token_match=stored_csrf_token == state_csrf_token
            if stored_csrf_token
            else False,
        )

        # Validate CSRF token
        if not stored_csrf_token or stored_csrf_token != state_csrf_token:
            logger.warning(
                "OAuth CSRF token mismatch",
                has_stored_token=bool(stored_csrf_token),
                has_state_token=bool(state_csrf_token),
                provider=provider,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state parameter",
            )

        # Validate provider matches
        if provider != state_provider:
            logger.warning(
                "OAuth provider mismatch",
                requested_provider=provider,
                state_provider=state_provider,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth provider mismatch",
            )

        # Validate redirect URI matches the one encoded in state
        if redirect_uri != state_redirect_uri:
            logger.warning(
                OAUTH_REDIRECT_URI_MISMATCH,
                requested_redirect_uri=redirect_uri,
                state_redirect_uri=state_redirect_uri,
                provider=provider,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=OAUTH_REDIRECT_URI_MISMATCH,
            )

        if provider not in self.oauth._clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth provider '{provider}' not configured",
            )

        client = self.oauth._clients[provider]

        try:
            # Get token endpoint from client configuration
            # For Authlib clients, the token endpoint is stored in the client metadata
            token_endpoint = getattr(client, "access_token_url", None)
            if not token_endpoint:
                # Try to get from server metadata
                token_endpoint = client.server_metadata.get("token_endpoint")
            if not token_endpoint:
                # Final fallback - this should not happen with proper configuration
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"No token endpoint configured for provider '{provider}'",
                )

            logger.info(
                "Exchanging authorization code for token",
                provider=provider,
                token_endpoint=token_endpoint,
                code_length=len(code),
                redirect_uri=redirect_uri,
            )

            # Get code verifier from session for PKCE
            code_verifier = request.session.get("oauth_code_verifier")

            # Exchange authorization code for access token using direct HTTP request
            # This avoids the state validation issues with Authlib's authorize_access_token
            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
            }

            # Add code verifier for PKCE if available
            if code_verifier:
                token_data["code_verifier"] = code_verifier

            async with httpx.AsyncClient() as http_client:
                token_response = await http_client.post(
                    token_endpoint,
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if token_response.status_code != 200:
                    logger.error(
                        "Token exchange failed",
                        provider=provider,
                        status_code=token_response.status_code,
                        response_text=token_response.text[:200],
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Failed to exchange authorization code for token",
                    )

                token = token_response.json()

            logger.info(
                "Token exchange successful",
                provider=provider,
                token_type=token.get("token_type"),
                has_access_token=bool(token.get("access_token")),
                has_id_token=bool(token.get("id_token")),
            )

            # Get user information
            user_info = await self._get_user_info(client, token, provider)

            # Clean up session
            request.session.pop("oauth_csrf_token", None)
            request.session.pop("oauth_code_verifier", None)

            logger.info(
                "OAuth code exchange successful with PKCE",
                provider=provider,
                user_id=user_info.id,
                email=user_info.email,
                used_pkce=bool(code_verifier),
            )

            return user_info

        except Exception as e:
            logger.error("OAuth code exchange failed", provider=provider, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth authentication failed",
            ) from e

    async def _get_user_info(
        self, client: Any, token: dict[str, Any], provider: str
    ) -> OAuthUserInfo:
        """Extract user information from OAuth token."""
        if provider == "github":
            return await self._get_github_user_info(client, token)
        elif provider == "microsoft":
            return await self._get_microsoft_user_info(client, token)
        elif provider == "discord":
            return await self._get_discord_user_info(client, token)
        else:
            return await self._get_generic_user_info(client, token, provider)

    async def _get_github_user_info(
        self, client: Any, token: dict[str, Any]
    ) -> OAuthUserInfo:
        """Get user info from GitHub."""
        resp = await client.get("https://api.github.com/user", token=token)
        user_data = resp.json()

        # Get primary email if not public
        email = user_data.get("email")
        if not email:
            email_resp = await client.get(
                "https://api.github.com/user/emails", token=token
            )
            emails = email_resp.json()
            primary_email = next((e for e in emails if e["primary"]), None)
            email = primary_email["email"] if primary_email else ""

        return OAuthUserInfo(
            id=str(user_data["id"]),
            email=email,
            name=user_data.get("name") or user_data.get("login"),
            avatar_url=user_data.get("avatar_url"),
            provider="github",
            provider_data=user_data,
        )

    async def _get_microsoft_user_info(
        self, client: Any, token: dict[str, Any]
    ) -> OAuthUserInfo:
        """Get user info from Microsoft."""
        resp = await client.get("https://graph.microsoft.com/v1.0/me", token=token)
        user_data = resp.json()

        return OAuthUserInfo(
            id=user_data["id"],
            email=user_data.get("mail") or user_data.get("userPrincipalName"),
            name=user_data.get("displayName"),
            avatar_url=None,  # Microsoft Graph requires separate call for photo
            provider="microsoft",
            provider_data=user_data,
        )

    async def _get_discord_user_info(
        self, client: Any, token: dict[str, Any]
    ) -> OAuthUserInfo:
        """Get user info from Discord."""
        resp = await client.get("https://discord.com/api/users/@me", token=token)
        user_data = resp.json()

        avatar_url = None
        if user_data.get("avatar"):
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_data['id']}/{user_data['avatar']}.png"

        return OAuthUserInfo(
            id=user_data["id"],
            email=user_data.get("email"),
            name=user_data.get("username"),
            avatar_url=avatar_url,
            provider="discord",
            provider_data=user_data,
        )

    async def _get_generic_user_info(
        self, client: Any, token: dict[str, Any], provider: str
    ) -> OAuthUserInfo:
        """Get user info from generic OAuth provider."""
        if not self.settings.oauth_userinfo_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User info URL not configured for generic provider",
            )

        resp = await client.get(self.settings.oauth_userinfo_url, token=token)
        user_data = resp.json()

        return OAuthUserInfo(
            id=str(user_data.get("sub") or user_data.get("id")),
            email=user_data.get("email"),
            name=user_data.get("name") or user_data.get("preferred_username"),
            avatar_url=user_data.get("picture"),
            provider=provider,
            provider_data=user_data,
        )

    async def get_google_authorization_url(
        self, request: Request, redirect_uri: str
    ) -> str:
        """
        Get Google OAuth authorization URL with contacts scope for integration.

        Args:
            request: FastAPI request object
            redirect_uri: OAuth callback URI

        Returns:
            Authorization URL for Google integration

        Raises:
            HTTPException: If Google provider not configured
        """
        if "google" not in self.oauth._clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google OAuth provider not configured",
            )

        client = self.oauth._clients["google"]

        # Generate CSRF token and encode state with provider info and integration flow type
        csrf_token = secrets.token_urlsafe(32)
        encoded_state = self._encode_state(
            "google", redirect_uri, csrf_token, "integration"
        )

        # Generate PKCE code verifier and store in session
        code_verifier = generate_token(48)
        request.session["oauth_code_verifier"] = code_verifier

        # Store CSRF token in session for validation
        request.session["oauth_csrf_token"] = csrf_token

        # Get authorization URL with contacts scope
        authorization_url = await client.create_authorization_url(
            redirect_uri,
            state=encoded_state,
            code_verifier=code_verifier,
            scope=GOOGLE_SCOPE,
            access_type="offline",  # Request refresh token
            prompt="consent",  # Force consent to get refresh token
        )

        logger.info(
            "Generated Google OAuth authorization URL",
            redirect_uri=redirect_uri,
            has_state=bool(encoded_state),
            has_csrf_token=bool(csrf_token),
        )

        return str(authorization_url["url"])

    async def handle_google_callback(
        self, request: Request, code: str, state: str, redirect_uri: str
    ) -> dict[str, Any]:
        """
        Handle Google OAuth callback for contacts integration.

        Args:
            request: FastAPI request object
            code: Authorization code from Google
            state: State parameter for CSRF protection
            redirect_uri: OAuth callback URI

        Returns:
            Token data including access_token, refresh_token, expires_in

        Raises:
            HTTPException: If callback validation fails
        """
        # Decode and validate state
        try:
            decoded_state = self._decode_state(state)
            provider = decoded_state["provider"]
            csrf_token = decoded_state["csrf_token"]
            state_redirect_uri = decoded_state["redirect_uri"]
        except Exception as e:
            logger.warning(OAUTH_STATE_DECODE_ERROR, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter",
            ) from e

        # Validate CSRF token
        session_csrf_token = request.session.get("oauth_csrf_token")
        if not session_csrf_token or session_csrf_token != csrf_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid CSRF token",
            )

        # Validate provider
        if provider != "google":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid provider in state",
            )

        # Validate redirect URI matches the one encoded in state
        if redirect_uri != state_redirect_uri:
            logger.warning(
                OAUTH_REDIRECT_URI_MISMATCH,
                requested_redirect_uri=redirect_uri,
                state_redirect_uri=state_redirect_uri,
                provider=provider,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=OAUTH_REDIRECT_URI_MISMATCH,
            )

        # Get code verifier from session
        code_verifier = request.session.get("oauth_code_verifier")
        if not code_verifier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing code verifier",
            )

        try:
            # Exchange authorization code for tokens using direct HTTP request
            # This avoids the state validation issues with Authlib's authorize_access_token
            client = self.oauth._clients["google"]
            token_endpoint = "https://oauth2.googleapis.com/token"

            logger.info(
                "Exchanging Google authorization code for tokens",
                token_endpoint=token_endpoint,
                code_length=len(code),
                redirect_uri=redirect_uri,
            )

            # Prepare token request data
            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "code_verifier": code_verifier,
            }

            # Exchange code for tokens
            async with httpx.AsyncClient() as http_client:
                token_response = await http_client.post(
                    token_endpoint,
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if token_response.status_code != 200:
                    logger.error(
                        "Google token exchange failed",
                        status_code=token_response.status_code,
                        response_text=token_response.text[:200],
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Failed to exchange authorization code for token",
                    )

                token = token_response.json()

            # Clean up session
            request.session.pop("oauth_csrf_token", None)
            request.session.pop("oauth_code_verifier", None)

            logger.info(
                "Successfully exchanged Google authorization code for tokens",
                has_access_token=bool(token.get("access_token")),
                has_refresh_token=bool(token.get("refresh_token")),
                expires_in=token.get("expires_in"),
            )

            # Return token data as dict
            return dict(token)

        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
        except Exception as e:
            logger.error("Failed to exchange Google authorization code", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to exchange authorization code: {str(e)}",
            ) from e

    async def get_google_user_email(self, access_token: str) -> str:
        """
        Get Google user email from access token.

        Args:
            access_token: Google OAuth access token

        Returns:
            User's email address

        Raises:
            HTTPException: If unable to fetch user info
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    logger.error(
                        "Failed to fetch Google user info",
                        status_code=response.status_code,
                        response_text=response.text[:200],
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Failed to fetch Google user information",
                    )

                user_info = response.json()
                email: str | None = user_info.get("email")

                if not email:
                    logger.error(
                        "No email in Google user info response",
                        user_info_keys=list(user_info.keys()),
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No email found in Google user information",
                    )

                logger.info(
                    "Successfully fetched Google user email",
                    email=email,
                )

                return email

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "Failed to get Google user email",
                error=str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get Google user information",
            ) from e

    async def disconnect_google(
        self, user_id: str, connection: AsyncConnection
    ) -> bool:
        """
        Disconnect Google integration for a user.

        This removes the stored OAuth tokens from the database. Note that this
        does not revoke the tokens with Google - the tokens will remain valid
        until they expire, but the user will need to re-authenticate to use
        the integration again.

        Args:
            user_id: User ID to disconnect integration for
            connection: Database connection for deleting tokens

        Returns:
            True if tokens were deleted, False if no tokens existed
        """
        from sqlalchemy import text

        try:
            # Delete user's Google auth tokens
            stmt = text("""
                DELETE FROM user_google_auth
                WHERE user_id = :user_id
            """)

            result = await connection.execute(stmt, {"user_id": user_id})
            deleted_count = result.rowcount

            if deleted_count > 0:
                logger.info(
                    "Google OAuth tokens deleted",
                    user_id=user_id,
                    deleted_count=deleted_count,
                )
                return True
            else:
                logger.info(
                    "No Google OAuth tokens found to delete",
                    user_id=user_id,
                )
                return False

        except Exception as e:
            logger.error(
                "Failed to disconnect Google",
                user_id=user_id,
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to disconnect Google integration",
            ) from e

    async def is_google_connected(
        self, user_id: str, connection: AsyncConnection
    ) -> bool:
        """
        Check if Google integration is connected for a user.

        Args:
            user_id: User ID to check connection status for
            connection: Database connection for querying token storage

        Returns:
            True if user has Google tokens stored, False otherwise
        """
        try:
            google_account_emails = await self._get_google_account_emails(
                user_id, connection
            )
            has_tokens = len(google_account_emails) > 0

            logger.debug(
                "Google connection check",
                user_id=user_id,
                has_tokens=has_tokens,
            )

            return has_tokens

        except Exception as e:
            logger.error(
                "Failed to check Google connection",
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            # Return False on error to avoid breaking the UI
            return False

    async def get_connected_google_account_email(
        self, user_id: str, connection: AsyncConnection
    ) -> str:
        """Return the single connected Google account email for a user."""
        google_account_emails = await self._get_google_account_emails(
            user_id, connection
        )

        if not google_account_emails:
            raise ValueError(f"No Google connection found for user {user_id}")

        if len(google_account_emails) > 1:
            raise ValueError(f"Multiple Google connections found for user {user_id}")

        return google_account_emails[0]

    async def _get_google_account_emails(
        self, user_id: str, connection: AsyncConnection
    ) -> list[str]:
        """Return all connected Google account emails for a user."""
        stmt = text("""
            SELECT google_account_email
            FROM user_google_auth
            WHERE user_id = :user_id
            ORDER BY google_account_email
        """)

        result = await connection.execute(stmt, {"user_id": user_id})
        return list(result.scalars().all())

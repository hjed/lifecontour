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
from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, status

from app.infrastructure.auth.models import OAuthUserInfo
from app.infrastructure.config import Settings

logger = structlog.get_logger()


class OAuthService:
    """OAuth service for handling multiple OAuth providers."""

    def __init__(self, settings: Settings) -> None:
        """Initialize OAuth service with settings."""
        self.settings = settings
        self.oauth = OAuth()
        self._configure_providers()

    def _encode_state(self, provider: str, redirect_uri: str, csrf_token: str) -> str:
        """Encode OAuth state with provider info and CSRF token."""
        state_data = {
            "provider": provider,
            "redirect_uri": redirect_uri,
            "csrf_token": csrf_token,
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
                "Failed to decode OAuth state",
                error=str(e),
                state=encoded_state[:20] + "...",
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
                )
                logger.info("Configured GitHub OAuth provider")
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
                    client_kwargs={"scope": "openid email profile"},
                )
                logger.info("Configured Microsoft OAuth provider")
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
                )
                logger.info("Configured Discord OAuth provider")
            except Exception as e:
                logger.warning(
                    "Failed to configure Discord OAuth provider", error=str(e)
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
                client_kwargs = {"scope": "openid email profile"}
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
                )
                logger.info(
                    "Configured generic OAuth provider",
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
        """Get OAuth authorization URL for provider."""
        if provider not in self.oauth._clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth provider '{provider}' not configured",
            )

        client = self.oauth._clients[provider]

        # Generate CSRF token and encode state with provider info
        csrf_token = secrets.token_urlsafe(32)
        encoded_state = self._encode_state(provider, redirect_uri, csrf_token)

        # Store CSRF token in session for validation (only the CSRF token, not all state)
        request.session["oauth_csrf_token"] = csrf_token

        # Get authorization URL with encoded state
        authorization_url = await client.create_authorization_url(
            redirect_uri, state=encoded_state
        )

        logger.info(
            "Generated OAuth authorization URL",
            provider=provider,
            state_preview=encoded_state[:20] + "...",
            csrf_token=csrf_token[:10] + "...",
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
            logger.error("Failed to decode OAuth state in callback", error=str(e))
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
            # Exchange authorization code for access token
            token = await client.authorize_access_token(request)

            # Get user information
            user_info = await self._get_user_info(client, token, provider)

            # Clean up session (only need to remove CSRF token now)
            request.session.pop("oauth_csrf_token", None)

            logger.info(
                "OAuth authentication successful",
                provider=provider,
                user_id=user_info.id,
                email=user_info.email,
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
            logger.error(
                "Failed to decode OAuth state", error=str(e), state=state[:20] + "..."
            )
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
                stored_csrf_token=stored_csrf_token[:10] + "..."
                if stored_csrf_token
                else None,
                state_csrf_token=state_csrf_token[:10] + "..."
                if state_csrf_token
                else None,
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
                "OAuth redirect URI mismatch",
                requested_redirect_uri=redirect_uri,
                state_redirect_uri=state_redirect_uri,
                provider=provider,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth redirect URI mismatch",
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

            # Exchange authorization code for access token using direct HTTP request
            # This avoids the state validation issues with Authlib's authorize_access_token
            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
            }

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

            # Clean up session (only need to remove CSRF token now)
            request.session.pop("oauth_csrf_token", None)

            logger.info(
                "OAuth code exchange successful",
                provider=provider,
                user_id=user_info.id,
                email=user_info.email,
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

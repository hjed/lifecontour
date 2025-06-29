"""
OAuth service for handling OAuth2 authentication with multiple providers.

Provides OAuth2 authentication using Authlib with support for GitHub, Microsoft,
Discord, and generic OAuth2 providers.
"""

import secrets
from typing import Any

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
                self.oauth.register(
                    name=self.settings.oauth_provider_name,
                    client_id=self.settings.oauth_client_id,
                    client_secret=self.settings.oauth_client_secret,
                    authorize_url=self.settings.oauth_authorization_url,
                    access_token_url=self.settings.oauth_token_url,
                    client_kwargs={"scope": "openid email profile"},
                )
                logger.info(
                    "Configured generic OAuth provider",
                    provider_name=self.settings.oauth_provider_name,
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

        # Generate and store state for CSRF protection
        state = secrets.token_urlsafe(32)
        request.session["oauth_state"] = state
        request.session["oauth_provider"] = provider
        request.session["oauth_redirect_uri"] = redirect_uri

        # Get authorization URL
        authorization_url = await client.create_authorization_url(
            redirect_uri, state=state
        )

        logger.info(
            "Generated OAuth authorization URL",
            provider=provider,
            state=state,
        )

        return str(authorization_url["url"])

    async def handle_callback(self, request: Request) -> OAuthUserInfo:
        """Handle OAuth callback and extract user information."""
        # Verify state parameter for CSRF protection
        state = request.query_params.get("state")
        stored_state = request.session.get("oauth_state")

        if not state or not stored_state or state != stored_state:
            logger.warning(
                "OAuth state mismatch", state=state, stored_state=stored_state
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state parameter",
            )

        provider = request.session.get("oauth_provider")
        redirect_uri = request.session.get("oauth_redirect_uri")

        if not provider or not redirect_uri:
            logger.warning("Missing OAuth session data", provider=provider)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth session",
            )

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

            # Clean up session
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_provider", None)
            request.session.pop("oauth_redirect_uri", None)

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

    async def exchange_code_for_user(
        self, provider: str, code: str, redirect_uri: str
    ) -> OAuthUserInfo:
        """Exchange authorization code for user information."""
        if provider not in self.oauth._clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth provider '{provider}' not configured",
            )

        client = self.oauth._clients[provider]

        try:
            # Create a mock request with the authorization code
            from starlette.requests import Request

            # Create a mock request with the code parameter
            mock_request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "url": f"{redirect_uri}?code={code}",
                    "query_string": f"code={code}".encode(),
                }
            )

            # Exchange authorization code for access token
            token = await client.authorize_access_token(mock_request)

            # Get user information
            user_info = await self._get_user_info(client, token, provider)

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

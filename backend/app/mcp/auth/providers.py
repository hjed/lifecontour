"""
MCP OAuth provider factory.

Creates the appropriate FastMCP auth provider based on application settings.
Uses FastMCP's built-in OAuth proxy providers (GitHubProvider, AzureProvider,
DiscordProvider) which handle .well-known discovery, authorization flows,
token issuance, and consent screens.
"""

from __future__ import annotations

import structlog
from fastmcp.server.auth.auth import AuthProvider
from fastmcp.server.auth.oauth_proxy.proxy import OAuthProxy
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.auth.providers.discord import DiscordProvider
from fastmcp.server.auth.providers.github import GitHubProvider

from app.infrastructure.config import Settings

logger = structlog.get_logger()


def create_mcp_auth_provider(settings: Settings) -> AuthProvider | None:
    """Create the MCP auth provider based on configured OAuth settings.

    Returns the first available provider in priority order:
    Generic OAuth > GitHub > Microsoft > Discord.

    Returns None if auth is disabled or no providers are configured.

    Args:
        settings: Application settings containing OAuth credentials

    Returns:
        Configured AuthProvider or None
    """
    if settings.disable_auth:
        logger.info("MCP: Auth disabled, no provider created")
        return None

    base_url = _get_mcp_base_url(settings)
    if not base_url:
        if _has_any_provider_configured(settings):
            raise RuntimeError(
                "WEBHOOK_BASE_URL must be configured to use MCP OAuth auth. "
                "Set WEBHOOK_BASE_URL or disable auth explicitly via "
                "DISABLE_AUTH=true."
            )
        logger.info("MCP: No OAuth providers configured, MCP auth unavailable")
        return None

    # Priority 1: Generic OAuth provider
    if (
        settings.oauth_client_id
        and settings.oauth_client_secret
        and settings.oauth_authorization_url
        and settings.oauth_token_url
    ):
        logger.info(
            "MCP: Configuring generic OAuth provider",
            provider_name=settings.oauth_provider_name or "generic",
        )
        # DebugTokenVerifier is the only TokenVerifier implementation in
        # FastMCP and is required by OAuthProxy. Named providers (GitHub,
        # Azure, Discord) have their own built-in verification. For
        # generic OAuth, tokens are validated via the upstream provider's
        # authorization flow; DebugTokenVerifier handles the local JWT
        # that OAuthProxy issues after a successful upstream exchange.
        logger.warning(
            "MCP: Generic OAuth uses DebugTokenVerifier for local token "
            "validation. Consider using a named provider (GitHub, Azure, "
            "Discord) for stronger token verification."
        )
        return OAuthProxy(
            upstream_authorization_endpoint=settings.oauth_authorization_url,
            upstream_token_endpoint=settings.oauth_token_url,
            upstream_client_id=settings.oauth_client_id,
            upstream_client_secret=settings.oauth_client_secret,
            token_verifier=DebugTokenVerifier(),
            base_url=base_url,
            issuer_url=_get_mcp_issuer_url(settings),
            extra_authorize_params={"scope": settings.oauth_scopes}
            if settings.oauth_scopes
            else None,
        )

    # Priority 2: GitHub
    if settings.github_client_id and settings.github_client_secret:
        logger.info("MCP: Configuring GitHub OAuth provider")
        return GitHubProvider(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            base_url=base_url,
            issuer_url=_get_mcp_issuer_url(settings),
        )

    # Priority 3: Microsoft / Azure AD
    if settings.microsoft_client_id and settings.microsoft_client_secret:
        logger.info(
            "MCP: Configuring Microsoft OAuth provider",
            tenant_id=settings.microsoft_tenant_id,
        )
        return AzureProvider(
            client_id=settings.microsoft_client_id,
            client_secret=settings.microsoft_client_secret,
            tenant_id=settings.microsoft_tenant_id,
            base_url=base_url,
            issuer_url=_get_mcp_issuer_url(settings),
            required_scopes=["openid", "profile", "email"],
        )

    # Priority 4: Discord
    if settings.discord_client_id and settings.discord_client_secret:
        logger.info("MCP: Configuring Discord OAuth provider")
        return DiscordProvider(
            client_id=settings.discord_client_id,
            client_secret=settings.discord_client_secret,
            base_url=base_url,
            issuer_url=_get_mcp_issuer_url(settings),
        )

    logger.info("MCP: No OAuth providers configured, MCP auth unavailable")
    return None


def _get_mcp_base_url(settings: Settings) -> str:
    """Compute the MCP base URL from settings.

    The base_url includes the mount path prefix so OAuth endpoints
    (authorize, token, callback) are under the mount path.

    Returns empty string if webhook_base_url is not configured.
    """
    if not settings.webhook_base_url:
        return ""
    base = settings.webhook_base_url.rstrip("/")
    mount = settings.mcp_mount_path.rstrip("/")
    return f"{base}{mount}"


def _get_mcp_issuer_url(settings: Settings) -> str:
    """Compute the MCP issuer URL from settings.

    The issuer_url is the root URL WITHOUT the mount path prefix.
    Per RFC 8414, path-aware discovery uses the issuer to construct
    .well-known paths. Setting this to the root URL ensures discovery
    works with path-aware clients.
    """
    if not settings.webhook_base_url:
        return ""
    return settings.webhook_base_url.rstrip("/")


def _has_any_provider_configured(settings: Settings) -> bool:
    """Check if any OAuth provider credentials are configured."""
    return bool(
        (settings.oauth_client_id and settings.oauth_client_secret)
        or (settings.github_client_id and settings.github_client_secret)
        or (settings.microsoft_client_id and settings.microsoft_client_secret)
        or (settings.discord_client_id and settings.discord_client_secret)
    )

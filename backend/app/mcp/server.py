"""
FastMCP server setup and configuration.

Creates and configures the FastMCP server with domain-specific tools,
OAuth authentication via FastMCP providers, and AI-optimized instructions.
"""

from __future__ import annotations

import structlog
from dishka import AsyncContainer
from dishka.integrations.starlette import setup_dishka
from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider

from app.infrastructure.config import Settings
from app.mcp.domains.contacts.tools import register_contact_tools
from app.mcp.domains.journals.tools import register_journal_tools

logger = structlog.get_logger()


def _create_mcp_auth_provider(
    settings: Settings,
) -> AuthProvider | None:
    """Create the appropriate FastMCP OAuth auth provider based on settings.

    Selects the first configured OAuth provider from the following priority:
    generic OAuth → GitHub → Google → Discord.

    Args:
        settings: Application settings containing OAuth credentials

    Returns:
        A FastMCP auth provider, or None if auth is disabled or
        no providers are configured.
    """
    if settings.disable_auth:
        logger.warning("MCP: Authentication disabled — no OAuth provider configured")
        return None

    base_url = (
        f"{settings.mcp_base_url.rstrip('/')}/{settings.mcp_mount_path.strip('/')}"
    )

    # Generic OAuth provider (preferred)
    if (
        settings.oauth_client_id
        and settings.oauth_client_secret
        and settings.oauth_authorization_url
        and settings.oauth_token_url
        and settings.oauth_introspection_url
    ):
        from fastmcp.server.auth import OAuthProxy
        from fastmcp.server.auth.providers.introspection import (
            IntrospectionTokenVerifier,
        )

        token_verifier = IntrospectionTokenVerifier(
            introspection_url=settings.oauth_introspection_url,
            client_id=settings.oauth_client_id,
            client_secret=settings.oauth_client_secret,
        )

        logger.info(
            "MCP: Using generic OAuth provider",
            provider_name=settings.oauth_provider_name or "generic",
            base_url=base_url,
        )
        return OAuthProxy(
            upstream_authorization_endpoint=settings.oauth_authorization_url,
            upstream_token_endpoint=settings.oauth_token_url,
            upstream_client_id=settings.oauth_client_id,
            upstream_client_secret=settings.oauth_client_secret,
            token_verifier=token_verifier,
            base_url=base_url,
        )

    # GitHub provider
    if settings.github_client_id and settings.github_client_secret:
        from fastmcp.server.auth.providers.github import GitHubProvider

        logger.info("MCP: Using GitHub OAuth provider", base_url=base_url)
        return GitHubProvider(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            base_url=base_url,
        )

    # Google provider
    if settings.google_client_id and settings.google_client_secret:
        from fastmcp.server.auth.providers.google import GoogleProvider

        logger.info("MCP: Using Google OAuth provider", base_url=base_url)
        return GoogleProvider(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            base_url=base_url,
        )

    # Discord provider
    if settings.discord_client_id and settings.discord_client_secret:
        from fastmcp.server.auth.providers.discord import DiscordProvider

        logger.info("MCP: Using Discord OAuth provider", base_url=base_url)
        return DiscordProvider(
            client_id=settings.discord_client_id,
            client_secret=settings.discord_client_secret,
            base_url=base_url,
        )

    logger.error(
        "MCP: No OAuth provider configured and authentication is not disabled. "
        "MCP server will NOT be mounted. Set at least one OAuth provider "
        "(OAUTH_*, GITHUB_*, GOOGLE_*, or DISCORD_* credentials) or set "
        "DISABLE_AUTH=true for development."
    )
    return None


def create_mcp_server(settings: Settings) -> FastMCP:
    """
    Create and configure FastMCP server with all domain tools.

    Args:
        settings: Application settings for OAuth configuration

    Returns:
        Configured FastMCP server instance with registered tools
    """
    logger.info("MCP: Creating FastMCP server")

    auth = _create_mcp_auth_provider(settings)

    # Create FastMCP server with AI-optimized instructions
    mcp: FastMCP = FastMCP(
        name="Personal Management System",
        auth=auth,
        instructions="""\
        This server provides AI access to personal management data and operations.

        Available domains:
        - Contacts: Retrieve contact information, search contacts, manage relationships
        - Journals: Create, update, search, and manage journal entries with types, tags, and relationships

        All data is formatted for AI analysis and decision making. Use the tools to:
        - Get detailed contact information by ID
        - Access contact methods (email, phone) and tags
        - Create and manage journal entries with multiple types (NOTE, EVENT, MOOD_RATING, etc.)
        - Link journals to contacts and organize with tags
        - Search journals with filtering and full-text search
        - Understand relationships and context through AI-friendly summaries

        The system maintains data privacy and requires valid authentication.
        All operations are logged for audit purposes.
        """,
    )

    # Register domain-specific tools
    logger.info("MCP: Registering contact domain tools")
    register_contact_tools(mcp)

    logger.info("MCP: Registering journal domain tools")
    register_journal_tools(mcp)

    # Future domains can be registered here:
    # register_calendar_tools(mcp)
    # register_photos_tools(mcp)

    logger.info("MCP: FastMCP server created successfully")
    return mcp


def create_mcp_app(container: AsyncContainer, settings: Settings) -> object | None:
    """
    Create FastMCP ASGI app with OAuth auth and Dishka integration.

    Args:
        container: Dishka container for dependency injection
        settings: Application settings for OAuth and path configuration

    Returns:
        ASGI application ready for mounting in FastAPI, or None if MCP
        cannot be started (e.g. no auth provider configured).
    """
    logger.info("MCP: Creating FastMCP ASGI application")

    # Create MCP server with OAuth auth
    mcp = create_mcp_server(settings)

    # Create HTTP app — path="/" because the mount prefix handles routing
    app = mcp.http_app(path="/")

    # Set up Dishka integration with the Starlette app
    setup_dishka(container, app)

    logger.info(
        "MCP: ASGI application created with OAuth authentication and Dishka integration"
    )
    return app

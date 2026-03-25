"""
FastMCP server setup and configuration.

Creates and configures the FastMCP server with domain-specific tools,
OAuth authentication via FastMCP's built-in providers, and AI-optimized
instructions.
"""

import json

import structlog
from dishka import AsyncContainer
from dishka.integrations.starlette import setup_dishka
from fastmcp import FastMCP
from fastmcp.server.auth.auth import AuthProvider
from fastmcp.server.auth.middleware import RequireAuthMiddleware
from starlette.types import Send

from app.mcp.domains.contacts.tools import register_contact_tools
from app.mcp.domains.journals.tools import register_journal_tools

logger = structlog.get_logger()


async def _patched_send_auth_error(
    self: RequireAuthMiddleware,
    send: Send,
    status_code: int,
    error: str,
    description: str,
) -> None:
    """Enhanced authentication mistake responder with RFC 9728 compliant Link Header."""
    # Enhance error descriptions based on error type
    enhanced_description = description

    if error == "invalid_token" and status_code == 401:
        # This is the "Authentication required" error
        enhanced_description = (
            "Authentication failed. The provided bearer token is invalid, expired, or no longer recognized by the server. "
            "To resolve: clear authentication tokens in your MCP client and reconnect. "
            "Your client should automatically re-register and obtain new tokens."
        )

    # Build WWW-Authenticate header value
    www_auth_parts = [
        f'error="{error}"',
        f'error_description="{enhanced_description}"',
    ]
    if self.resource_metadata_url:
        www_auth_parts.append(f'resource_metadata="{self.resource_metadata_url}"')

    www_authenticate = f"Bearer {', '.join(www_auth_parts)}"

    # Send response
    body = {"error": error, "error_description": enhanced_description}
    body_bytes = json.dumps(body).encode()

    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body_bytes)).encode()),
        (b"www-authenticate", www_authenticate.encode()),
    ]

    # --- BUG FIX: ADD MISSING LINK HEADER FOR RFC 9728 COMPLIANCE ---
    if self.resource_metadata_url:
        link_val = f'<{self.resource_metadata_url}>; rel="oauth-protected-resource"'
        headers.append((b"link", link_val.encode()))

    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": headers,
        }
    )

    await send(
        {
            "type": "http.response.body",
            "body": body_bytes,
        }
    )

    # FastMCP uses structlog too so we can just use the standard logger
    logger.info(
        "MCP Auth error returned",
        error=error,
        status=status_code,
    )


# Apply the monkeypatch globally before any routes are created
RequireAuthMiddleware._send_auth_error = _patched_send_auth_error  # type: ignore[method-assign]


def create_mcp_server(auth: AuthProvider | None = None) -> FastMCP[None]:
    """
    Create and configure FastMCP server with all domain tools.

    Args:
        auth: Optional OAuth provider for MCP authentication.
              None means no authentication (dev mode / disable_auth).

    Returns:
        Configured FastMCP server instance with registered tools
    """
    logger.info("MCP: Creating FastMCP server", auth_enabled=auth is not None)

    # Create FastMCP server with AI-optimized instructions
    mcp: FastMCP[None] = FastMCP(
        name="Personal Management System",
        instructions="""
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
        auth=auth,
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


def create_mcp_app(
    container: AsyncContainer,
    auth_provider: AuthProvider | None = None,
) -> object:
    """
    Create FastMCP ASGI app with Dishka integration and optional OAuth auth.

    Args:
        container: Dishka container for dependency injection
        auth_provider: Optional OAuth provider for MCP authentication.
                       None means no authentication (dev mode).

    Returns:
        ASGI application ready for mounting in FastAPI
    """
    logger.info(
        "MCP: Creating FastMCP ASGI application",
        auth_enabled=auth_provider is not None,
    )

    # Create MCP server with auth
    mcp = create_mcp_server(auth=auth_provider)

    # Create HTTP app — FastMCP handles auth internally via the provider
    app = mcp.http_app(path="/mcp")

    # Set up Dishka integration with the Starlette app
    setup_dishka(container, app)

    logger.info(
        "MCP: ASGI application created",
        auth_type=type(auth_provider).__name__ if auth_provider else "none",
    )
    return app

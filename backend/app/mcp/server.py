"""
FastMCP server setup and configuration.

Creates and configures the FastMCP server with domain-specific tools,
authentication middleware, and AI-optimized instructions.
"""

import structlog
from dishka import AsyncContainer
from dishka.integrations.starlette import setup_dishka
from fastmcp import FastMCP
from starlette.middleware import Middleware

from app.mcp.auth.session_auth import SessionAuthMiddleware
from app.mcp.domains.contacts.tools import register_contact_tools

logger = structlog.get_logger()


def create_mcp_server() -> FastMCP[None]:
    """
    Create and configure FastMCP server with all domain tools.

    Returns:
        Configured FastMCP server instance with registered tools
    """
    logger.info("MCP: Creating FastMCP server")

    # Create FastMCP server with AI-optimized instructions
    mcp: FastMCP[None] = FastMCP(
        name="Personal Management System",
        instructions="""
        This server provides AI access to personal management data and operations.

        Available domains:
        - Contacts: Retrieve contact information, search contacts, manage relationships

        All data is formatted for AI analysis and decision making. Use the tools to:
        - Get detailed contact information by ID
        - Access contact methods (email, phone) and tags
        - Understand relationships and context through AI-friendly summaries

        The system maintains data privacy and requires valid authentication.
        All operations are logged for audit purposes.
        """,
    )

    # Register domain-specific tools
    logger.info("MCP: Registering contact domain tools")
    register_contact_tools(mcp)

    # Future domains can be registered here:
    # register_journal_tools(mcp)
    # register_calendar_tools(mcp)
    # register_photos_tools(mcp)

    logger.info("MCP: FastMCP server created successfully")
    return mcp


def create_mcp_app(container: AsyncContainer) -> object:
    """
    Create FastMCP ASGI app with authentication middleware and Dishka integration.

    Args:
        container: Dishka container for dependency injection

    Returns:
        ASGI application ready for mounting in FastAPI
    """
    logger.info("MCP: Creating FastMCP ASGI application")

    # Create MCP server
    mcp = create_mcp_server()

    # Create middleware stack
    middleware = [Middleware(SessionAuthMiddleware)]

    # Create HTTP app with session authentication middleware
    app = mcp.http_app(path="/mcp", middleware=middleware)

    # Set up Dishka integration with the Starlette app
    setup_dishka(container, app)

    logger.info(
        "MCP: ASGI application created with authentication middleware and Dishka integration"
    )
    return app

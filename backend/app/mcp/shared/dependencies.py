"""
Shared MCP dependency injection helpers.

Provides utilities for accessing domain services within MCP tools,
reusing the existing dependency injection patterns from the REST API.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services import ContactService
from app.infrastructure.database import get_async_database_engine
from app.infrastructure.search.search_service import SearchService


async def get_async_db_connection() -> AsyncGenerator[AsyncConnection, None]:
    """
    Get async database connection for MCP tools.

    Reuses the existing database connection pattern from the REST API.
    """
    engine = get_async_database_engine()
    async with engine.begin() as connection:
        yield connection


async def get_contact_service() -> ContactService:
    """
    Get ContactService instance for MCP tools.

    Creates the service with all required dependencies,
    using the shared factory from app.shared.dependencies.

    Note: This creates a new connection for each call.
    For production use, consider connection pooling.
    """
    from app.shared.dependencies import create_contact_service

    # Get database connection
    engine = get_async_database_engine()
    async with engine.begin() as connection:
        return create_contact_service(connection)


def get_search_service() -> SearchService:
    """
    Get SearchService instance for MCP tools.

    Creates the search service for MeiliSearch operations.
    """
    return SearchService()

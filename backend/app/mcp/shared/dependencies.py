"""
Shared MCP dependency injection helpers.

Provides utilities for accessing domain services within MCP tools,
reusing the existing dependency injection patterns from the REST API.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactEventPublisher,
    SqlContactFieldHistoryRepository,
    SqlContactRepository,
    SqlTagRepository,
)
from app.core.contacts.services import (
    AddressValidationService,
    ContactHistoryService,
    ContactService,
    ContactValidationService,
    TagHierarchyService,
)
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
    following the same pattern as the REST API.

    Note: This creates a new connection for each call.
    For production use, consider connection pooling.
    """
    # Get database connection
    engine = get_async_database_engine()
    async with engine.begin() as connection:
        # Create repositories
        contact_repository = SqlContactRepository(connection)
        tag_repository = SqlTagRepository(connection)
        history_repository = SqlContactFieldHistoryRepository(connection)
        event_publisher = SqlContactEventPublisher(connection)

        # Create validation services
        contact_validation_service = ContactValidationService(contact_repository)
        address_validation_service = AddressValidationService()

        # Create history service
        history_service = ContactHistoryService(history_repository)

        # Create tag hierarchy service
        tag_hierarchy_service = TagHierarchyService(tag_repository)

        # Create and return contact service
        return ContactService(
            contact_repo=contact_repository,
            tag_repo=tag_repository,
            history_repo=history_repository,
            event_publisher=event_publisher,
            contact_validation_service=contact_validation_service,
            address_validation_service=address_validation_service,
            history_service=history_service,
            tag_hierarchy_service=tag_hierarchy_service,
        )


def get_search_service() -> SearchService:
    """
    Get SearchService instance for MCP tools.

    Creates the search service for MeiliSearch operations.
    """
    return SearchService()

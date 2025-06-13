"""
Shared dependency injection for the application.

This module provides common dependency factories that can be used
across different layers (API, MCP, CLI, etc.) to ensure consistent
service creation and configuration.
"""

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


def create_contact_service(connection: AsyncConnection) -> ContactService:
    """
    Create ContactService instance with provided database connection.

    This is a shared factory function used across all application layers
    (API, MCP, CLI, etc.) to ensure consistent service creation patterns.

    Args:
        connection: Database connection to use for repositories

    Returns:
        Configured ContactService instance with all dependencies
    """
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


# Add other shared service factories here as needed
# def create_search_service(connection: AsyncConnection) -> SearchService:
#     """Create SearchService with dependencies."""
#     pass

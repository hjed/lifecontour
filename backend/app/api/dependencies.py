"""
API dependencies for dependency injection.

Provides common dependencies used across API endpoints including
database sessions, services, and authentication.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactEventPublisher,
    SqlContactFieldHistoryRepository,
    SqlContactRepository,
    SqlTagRepository,
)
from app.core.contacts.services.contact_service import ContactService
from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.search.search_service import SearchService


async def get_async_db_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Get async database connection for API endpoints."""
    engine = get_async_database_engine()
    async with engine.begin() as conn:
        yield conn


async def get_outbox_event_publisher(
    conn: Annotated[AsyncConnection, Depends(get_async_db_connection)],
) -> OutboxEventPublisher:
    """Get outbox event publisher for publishing domain events."""
    return OutboxEventPublisher(conn)


def get_search_service() -> SearchService:
    """Get search service for search operations."""
    return SearchService()


async def get_contact_service(
    conn: Annotated[AsyncConnection, Depends(get_async_db_connection)],
) -> ContactService:
    """Get contact service with all dependencies."""
    # Create repositories with the database connection
    contact_repo = SqlContactRepository(conn)
    tag_repo = SqlTagRepository(conn)
    history_repo = SqlContactFieldHistoryRepository(conn)
    event_publisher = SqlContactEventPublisher(conn)

    # Create and return the service
    return ContactService(
        contact_repo=contact_repo,
        tag_repo=tag_repo,
        history_repo=history_repo,
        event_publisher=event_publisher,
    )


# Type aliases for dependency injection
AsyncDbConnection = Annotated[AsyncConnection, Depends(get_async_db_connection)]
OutboxPublisher = Annotated[OutboxEventPublisher, Depends(get_outbox_event_publisher)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
ContactServiceDep = Annotated[ContactService, Depends(get_contact_service)]

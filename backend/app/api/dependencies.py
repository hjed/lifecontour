"""
API dependencies for dependency injection.

Provides common dependencies used across API endpoints including
database sessions, services, and authentication.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.contacts.adapters.sql import SqlTagRepository
from app.core.contacts.services import ContactService
from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.search.search_service import SearchService


async def get_async_db_connection(
    engine: Annotated[AsyncEngine, Depends(get_async_database_engine)],
) -> AsyncGenerator[AsyncConnection, None]:
    """Get async database connection for API endpoints."""
    async with engine.begin() as conn:
        yield conn


# Type aliases for dependency injection
AsyncConnectionDep = Annotated[AsyncConnection, Depends(get_async_db_connection)]


def get_search_service() -> SearchService:
    """Create SearchService instance."""
    return SearchService()


SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]


def get_contact_service(
    connection: AsyncConnection = Depends(get_async_db_connection),
) -> ContactService:
    """Create ContactService with all dependencies using shared factory."""
    from app.shared.dependencies import create_contact_service

    return create_contact_service(connection)


def get_tag_repository(
    connection: AsyncConnection = Depends(get_async_db_connection),
) -> SqlTagRepository:
    """Create TagRepository."""
    return SqlTagRepository(connection)


ContactServiceDep = Annotated[ContactService, Depends(get_contact_service)]
TagRepositoryDep = Annotated[SqlTagRepository, Depends(get_tag_repository)]


async def get_outbox_event_publisher(
    conn: Annotated[AsyncConnection, Depends(get_async_db_connection)],
) -> OutboxEventPublisher:
    """Get outbox event publisher for publishing domain events."""
    return OutboxEventPublisher(conn)


# Type aliases for dependency injection
AsyncDbConnection = Annotated[AsyncConnection, Depends(get_async_db_connection)]
OutboxPublisher = Annotated[OutboxEventPublisher, Depends(get_outbox_event_publisher)]

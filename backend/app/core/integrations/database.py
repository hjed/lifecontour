"""
Database connection patterns for integration workers.

Provides session-per-task database connection patterns and utilities
for integration workers to ensure proper transaction isolation.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.infrastructure.config import Settings

logger = logging.getLogger(__name__)


class IntegrationDatabaseManager:
    """
    Database manager for integration workers.

    Provides session-per-task pattern with proper transaction isolation
    and connection management for background integration tasks.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """
        Initialize the database manager.

        Args:
            settings: Application settings (will load from env if None)
        """
        if settings is None:
            settings = Settings()

        self.settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def _create_engine(self) -> None:
        """Create async database engine with worker-optimized settings."""
        if self._engine is not None:
            return

        # Use NullPool for workers to avoid connection sharing issues
        self._engine = create_async_engine(
            self.settings.database_url,
            poolclass=NullPool,  # No connection pooling for workers
            echo=self.settings.debug,  # Log SQL in debug mode
            future=True,
        )

        # Create session factory
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,  # Keep objects accessible after commit
        )

        logger.info("Integration database engine created")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session for a single task.

        This implements the session-per-task pattern where each background
        task gets its own isolated database session.

        Yields:
            AsyncSession: Database session for the task

        Example:
            async def my_integration_task(ctx):
                db_manager = IntegrationDatabaseManager()
                async with db_manager.get_session() as session:
                    # Perform database operations
                    result = await session.execute(select(Contact))
                    await session.commit()
        """
        if self._session_factory is None:
            self._create_engine()

        if self._session_factory is None:
            raise RuntimeError("Database session factory is not initialized")
        session = self._session_factory()
        try:
            logger.debug("Created new database session for integration task")
            yield session
        except Exception as e:
            logger.error(f"Database error in integration task: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()
            logger.debug("Closed database session for integration task")

    async def close(self) -> None:
        """Close the database engine and clean up resources."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Integration database engine closed")


# Global database manager instance for workers
_db_manager: IntegrationDatabaseManager | None = None


def get_database_manager(
    settings: Settings | None = None,
) -> IntegrationDatabaseManager:
    """
    Get the global database manager instance for integration workers.

    Args:
        settings: Application settings (will load from env if None)

    Returns:
        IntegrationDatabaseManager: Database manager instance
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = IntegrationDatabaseManager(settings)
    return _db_manager


@asynccontextmanager
async def get_integration_session(
    settings: Settings | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Convenience function to get a database session for integration tasks.

    Args:
        settings: Application settings (will load from env if None)

    Yields:
        AsyncSession: Database session for the task

    Example:
        async def sync_contact_task(ctx, external_id: str):
            async with get_integration_session() as session:
                # Query existing sync metadata
                result = await session.execute(
                    select(SyncMetadata).where(
                        SyncMetadata.external_id == external_id
                    )
                )
                sync_metadata = result.scalar_one_or_none()

                # Perform sync operations...
                await session.commit()
    """
    db_manager = get_database_manager(settings)
    async with db_manager.get_session() as session:
        yield session


async def cleanup_database_manager() -> None:
    """Clean up the global database manager instance."""
    global _db_manager
    if _db_manager is not None:
        await _db_manager.close()
        _db_manager = None


# ARQ context helpers for database sessions
async def setup_database_context(ctx: dict[str, Any]) -> None:
    """
    Set up database context for ARQ worker.

    This should be called during worker startup to initialize
    the database manager.

    Args:
        ctx: ARQ context dictionary
    """
    db_manager = get_database_manager()
    ctx["db_manager"] = db_manager
    logger.info("Database context set up for integration worker")


async def cleanup_database_context(ctx: dict[str, Any]) -> None:
    """
    Clean up database context for ARQ worker.

    This should be called during worker shutdown to clean up
    database resources.

    Args:
        ctx: ARQ context dictionary
    """
    db_manager = ctx.get("db_manager")
    if db_manager:
        await db_manager.close()
    await cleanup_database_manager()
    logger.info("Database context cleaned up for integration worker")


@asynccontextmanager
async def get_task_session(ctx: dict[str, Any]) -> AsyncGenerator[AsyncSession, None]:
    """
    Get a database session from ARQ task context.

    Args:
        ctx: ARQ context dictionary

    Yields:
        AsyncSession: Database session for the task

    Example:
        async def my_integration_task(ctx, external_id: str):
            async with get_task_session(ctx) as session:
                # Perform database operations
                pass
    """
    db_manager = ctx.get("db_manager")
    if db_manager is None:
        # Fallback to creating a new manager
        db_manager = get_database_manager()

    async with db_manager.get_session() as session:
        yield session

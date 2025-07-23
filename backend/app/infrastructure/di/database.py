"""
Database providers for Dishka dependency injection.

Provides database connections and related infrastructure with proper lifecycle management.
"""

from collections.abc import AsyncIterable, Iterable

from dishka import Provider, Scope, provide
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.orm import Session

from app.infrastructure.config import Settings
from app.infrastructure.database import get_async_database_engine, get_database_engine


class DatabaseProvider(Provider):
    """Provider for database-related dependencies."""

    def __init__(self, settings: Settings | None = None):
        """Initialize provider with optional settings."""
        super().__init__()
        self.settings = settings

    @provide(scope=Scope.APP)
    def get_engine(self) -> AsyncEngine:
        """Get the async database engine (singleton for app lifetime)."""
        if self.settings is not None:
            # Use provided settings for testing
            async_url = str(self.settings.database_url).replace(
                "postgresql://", "postgresql+asyncpg://"
            )
            return create_async_engine(
                async_url,
                echo=self.settings.database_echo,
                pool_pre_ping=True,
                pool_recycle=300,
            )
        else:
            # Use default cached engine for production
            return get_async_database_engine()

    @provide(scope=Scope.REQUEST)
    async def get_connection(
        self, engine: AsyncEngine
    ) -> AsyncIterable[AsyncConnection]:
        """
        Get async database connection for request scope.

        Uses transaction with automatic rollback/commit and proper cleanup.
        Handles transaction failures gracefully to prevent aborted transaction errors.
        """
        async with engine.begin() as conn:
            try:
                yield conn
            except Exception:
                # If an exception occurs, the transaction will be automatically rolled back
                # by the engine.begin() context manager. We just need to re-raise the exception.
                raise

    @provide(scope=Scope.APP)
    def get_sync_engine(self) -> Engine:
        """Get the sync database engine (singleton for app lifetime)."""
        if self.settings is not None:
            # Use provided settings for testing
            return create_engine(
                str(self.settings.database_url),
                echo=self.settings.database_echo,
                pool_pre_ping=True,
                pool_recycle=300,
            )
        else:
            # Use default cached engine for production
            return get_database_engine()

    @provide(scope=Scope.REQUEST)
    def get_sync_session(self, engine: Engine) -> Iterable[Session]:
        """
        Get sync database session for request scope.

        Uses session with automatic cleanup.
        """
        session = Session(engine)
        try:
            yield session
        finally:
            session.close()

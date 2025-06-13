"""
Database providers for Dishka dependency injection.

Provides database connections and related infrastructure with proper lifecycle management.
"""

from collections.abc import AsyncIterable

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.infrastructure.config import Settings
from app.infrastructure.database import get_async_database_engine


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
        """
        async with engine.begin() as conn:
            yield conn

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
        Get async database connection for request scope (commit-as-you-go).

        Uses ``engine.connect()`` rather than ``engine.begin()`` so writes can be
        committed *during* the request (before the response is sent) instead of
        only at teardown — fixing the read-after-write race in issue #945.

        Commit responsibility, in order:

        1. Migrated endpoints commit explicitly in the service layer via
           ``app.infrastructure.unit_of_work`` (``unit_of_work`` / ``@transactional``)
           — this runs mid-handler, before the response.
        2. ``CommitOnResponseMiddleware`` commits any remaining write before the
           REST response is sent (covers endpoints not yet migrated).
        3. As a final safety net, on a successful request we commit here at
           teardown. This covers paths the middleware does not (e.g. the mounted
           MCP sub-app). It is a no-op when the work was already committed above.

        On error we roll back whatever the handler left uncommitted.
        """
        async with engine.connect() as conn:
            try:
                yield conn
            except BaseException:
                if conn.in_transaction():
                    await conn.rollback()
                raise
            else:
                # Safety-net commit for any write not already committed above.
                if conn.in_transaction():
                    await conn.commit()

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

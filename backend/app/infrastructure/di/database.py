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

        Uses ``engine.connect()`` + an explicit ``conn.begin()`` rather than
        ``engine.begin()``. Both keep a transaction active for the whole request
        (so repositories that require one — e.g. those asserting
        ``conn.in_transaction()`` — keep working), but because we own the
        transaction lifecycle (rather than ``engine.begin()``'s context manager,
        which only commits at teardown), writes can be committed *during* the
        request, before the response is sent — fixing the read-after-write race
        in issue #945.

        Commit timing is owned entirely by the **service layer**: every write
        runs inside ``unit_of_work`` / ``@transactional`` (REST handlers and MCP
        tools alike), which commits before the response is sent. The provider
        never commits here:

        * On normal exit the connection is closed with any still-open
          transaction rolled back. For a write request that transaction was
          already committed by its service-layer unit of work, so only an
          autobegun read transaction (harmless, no rows changed) is discarded.
          A *read* request leaves only a read-only transaction (it may have run
          SELECTs / held locks, but changed no rows), likewise rolled back on close.
        * On an unhandled exception we roll back whatever the handler left
          uncommitted.

        (There is no longer a teardown-commit "backstop": all write paths commit
        explicitly in the service layer — see ``app.infrastructure.unit_of_work``.)
        """
        async with engine.connect() as conn:
            # Begin immediately so a transaction is active for the whole request
            # (matching the previous engine.begin() invariant). Service-layer
            # units of work commit their writes before the response; any further
            # statements re-autobegin and are rolled back when the connection
            # closes below.
            await conn.begin()
            try:
                yield conn
            except BaseException:
                if conn.in_transaction():
                    await conn.rollback()
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

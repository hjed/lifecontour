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

        Commit responsibility, in order:

        1. Migrated endpoints commit explicitly in the service layer via
           ``app.infrastructure.unit_of_work`` (``unit_of_work`` / ``@transactional``)
           — this runs mid-handler, before the response.
        2. ``CommitOnResponseMiddleware`` settles the REST request transaction
           before the response is sent: commit on success, roll back on a
           4xx/5xx. This covers endpoints not yet migrated to (1).
        3. As a final safety net, on a request that raised no exception we commit
           here at teardown. After (2) the REST connection is no longer in a
           transaction, so this is a no-op for REST; it exists to cover paths the
           middleware does not run on (the mounted MCP sub-app).

        On an unhandled exception we roll back whatever the handler left
        uncommitted.

        Caveat: the teardown commit is status-unaware, so for the MCP sub-app a
        write performed on a request that *returns* (not raises) an error status
        would still be committed. MCP write tools are being migrated to explicit
        units of work as follow-up; until then this matches the prior behaviour.
        """
        async with engine.connect() as conn:
            # Begin immediately so a transaction is active for the whole request
            # (matching the previous engine.begin() invariant). unit_of_work /
            # the commit middleware commit this before the response; any further
            # statements re-autobegin and are settled the same way.
            await conn.begin()
            try:
                yield conn
            except BaseException:
                if conn.in_transaction():
                    await conn.rollback()
                raise
            else:
                # Safety net for paths the middleware doesn't settle (MCP).
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

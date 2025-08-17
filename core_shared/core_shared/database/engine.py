"""
Async database engine and session management for integration workers.

Provides session-per-task pattern for ARQ workers with proper connection pooling.
"""

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker as AsyncSessionmaker
else:
    AsyncSessionmaker = async_sessionmaker


def create_session_factory(database_url: str) -> AsyncSessionmaker[AsyncSession]:
    """
    Create async session factory for integration workers.

    Uses session-per-task pattern with connection pooling for efficient
    database access in ARQ workers.

    Args:
        database_url: PostgreSQL connection URL

    Returns:
        Async session factory
    """
    # Convert sync URL to async if needed
    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        async_url = database_url

    # Create async engine with connection pooling
    engine = create_async_engine(
        async_url,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,
        echo=False,  # Set to True for debugging
    )

    # Create session factory
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )


def create_async_engine_from_url(
    database_url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 3600,
    echo: bool = False,
) -> AsyncEngine:
    """
    Create async SQLAlchemy engine with optimized connection pooling.

    Args:
        database_url: PostgreSQL connection URL
        pool_size: Number of connections to maintain in the pool
        max_overflow: Maximum number of connections that can overflow the pool
        pool_timeout: Timeout in seconds for getting connection from pool
        pool_recycle: Number of seconds after which a connection is recreated
        echo: Whether to log all SQL statements

    Returns:
        Configured async SQLAlchemy engine
    """
    # Convert sync URL to async if needed
    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        async_url = database_url

    return create_async_engine(
        async_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        echo=echo,
    )

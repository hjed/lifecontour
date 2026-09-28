"""
Shared database utilities for Lifecontour integrations.

Provides common database connection and session management utilities
that can be used across the main application and integration workers.
"""

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import QueuePool


def get_database_url(
    host: str | None = None,
    port: int | None = None,
    database: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """
    Get database URL from environment variables or provided parameters.

    Args:
        host: Database host (defaults to DATABASE_HOST env var or 'localhost')
        port: Database port (defaults to DATABASE_PORT env var or 5432)
        database: Database name (defaults to DATABASE_NAME env var or 'personal_management')
        username: Database username (defaults to DATABASE_USER env var or 'postgres')
        password: Database password (defaults to DATABASE_PASSWORD env var or 'postgres')

    Returns:
        PostgreSQL connection URL
    """
    # Check for full DATABASE_URL first
    if database_url := os.getenv("DATABASE_URL"):
        return database_url

    # Build URL from individual components
    host = host or os.getenv("DATABASE_HOST", "localhost")
    port = port or int(os.getenv("DATABASE_PORT", "5432"))
    database = database or os.getenv("DATABASE_NAME", "personal_management")
    username = username or os.getenv("DATABASE_USER", "postgres")
    password = password or os.getenv("DATABASE_PASSWORD", "postgres")

    return f"postgresql://{username}:{password}@{host}:{port}/{database}"


def create_engine_from_url(
    database_url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 3600,
    echo: bool = False,
) -> Engine:
    """
    Create SQLAlchemy engine with optimized connection pooling.

    Args:
        database_url: PostgreSQL connection URL
        pool_size: Number of connections to maintain in the pool
        max_overflow: Maximum number of connections that can overflow the pool
        pool_timeout: Timeout in seconds for getting connection from pool
        pool_recycle: Number of seconds after which a connection is recreated
        echo: Whether to log all SQL statements

    Returns:
        Configured SQLAlchemy engine
    """
    return create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        echo=echo,
        # Connection arguments for PostgreSQL
        connect_args={
            "connect_timeout": 10,
            "application_name": "personal_management_integration",
        },
    )


def create_engine_from_env(
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 3600,
    echo: bool | None = None,
) -> Engine:
    """
    Create SQLAlchemy engine using environment variables.

    Args:
        pool_size: Number of connections to maintain in the pool
        max_overflow: Maximum number of connections that can overflow the pool
        pool_timeout: Timeout in seconds for getting connection from pool
        pool_recycle: Number of seconds after which a connection is recreated
        echo: Whether to log SQL statements (defaults to DEBUG env var)

    Returns:
        Configured SQLAlchemy engine
    """
    database_url = get_database_url()

    # Default echo to DEBUG environment variable
    if echo is None:
        echo = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

    return create_engine_from_url(
        database_url=database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        echo=echo,
    )

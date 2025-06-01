"""
Database configuration and connection management.

Uses SQLAlchemy Core with explicit SQL queries for better readability
and AI assistant understanding. Provides connection management and
transaction support.
"""

from collections.abc import Generator
from functools import lru_cache

import structlog
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.config import get_settings
from app.infrastructure.database_metadata import metadata

# Import table definitions to register them with metadata
# This import must be after metadata is imported to avoid circular imports

logger = structlog.get_logger()


@lru_cache
def get_database_engine() -> Engine:
    """Get cached database engine."""
    settings = get_settings()

    engine = create_engine(
        str(settings.database_url),
        echo=settings.database_echo,
        pool_pre_ping=True,
        pool_recycle=300,
    )

    logger.info("Database engine created", url=str(settings.database_url).split("@")[0])
    return engine


@lru_cache
def get_async_database_engine() -> AsyncEngine:
    """Get cached async database engine."""
    settings = get_settings()

    # Convert postgresql:// to postgresql+asyncpg://
    async_url = str(settings.database_url).replace(
        "postgresql://", "postgresql+asyncpg://"
    )

    engine = create_async_engine(
        async_url,
        echo=settings.database_echo,
        pool_pre_ping=True,
        pool_recycle=300,
    )

    logger.info("Async database engine created", url=async_url.split("@")[0])
    return engine


def get_session_factory() -> sessionmaker[Session]:
    """Get SQLAlchemy session factory."""
    engine = get_database_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_database_session() -> Generator[Session, None, None]:
    """
    Dependency for getting database sessions in FastAPI endpoints.

    Provides automatic session management with proper cleanup.
    """
    session_local = get_session_factory()
    session = session_local()
    try:
        yield session
    finally:
        session.close()


def check_database_connection() -> bool:
    """
    Check if database connection is working.

    Returns:
        bool: True if connection is successful, False otherwise
    """
    try:
        engine = get_database_engine()
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.error("Database connection check failed", error=str(e))
        return False


def create_tables() -> None:
    """Create all database tables."""
    engine = get_database_engine()
    metadata.create_all(bind=engine)
    logger.info("Database tables created")


def drop_tables() -> None:
    """Drop all database tables (for testing)."""
    engine = get_database_engine()
    metadata.drop_all(bind=engine)
    logger.info("Database tables dropped")

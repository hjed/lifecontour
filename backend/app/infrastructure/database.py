"""
Database configuration and connection management.

Uses SQLAlchemy Core with explicit SQL queries for better readability
and AI assistant understanding. Provides connection management and
transaction support.
"""

from collections.abc import Generator
from functools import lru_cache

import structlog
from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.config import get_settings

logger = structlog.get_logger()

# SQLAlchemy metadata for table definitions
metadata = MetaData()


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

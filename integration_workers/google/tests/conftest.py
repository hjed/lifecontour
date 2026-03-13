"""
Pytest configuration for Google Contacts worker tests.

Sets up environment variables and fixtures needed for testing.
"""

import os

import pytest
import pytest_asyncio


# Set up environment variables before any imports
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables."""
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
    )
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    os.environ.setdefault("GOOGLE_CLIENT_ID", "test_client_id")
    os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test_client_secret")
    os.environ.setdefault("ENCRYPTION_KEY", "test_encryption_key_32_characters!")
    os.environ.setdefault("WORKER_ID", "test-worker")
    os.environ.setdefault("LOG_LEVEL", "INFO")


def get_async_database_url() -> str:
    """Get the database URL and ensure it uses asyncpg driver."""
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
    )
    if database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


@pytest_asyncio.fixture(scope="function")
async def async_engine():
    """Create async database engine for testing."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        get_async_database_url(),
        echo=False,
        pool_pre_ping=True,
        pool_recycle=300,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def async_connection(async_engine):
    """Create async database connection with transaction rollback."""
    async with async_engine.begin() as conn:
        nested_trans = await conn.begin_nested()
        try:
            yield conn
        finally:
            await nested_trans.rollback()


@pytest_asyncio.fixture(scope="function")
async def db_session(async_connection):
    """Create database session for tests ensuring isolation via savepoints."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(
        async_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session

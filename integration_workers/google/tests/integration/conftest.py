"""
Pytest configuration for Google Contacts worker integration tests.

Contains database session fixtures and migrations.
"""

import os
from typing import Any

import pytest_asyncio


def get_async_database_url() -> str:
    """Get the database URL and ensure it uses asyncpg driver."""
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
    )
    if database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


@pytest_asyncio.fixture(scope="function")
async def async_engine() -> Any:
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


@pytest_asyncio.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    """Apply Alembic migrations to the test database."""
    import subprocess
    from pathlib import Path

    backend_dir = Path(__file__).parent.parent.parent.parent.parent / "backend"

    # We use the DATABASE_URL environment variable which is already set
    env = os.environ.copy()

    # Run alembic upgrade head
    subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=backend_dir,
        check=True,
        env=env,
        capture_output=True,
    )


@pytest_asyncio.fixture(scope="function")
async def async_connection(async_engine: Any) -> Any:
    """Create async database connection with transaction rollback."""
    async with async_engine.begin() as conn:
        nested_trans = await conn.begin_nested()
        try:
            yield conn
        finally:
            await nested_trans.rollback()


@pytest_asyncio.fixture(scope="function")
async def db_session(async_connection: Any) -> Any:
    """Create database session for tests ensuring isolation via savepoints."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(
        async_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session

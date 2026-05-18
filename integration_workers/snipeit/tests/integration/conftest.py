"""
Pytest configuration for Snipe-IT worker integration tests.

Contains database session fixtures and migrations.
"""

import os
from typing import Any, cast

import pytest
import pytest_asyncio


def get_workspace_env() -> dict[str, str]:
    import json
    import subprocess
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent.parent.parent
    script = project_root / "scripts" / "workspace_env.py"
    try:
        result = subprocess.run(
            ["python3", str(script), "json"], check=True, capture_output=True, text=True
        )
        return cast(dict[str, str], json.loads(result.stdout))
    except Exception as e:
        raise RuntimeError(
            f"Failed to load workspace environment from {script}: {e}"
        ) from e


def get_async_database_url() -> str:
    """Get the database URL and ensure it uses asyncpg driver."""
    env = get_workspace_env()
    db_port = env.get("DB_TEST_PORT", "5433")
    default_url = f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"

    database_url = os.environ.get("DATABASE_URL", default_url)
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


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    """Apply Alembic migrations to the test database."""
    import subprocess
    from pathlib import Path

    backend_dir = Path(__file__).parent.parent.parent.parent.parent / "backend"

    # We use the DATABASE_URL environment variable which is already set
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)  # Prevent uv warning about mismatched environment
    env.pop("UV_RUN_RECURSION_DEPTH", None)  # Prevent nested uv run limitation
    # Prevent uv from reading .env and overwriting the DATABASE_URL
    env["UV_NO_ENV"] = "1"
    # Ensure alembic gets the correct dynamic database URL
    env["DATABASE_URL"] = get_async_database_url()

    # Run alembic upgrade head
    try:
        subprocess.run(
            ["uv", "run", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=backend_dir,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        print(f"Alembic failed (exit code {e.returncode}).")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        raise


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

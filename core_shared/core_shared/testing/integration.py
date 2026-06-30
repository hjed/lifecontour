"""Shared worker *integration* test fixtures.

Every integration worker hand-rolled the same database scaffolding in its
``tests/integration/conftest.py`` — a per-test async engine, a session-scoped
``alembic upgrade head``, a savepoint-wrapped connection, and a savepoint
session — plus the ``get_workspace_env``/``get_async_database_url`` helpers that
derive the workspace-isolated test database. This module defines each of those
once, resolved relative to the monorepo root rather than a brittle ``parent``
chain.

**Consumption — by import, not via ``pytest_plugins``.** A worker's
``tests/integration/conftest.py`` imports the fixtures it needs::

    from core_shared.testing.integration import (
        async_connection,
        async_engine,
        apply_migrations,
        db_session,
    )

    __all__ = ["async_connection", "async_engine", "apply_migrations", "db_session"]

They are imported (not registered as a plugin) on purpose: ``apply_migrations``
is ``autouse=True, scope="session"`` and must stay scoped to the integration
subtree. Registering this module globally via ``pytest_plugins`` (which is only
honoured in the top-level ``conftest.py`` anyway) would run ``alembic upgrade
head`` for every unit-test session too. Importing the fixtures into the
integration ``conftest.py`` keeps the autouse migration scoped exactly as the
per-worker copies did.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio


def get_repo_root() -> Path:
    """Return the monorepo root (the directory holding ``backend/`` + ``scripts/``).

    Resolved from this module's location: ``core_shared/core_shared/testing/``
    is three directories below the repository root.
    """
    return Path(__file__).resolve().parents[3]


def get_workspace_env() -> dict[str, str]:
    """Load workspace-specific ports from ``scripts/workspace_env.py``.

    Tests run with workspace-isolated Docker ports; this returns the resolved
    environment mapping for the current worktree.
    """
    script = get_repo_root() / "scripts" / "workspace_env.py"
    try:
        # Use the current interpreter (sys.executable) rather than a bare
        # "python3" so the helper always runs under the same toolchain as the
        # tests/uv environment invoking it.
        result = subprocess.run(
            [sys.executable, str(script), "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        return cast(dict[str, str], json.loads(result.stdout))
    except subprocess.CalledProcessError as e:
        # Surface stdout/stderr so a failing workspace_env.py is diagnosable in CI.
        raise RuntimeError(
            f"Failed to load workspace environment from {script} "
            f"(exit {e.returncode}).\nstdout: {e.stdout}\nstderr: {e.stderr}"
        ) from e
    except Exception as e:
        raise RuntimeError(
            f"Failed to load workspace environment from {script}: {e}"
        ) from e


def get_async_database_url() -> str:
    """Return the test database URL, ensuring it uses the asyncpg driver.

    Honours an explicit ``DATABASE_URL`` when set; otherwise derives the URL
    from the workspace-isolated test Postgres port.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        db_port = get_workspace_env().get("DB_TEST_PORT", "5433")
        database_url = (
            f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}"
            "/personal_management_test"
        )
    if database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


@pytest_asyncio.fixture(scope="function")
async def async_engine() -> Any:
    """Create an async database engine for testing."""
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
    """Apply Alembic migrations to the test database (once per session)."""
    backend_dir = get_repo_root() / "backend"

    # We use the DATABASE_URL environment variable which is already set.
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)  # Prevent uv warning about mismatched environment
    env.pop("UV_RUN_RECURSION_DEPTH", None)  # Prevent nested uv run limitation
    # Prevent uv from reading .env and overwriting the DATABASE_URL
    env["UV_NO_ENV"] = "1"
    # Ensure alembic gets the correct dynamic database URL
    env["DATABASE_URL"] = get_async_database_url()

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
    """Create an async database connection with transaction rollback."""
    async with async_engine.begin() as conn:
        nested_trans = await conn.begin_nested()
        try:
            yield conn
        finally:
            await nested_trans.rollback()


@pytest_asyncio.fixture(scope="function")
async def db_session(async_connection: Any) -> Any:
    """Create a database session for tests, ensuring isolation via savepoints."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(
        async_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session

"""
Pytest configuration and fixtures for the Personal Management System.

Provides common test fixtures, database setup, and test utilities
for unit, integration, and end-to-end tests.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.config import Settings
from app.infrastructure.database import get_database_session
from app.main import create_app

# Test database URL (PostgreSQL test database)
SQLALCHEMY_DATABASE_URL = (
    "postgresql://postgres:postgres@localhost:5432/personal_management_test"
)

# Create test engine
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Create test session factory
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_database_session() -> Generator[Session, None, None]:
    """Override database session for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


def run_test_migrations():
    """Run Alembic migrations for test database."""
    try:
        # Set test environment
        os.environ["ENVIRONMENT"] = "test"

        # Get backend directory
        backend_dir = Path(__file__).parent.parent

        # Configure Alembic
        alembic_cfg = Config(str(backend_dir / "alembic.ini"))
        alembic_cfg.set_main_option(
            "script_location", str(backend_dir / "app" / "migrations")
        )

        # Run migrations to head
        command.upgrade(alembic_cfg, "head")

    except Exception as e:
        print(f"Error running test migrations: {e}")
        raise


def drop_test_database():
    """Drop all tables in test database."""
    try:
        # Set test environment
        os.environ["ENVIRONMENT"] = "test"

        # Get backend directory
        backend_dir = Path(__file__).parent.parent

        # Configure Alembic
        alembic_cfg = Config(str(backend_dir / "alembic.ini"))
        alembic_cfg.set_main_option(
            "script_location", str(backend_dir / "app" / "migrations")
        )

        # Downgrade to base (drops all tables)
        command.downgrade(alembic_cfg, "base")

    except Exception as e:
        print(f"Error dropping test database: {e}")
        raise


@pytest.fixture(scope="function")
def test_db() -> Generator[None, None, None]:
    """Create test database tables using Alembic migrations."""
    # Run migrations to create all tables
    run_test_migrations()
    yield
    # Drop all tables by downgrading to base
    drop_test_database()


def override_get_settings() -> Settings:
    """Override settings for testing."""
    return Settings(
        debug=True,
        database_url="postgresql://postgres:postgres@localhost:5432/personal_management_test",
        allowed_hosts=["*"],  # Allow all hosts for testing
        cors_origins=["*"],
    )


@pytest.fixture(scope="function")
def client(test_db: Generator[None, None, None]) -> Generator[TestClient, None, None]:
    """Create test client with database override."""
    test_settings = override_get_settings()
    app = create_app(settings=test_settings)
    app.dependency_overrides[get_database_session] = override_get_database_session

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="function")
def db_session(test_db: Generator[None, None, None]) -> Generator[Session, None, None]:
    """Get test database session."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

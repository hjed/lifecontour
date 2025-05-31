"""
Pytest configuration and fixtures for the Personal Management System.

Provides common test fixtures, database setup, and test utilities
for unit, integration, and end-to-end tests.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.config import Settings
from app.infrastructure.database import get_database_session, metadata
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


@pytest.fixture(scope="function")
def test_db() -> Generator[None, None, None]:
    """Create test database tables."""
    metadata.create_all(bind=engine)
    yield
    metadata.drop_all(bind=engine)


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

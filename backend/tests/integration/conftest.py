"""Integration test configuration with Docker PostgreSQL support."""

import asyncio
import os
import subprocess
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

# Constants
CONTAINER_NAME_FILTER = "name=postgres-test"
BACKEND_POSTGRES_CONTAINER = "backend-postgres-test-1"
DOCKER_COMPOSE_TEST_FILE = "docker-compose.test.yml"
MAX_DB_STARTUP_RETRIES = 30


@dataclass
class DatabaseConfig:
    """Centralized database configuration for tests."""

    host: str
    port: str
    user: str
    password: str
    name: str

    @classmethod
    def from_environment(cls) -> "DatabaseConfig":
        """Create database config from environment variables with defaults."""
        return cls(
            host=os.getenv("TEST_DB_HOST", "localhost"),
            port=os.getenv("TEST_DB_PORT", "5433"),
            user=os.getenv("TEST_DB_USER", "postgres"),
            password=os.getenv("TEST_DB_PASSWORD", "postgres"),
            name=os.getenv("TEST_DB_NAME", "personal_management_test"),
        )

    def get_async_url(self) -> str:
        """Get async database URL for SQLAlchemy."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    def get_sync_url(self) -> str:
        """Get sync database URL for FastAPI."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class DockerManager:
    """Manages Docker operations for integration tests."""

    def __init__(self):
        self.backend_dir = self._get_backend_directory()
        self.docker_compose_cmd = self._get_docker_compose_cmd()

    def _get_backend_directory(self) -> str:
        """Get the backend directory path."""
        return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    def _get_docker_compose_cmd(self) -> list[str]:
        """Get the appropriate docker compose command."""
        # Try docker-compose first (standalone version)
        try:
            result = subprocess.run(
                ["docker-compose", "--version"],
                check=True,
                capture_output=True,
                text=True,
            )
            if "docker-compose" in result.stdout:
                return ["docker-compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Try docker compose (plugin version)
        try:
            result = subprocess.run(
                ["docker", "compose", "--version"],
                check=True,
                capture_output=True,
                text=True,
            )
            if "Docker Compose" in result.stdout:
                return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Default to docker-compose
        return ["docker-compose"]

    def is_container_running(self, container_filter: str) -> bool:
        """Check if a container matching the filter is running."""
        try:
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    container_filter,
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return bool(result.stdout.strip())
        except subprocess.CalledProcessError:
            return False

    def get_container_name(self, name_filter: str) -> str | None:
        """Get the actual container name matching the filter."""
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", name_filter, "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip() or None
        except subprocess.CalledProcessError:
            return None

    def start_database(self) -> None:
        """Start Docker PostgreSQL container for testing."""
        try:
            # Check if container is already running
            if self.is_container_running(f"name={BACKEND_POSTGRES_CONTAINER}"):
                print("Test database container already running")
                return

            # Start the container
            subprocess.run(
                self.docker_compose_cmd + ["-f", DOCKER_COMPOSE_TEST_FILE, "up", "-d"],
                cwd=self.backend_dir,
                check=True,
            )

            # Wait for database to be ready
            self._wait_for_database_ready()

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to start test database: {e}") from e

    def stop_database(self) -> None:
        """Stop Docker PostgreSQL container."""
        try:
            subprocess.run(
                self.docker_compose_cmd
                + ["-f", DOCKER_COMPOSE_TEST_FILE, "down", "-v"],
                cwd=self.backend_dir,
                check=True,
            )
            print("Test database stopped")
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to stop test database: {e}")

    def _wait_for_database_ready(self) -> None:
        """Wait for the database to be ready to accept connections."""
        for _i in range(MAX_DB_STARTUP_RETRIES):
            try:
                container_name = self.get_container_name(CONTAINER_NAME_FILTER)
                if not container_name:
                    time.sleep(1)
                    continue

                result = subprocess.run(
                    ["docker", "exec", container_name, "pg_isready", "-U", "postgres"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if result.returncode == 0:
                    print("Test database is ready")
                    time.sleep(2)  # Give it a bit more time
                    return
            except subprocess.CalledProcessError:
                pass

            time.sleep(1)

        raise RuntimeError("Test database failed to start within timeout")


# SQL DDL statements for test database schema (each statement executed separately)
TEST_DATABASE_SCHEMA_STATEMENTS = [
    # Drop tables if they exist (in reverse dependency order)
    "DROP TABLE IF EXISTS contact_tags CASCADE",
    "DROP TABLE IF EXISTS contact_notes CASCADE",
    "DROP TABLE IF EXISTS contact_addresses CASCADE",
    "DROP TABLE IF EXISTS contact_methods CASCADE",
    "DROP TABLE IF EXISTS contact_field_history CASCADE",
    "DROP TABLE IF EXISTS contact_edit_event CASCADE",
    "DROP TABLE IF EXISTS contacts CASCADE",
    "DROP TABLE IF EXISTS tags CASCADE",
    # Create tables
    """CREATE TABLE contacts (
        id SERIAL PRIMARY KEY,
        first_name VARCHAR(100) NOT NULL,
        last_name VARCHAR(100),
        middle_name VARCHAR(100),
        nick_name VARCHAR(100),
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE contact_methods (
        id SERIAL PRIMARY KEY,
        contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        method_type VARCHAR(50) NOT NULL,
        value VARCHAR(255) NOT NULL,
        label VARCHAR(100),
        is_primary BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE UNIQUE INDEX contact_methods_primary_unique
    ON contact_methods (contact_id, method_type)
    WHERE is_primary = true""",
    """CREATE UNIQUE INDEX contact_methods_email_unique
    ON contact_methods (value)
    WHERE method_type = 'email'""",
    """CREATE TABLE contact_addresses (
        id SERIAL PRIMARY KEY,
        contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        label VARCHAR(100),
        street_line_1 VARCHAR(255) NOT NULL,
        street_line_2 VARCHAR(255),
        locality VARCHAR(100),
        region VARCHAR(100),
        postal_code VARCHAR(20),
        country_code VARCHAR(2) NOT NULL,
        is_primary BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE UNIQUE INDEX contact_addresses_primary_unique
    ON contact_addresses (contact_id)
    WHERE is_primary = true""",
    """CREATE TABLE contact_notes (
        id SERIAL PRIMARY KEY,
        contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE tags (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL UNIQUE,
        parent_id INTEGER REFERENCES tags(id) ON DELETE SET NULL,
        color VARCHAR(7),
        description TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE contact_tags (
        contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (contact_id, tag_id)
    )""",
    """CREATE TABLE contact_field_history (
        id SERIAL PRIMARY KEY,
        entity_type VARCHAR(50) NOT NULL,
        entity_id INTEGER NOT NULL,
        field_name VARCHAR(100) NOT NULL,
        old_value TEXT,
        new_value TEXT,
        changed_by VARCHAR(100) DEFAULT 'system',
        created_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE contact_edit_event (
        id SERIAL PRIMARY KEY,
        event_id VARCHAR(255) NOT NULL UNIQUE,
        event_type VARCHAR(100) NOT NULL,
        aggregate_id INTEGER NOT NULL,
        event_data JSONB NOT NULL,
        occurred_at TIMESTAMP NOT NULL,
        correlation_id VARCHAR(255)
    )""",
]


# Global instances
_db_config = DatabaseConfig.from_environment()
_docker_manager = DockerManager()


def get_test_database_url() -> str:
    """Get test database URL from environment variables or use defaults."""
    return _db_config.get_async_url()


def restore_environment_variables(original_values: dict[str, str | None]) -> None:
    """Helper function to restore environment variables."""
    for key, value in original_values.items():
        if value is not None:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]


def clear_caches() -> None:
    """Helper function to clear FastAPI caches."""
    from app.infrastructure.config import get_settings
    from app.infrastructure.database import get_database_engine

    get_settings.cache_clear()
    get_database_engine.cache_clear()


def start_test_database():
    """Start Docker PostgreSQL container for testing."""
    _docker_manager.start_database()


def stop_test_database():
    """Stop Docker PostgreSQL container."""
    _docker_manager.stop_database()


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Setup and teardown test database for the entire test session."""
    # Skip Docker setup in CI - services are provided by GitHub Actions
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        print("Running in CI - using GitHub Actions services")
        yield
        return

    # Local development - use Docker Compose
    print("Running locally - starting Docker services")
    start_test_database()
    yield
    stop_test_database()


@pytest_asyncio.fixture(scope="function")
async def async_engine(setup_test_database) -> AsyncGenerator[AsyncEngine, None]:
    """Create async database engine for testing."""
    engine = create_async_engine(
        get_test_database_url(),
        echo=False,  # Set to True for SQL debugging
        pool_pre_ping=True,
        pool_recycle=300,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def async_connection(
    async_engine: AsyncEngine,
) -> AsyncGenerator[AsyncConnection, None]:
    """Create async database connection with transaction rollback."""
    async with async_engine.begin() as conn:
        # Execute each schema statement separately (asyncpg doesn't support multiple commands in one statement)
        for statement in TEST_DATABASE_SCHEMA_STATEMENTS:
            await conn.execute(text(statement))

        # Start a nested transaction for the test
        nested_trans = await conn.begin_nested()
        try:
            yield conn
        finally:
            # Always rollback the nested transaction
            await nested_trans.rollback()


@pytest_asyncio.fixture
async def clean_database(
    async_connection: AsyncConnection,
) -> AsyncGenerator[AsyncConnection, None]:
    """Provide a clean database connection for each test."""
    # Since we're using transaction rollback, each test starts with a clean state
    yield async_connection


@pytest.fixture
def integration_test_client():
    """Create test client for integration tests with real database setup."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    # Store original environment values
    original_values = {
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "ALLOWED_HOSTS": os.environ.get("ALLOWED_HOSTS"),
    }

    # Set environment variables for test database and allowed hosts
    os.environ["DATABASE_URL"] = _db_config.get_sync_url()
    os.environ["ALLOWED_HOSTS"] = '["*"]'

    # Clear the cached settings and database engine
    clear_caches()

    try:
        app = create_app()
        yield TestClient(app)
    finally:
        # Restore original environment
        restore_environment_variables(original_values)
        # Clear cache again to restore original settings
        clear_caches()


# Shared fixtures for API integration tests with authentication
@pytest.fixture
def test_user():
    """Create a test user for authentication."""
    from app.infrastructure.auth.models import SessionUser

    return SessionUser(
        id="test-user-123",
        email="test@example.com",
        name="Test User",
        avatar_url="https://example.com/avatar.jpg",
        provider="test",
    )


@pytest.fixture
def test_settings():
    """Create test settings that allow all hosts and use the correct test database."""
    from app.infrastructure.config import Settings

    return Settings(
        debug=True,
        database_url=get_test_database_url(),  # Use the same database URL as other integration tests
        allowed_hosts=["*"],  # Allow all hosts for testing
        cors_origins=["*"],
    )


@pytest.fixture
def authenticated_app(test_user, test_settings):
    """Create a FastAPI app with authentication overridden for testing."""
    from app.api.auth.dependencies import require_authentication
    from app.main import create_app

    def override_require_authentication():
        return test_user

    app = create_app(settings=test_settings)
    app.dependency_overrides[require_authentication] = override_require_authentication

    return app


@pytest.fixture
def mock_search_service():
    """Create a mock search service for testing."""
    from typing import Any
    from unittest.mock import MagicMock

    def _create_mock_service(search_results: dict[str, Any]):
        mock_service = MagicMock()
        mock_service.search_contacts.return_value = search_results
        mock_service.global_search.return_value = search_results
        return mock_service

    return _create_mock_service


@pytest.fixture
def authenticated_search_client(authenticated_app, mock_search_service):
    """
    Create a test client with authentication and search service mocking.

    Returns a tuple of (test_client, mock_service_factory).
    The mock_service_factory can be called with search results to set up the mock.
    """
    from typing import Any

    from fastapi.testclient import TestClient

    from app.api.dependencies import get_search_service

    def setup_search_mock(search_results: dict[str, Any]):
        mock_service = mock_search_service(search_results)
        authenticated_app.dependency_overrides[get_search_service] = (
            lambda: mock_service
        )
        return mock_service

    test_client = TestClient(authenticated_app)
    return test_client, setup_search_mock

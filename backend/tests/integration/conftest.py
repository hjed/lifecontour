"""Integration test configuration with Docker PostgreSQL support."""

import asyncio
import os
import subprocess
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, cast

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
        # Try docker compose first (plugin version - preferred in CI)
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

        # Try docker-compose (standalone version)
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

        # Default to docker compose (newer version)
        return ["docker", "compose"]

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

            # Run database migrations
            print("Running database migrations...")
            self._run_migrations()

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

    def _run_migrations(self) -> None:
        """Run database migrations on test database."""
        try:
            import os
            import sys

            # Set test environment and database URL
            test_env = {
                **os.environ,
                "ENVIRONMENT": "test",
                "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5433/personal_management_test",
            }

            print(f"Running migrations from directory: {self.backend_dir}")
            print(f"Python executable: {sys.executable}")
            print(f"Database URL: {test_env['DATABASE_URL']}")

            # Run migrations using alembic directly
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=self.backend_dir,
                capture_output=True,
                text=True,
                check=True,
                env=test_env,
            )
            print("Database migrations completed successfully")
            print(f"Migration output: {result.stdout}")

        except subprocess.CalledProcessError as e:
            print(f"Migration output: {e.stdout}")
            print(f"Migration error: {e.stderr}")
            raise RuntimeError(f"Failed to run migrations: {e}") from e

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
    "DROP TABLE IF EXISTS journal_travel_transportation CASCADE",
    "DROP TABLE IF EXISTS journal_travel_accommodations CASCADE",
    "DROP TABLE IF EXISTS journal_travel_flights CASCADE",
    "DROP TABLE IF EXISTS journal_travel_data CASCADE",
    "DROP TABLE IF EXISTS journal_plan_documents CASCADE",
    "DROP TABLE IF EXISTS journal_plan_data CASCADE",
    "DROP TABLE IF EXISTS journal_photo_album_data CASCADE",
    "DROP TABLE IF EXISTS journal_mood_data CASCADE",
    "DROP TABLE IF EXISTS journal_calendar_info CASCADE",
    "DROP TABLE IF EXISTS journals CASCADE",
    "DROP TABLE IF EXISTS calendars CASCADE",
    "DROP TABLE IF EXISTS contact_relationships CASCADE",
    "DROP TABLE IF EXISTS contact_tags CASCADE",
    "DROP TABLE IF EXISTS contact_notes CASCADE",
    "DROP TABLE IF EXISTS contact_addresses CASCADE",
    "DROP TABLE IF EXISTS contact_methods CASCADE",
    "DROP TABLE IF EXISTS contact_field_history CASCADE",
    "DROP TABLE IF EXISTS contact_edit_event CASCADE",
    "DROP TABLE IF EXISTS contacts CASCADE",
    "DROP TABLE IF EXISTS tags CASCADE",
    "DROP TABLE IF EXISTS user_google_auth CASCADE",
    # Create tables
    """CREATE TABLE contacts (
        id SERIAL PRIMARY KEY,
        first_name VARCHAR(100) NOT NULL,
        last_name VARCHAR(100),
        middle_name VARCHAR(100),
        nick_name VARCHAR(100),
        is_favourite BOOLEAN DEFAULT FALSE NOT NULL,
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
    """CREATE TABLE contact_relationships (
        id SERIAL PRIMARY KEY,
        from_contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        to_contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        relationship_type VARCHAR(50) NOT NULL CHECK (relationship_type IN ('partner', 'child', 'parent', 'sibling', 'friend', 'colleague', 'family', 'other')),
        created_at TIMESTAMP DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
        CONSTRAINT ck_contact_relationships_no_self_reference CHECK (from_contact_id != to_contact_id),
        CONSTRAINT uq_contact_relationships_unique_relationship UNIQUE (from_contact_id, to_contact_id, relationship_type)
    )""",
    """CREATE TABLE user_google_auth (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR(50) NOT NULL,
        google_account_email VARCHAR(255) NOT NULL,
        encrypted_access_token BYTEA NOT NULL,
        encrypted_refresh_token BYTEA,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        CONSTRAINT uq_user_google_account UNIQUE (user_id, google_account_email)
    )""",
    """CREATE INDEX idx_user_google_auth_user_id ON user_google_auth (user_id)""",
    """CREATE INDEX idx_user_google_auth_email ON user_google_auth (google_account_email)""",
    # Journals table
    """CREATE TABLE journals (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR(50) NOT NULL,
        title VARCHAR(500) NOT NULL,
        content TEXT NOT NULL,
        event_date_range_start TIMESTAMP WITH TIME ZONE NOT NULL,
        event_date_range_end TIMESTAMP WITH TIME ZONE NOT NULL,
        parent_id INTEGER REFERENCES journals(id) ON DELETE SET NULL,
        "order" INTEGER,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        CONSTRAINT ck_journals_event_date_range_valid CHECK (event_date_range_start <= event_date_range_end)
    )""",
    """CREATE INDEX idx_journals_user_id ON journals (user_id)""",
    """CREATE INDEX idx_journals_parent_id ON journals (parent_id)""",
    """CREATE INDEX idx_journals_event_date_range ON journals (event_date_range_start, event_date_range_end)""",
    """CREATE INDEX idx_journals_child_ordering ON journals (parent_id, event_date_range_start, "order")""",
    """CREATE INDEX idx_journals_created_at ON journals (created_at)""",
    # Calendars table
    """CREATE TABLE calendars (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id VARCHAR(50) NOT NULL,
        name VARCHAR(100) NOT NULL,
        color VARCHAR(7) NOT NULL,
        description TEXT,
        is_synced_to_google BOOLEAN DEFAULT FALSE NOT NULL,
        google_calendar_id VARCHAR(255),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )""",
    """CREATE INDEX idx_calendars_user_id ON calendars (user_id)""",
    # Journal calendar info table (EVENT type)
    """CREATE TABLE journal_calendar_info (
        journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
        calendar_id UUID NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
        start_time TIME,
        end_time TIME,
        is_all_day BOOLEAN DEFAULT FALSE NOT NULL,
        location VARCHAR(500),
        sync_invitees BOOLEAN DEFAULT FALSE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )""",
    """CREATE INDEX idx_journal_calendar_info_calendar_id ON journal_calendar_info (calendar_id)""",
    # Journal mood data table (MOOD_RATING type)
    """CREATE TABLE journal_mood_data (
        journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
        mood_value INTEGER CHECK (mood_value IS NULL OR (mood_value >= 1 AND mood_value <= 10)),
        mood_label VARCHAR(50),
        energy_level INTEGER CHECK (energy_level IS NULL OR (energy_level >= 1 AND energy_level <= 10)),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )""",
    # Journal photo album data table (PHOTO_ALBUM type)
    """CREATE TABLE journal_photo_album_data (
        journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
        immich_album_id VARCHAR(255) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )""",
    # Journal plan data table (PLAN type)
    """CREATE TABLE journal_plan_data (
        journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )""",
    # Journal plan documents table
    """CREATE TABLE journal_plan_documents (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        journal_id INTEGER NOT NULL REFERENCES journal_plan_data(journal_id) ON DELETE CASCADE,
        url VARCHAR(2000) NOT NULL,
        title VARCHAR(500) NOT NULL,
        description TEXT,
        "order" INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )""",
    # Journal travel data table (TRAVEL type)
    """CREATE TABLE journal_travel_data (
        journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )""",
    # Journal travel flights table
    """CREATE TABLE journal_travel_flights (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        journal_id INTEGER NOT NULL REFERENCES journal_travel_data(journal_id) ON DELETE CASCADE,
        flight_number VARCHAR(20) NOT NULL,
        airline VARCHAR(100),
        departure_airport VARCHAR(10) NOT NULL,
        arrival_airport VARCHAR(10) NOT NULL,
        departure_time TIMESTAMP WITH TIME ZONE NOT NULL,
        arrival_time TIMESTAMP WITH TIME ZONE NOT NULL,
        booking_reference VARCHAR(100),
        seat_number VARCHAR(20),
        confirmation_number VARCHAR(100),
        "order" INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )""",
    # Journal travel accommodations table
    """CREATE TABLE journal_travel_accommodations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        journal_id INTEGER NOT NULL REFERENCES journal_travel_data(journal_id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        address TEXT,
        check_in_date DATE NOT NULL,
        check_out_date DATE NOT NULL,
        booking_reference VARCHAR(100),
        confirmation_number VARCHAR(100),
        "order" INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
        CHECK (check_in_date < check_out_date)
    )""",
    # Journal travel transportation table
    """CREATE TABLE journal_travel_transportation (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        journal_id INTEGER NOT NULL REFERENCES journal_travel_data(journal_id) ON DELETE CASCADE,
        type VARCHAR(50) NOT NULL,
        details TEXT NOT NULL,
        booking_reference VARCHAR(100),
        "order" INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
    )""",
]


# Global instances
_db_config = DatabaseConfig.from_environment()
_docker_manager = DockerManager()


@pytest.fixture(scope="session")
def db_config() -> DatabaseConfig:
    """Shared database configuration fixture for integration tests."""
    return _db_config


def get_test_database_url() -> str:
    """Get test database URL from environment variables or use defaults."""
    # Use development database if available
    if _is_dev_database_available():
        return "postgresql+asyncpg://dev_user:dev_password@localhost:5432/personal_management_dev"

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


def _is_dev_database_available() -> bool:
    """Check if development database is available."""
    try:
        import psycopg2

        # Try to connect to development database
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="personal_management_dev",
            user="dev_user",
            password="dev_password",
        )
        conn.close()
        return True
    except Exception:
        return False


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

    # Check if development database is available
    if _is_dev_database_available():
        print("Using existing development database for integration tests")
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
        meilisearch_url="http://localhost:7701",  # Use test MeiliSearch port
        meilisearch_api_key="test_master_key",  # Use test API key
        allowed_hosts=["*"],  # Allow all hosts for testing
        cors_origins=["*"],
    )


@pytest.fixture
def authenticated_app(test_settings):
    """Create a FastAPI app for testing."""
    from app.main import create_app

    # Note: With Dishka, authentication is handled through the container
    # For integration tests, we use the real authentication flow
    # Individual tests can mock the session as needed
    app = create_app(settings=test_settings)
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
def authenticated_search_client(test_settings, mock_search_service, test_user):
    """
    Create a test client with authentication and search service mocking.

    Returns a tuple of (test_client, mock_service_factory).
    The mock_service_factory can be called with search results to set up the mock.
    """
    from typing import Any

    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import setup_dishka
    from fastapi.testclient import TestClient

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.search.search_service import SearchService

    # Store the mock service so it can be updated
    mock_search_service_instance = None

    class TestAuthSearchProvider(Provider):
        """Test provider for authenticated search client."""

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            from typing import cast

            return cast(SessionUser, test_user)

        @provide(scope=Scope.REQUEST)
        def get_search_service(self) -> SearchService:
            # Return the mock service if it's been set up
            if mock_search_service_instance is not None:
                return mock_search_service_instance
            # Otherwise return a real service (which will fail if MeiliSearch is not available)
            return SearchService()

    def setup_search_mock(search_results: dict[str, Any]):
        """Setup search mock for testing."""
        nonlocal mock_search_service_instance
        mock_search_service_instance = mock_search_service(search_results)
        return mock_search_service_instance

    # Create app with test settings
    from app.main import create_app

    app = create_app(settings=test_settings)

    # Replace container with test container
    test_container = make_async_container(TestAuthSearchProvider())
    try:
        app.state.dishka_container.close()
    except RuntimeError:
        pass
    app.state.dishka_container = test_container
    setup_dishka(test_container, app)

    test_client = TestClient(app)
    return test_client, setup_search_mock


@pytest_asyncio.fixture
async def authenticated_client(test_settings, test_user):
    """Create an authenticated test client for integration tests."""
    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import setup_dishka
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.auth.oauth_service import OAuthService
    from app.infrastructure.config import Settings
    from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
    from app.infrastructure.search.search_service import SearchService
    from app.main import create_app

    class TestAuthProvider(Provider):
        """Test provider for authenticated client."""

        @provide(scope=Scope.APP)
        def get_settings(self) -> Settings:
            """Get test settings for app scope."""
            return cast(Settings, test_settings)

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            return cast(SessionUser, test_user)

        @provide(scope=Scope.REQUEST)
        def get_oauth_service(self, settings: Settings) -> OAuthService:
            """Get OAuth service instance for request scope."""
            return OAuthService(settings)

        @provide(scope=Scope.APP)
        def get_search_service(self) -> SearchService:
            """
            Get search service (singleton for app lifetime).

            Required for full app initialization even if not directly used in OAuth tests.
            Some routes depend on SearchService being available in the DI container.

            Note: This is a mock/stub instance created without dependencies or configuration,
            and is intended for testing purposes only.
            """
            return SearchService()

        @provide(scope=Scope.REQUEST)
        def get_outbox_event_publisher(
            self, connection: AsyncConnection
        ) -> OutboxEventPublisher:
            """
            Get outbox event publisher for request scope.

            Required for full app initialization even if not directly used in OAuth tests.
            Some routes depend on OutboxEventPublisher being available in the DI container.
            """
            return OutboxEventPublisher(connection)

    # Create app with test settings
    app = create_app(settings=test_settings)

    # Replace container with test container that includes all providers
    from dishka.integrations.fastapi import FastapiProvider

    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.database import DatabaseProvider
    from app.infrastructure.di.integrations import IntegrationProvider

    test_container = make_async_container(
        DatabaseProvider(test_settings),
        TestAuthProvider(),
        ContactProvider(),
        IntegrationProvider(),
        FastapiProvider(),
    )
    try:
        await app.state.dishka_container.close()
    except (RuntimeError, AttributeError):
        pass
    app.state.dishka_container = test_container
    setup_dishka(test_container, app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def redis_pool():
    """Create a mock Redis pool for testing."""
    from unittest.mock import AsyncMock

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.close = AsyncMock()
    return mock_redis


@pytest.fixture
def mock_session_user(test_user):
    """Provide a mock session user for testing."""
    return test_user


class ContactFactory:
    """Factory for creating contacts in integration tests."""

    def __init__(self, client):
        self.client = client

    async def create_contact(
        self, first_name: str, last_name: str | None = None
    ) -> dict[str, Any]:
        """Create a contact via API and return the response data."""
        request_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }

        response = await self.client.post("/api/contacts", json=request_data)
        assert response.status_code == 201
        return response.json()["data"]  # type: ignore[no-any-return]

    async def create_relationship(
        self, from_contact_id: int, to_contact_id: int, relationship_type: Any
    ) -> dict[str, Any]:
        """Create a relationship via API and return the response data."""
        from app.core.contacts.models.entities import RelationshipType

        # Convert enum to string if needed
        if isinstance(relationship_type, RelationshipType):
            relationship_type_str = relationship_type.value
        else:
            relationship_type_str = relationship_type

        request_data = {
            "data": {
                "type": "contact_relationships",
                "attributes": {
                    "relationship_type": relationship_type_str,
                    "from_contact_id": from_contact_id,
                    "to_contact_id": to_contact_id,
                },
            }
        }

        response = await self.client.post(
            f"/api/contacts/{from_contact_id}/relationships", json=request_data
        )
        assert response.status_code == 201
        return response.json()["data"]  # type: ignore[no-any-return]


@pytest_asyncio.fixture
async def contact_factory(authenticated_client):
    """Provide a ContactFactory for integration tests."""
    return ContactFactory(authenticated_client)


# Journal integration test fixtures
@pytest_asyncio.fixture
async def db_connection(async_connection: AsyncConnection) -> AsyncConnection:
    """Alias for async_connection for journal integration tests."""
    return async_connection


@pytest_asyncio.fixture
async def sample_journal_id(async_connection: AsyncConnection) -> int:
    """Create a sample journal for testing and return its ID."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    now = datetime.now(UTC)
    query = text("""
        INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
        VALUES (:user_id, :title, :content, :start, :end)
        RETURNING id
    """)

    result = await async_connection.execute(
        query,
        {
            "user_id": "test-user-123",
            "title": "Test Journal",
            "content": "Test content",
            "start": now,
            "end": now + timedelta(hours=1),
        },
    )
    row = result.fetchone()
    assert row is not None
    return int(row[0])

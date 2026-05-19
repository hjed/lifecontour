"""Integration test configuration with Docker PostgreSQL support."""

import asyncio
import json
import os
import subprocess
import time
from base64 import b64encode
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import pytest
import pytest_asyncio
from dishka.integrations.fastapi import setup_dishka as setup_fastapi_dishka
from dishka.integrations.starlette import setup_dishka as setup_starlette_dishka
from itsdangerous import TimestampSigner
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from tests.integration.sse_helpers import reset_sse_starlette_appstatus_event

# Constants
DOCKER_COMPOSE_FILE = "docker-compose.yml"
MAX_DB_STARTUP_RETRIES = 30


def get_workspace_env() -> dict[str, str]:
    import json
    import subprocess
    import typing
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent.parent
    script = project_root / "scripts" / "workspace_env.py"
    result = subprocess.run(
        ["python3", str(script), "json"], check=True, capture_output=True, text=True
    )
    return typing.cast(dict[str, str], json.loads(result.stdout))


workspace_env = get_workspace_env()
CONTAINER_PREFIX = workspace_env.get("CONTAINER_PREFIX", "pms")
CONTAINER_NAME_FILTER = f"name={CONTAINER_PREFIX}-postgres"
BACKEND_POSTGRES_CONTAINER = f"{CONTAINER_PREFIX}-postgres"


@dataclass
class DatabaseConfig:
    """Centralized database configuration for tests."""

    host: str
    port: str
    user: str
    password: str
    name: str

    @classmethod
    def from_environment(cls) -> DatabaseConfig:
        """Create database config from environment variables with defaults."""
        return cls(
            host=os.getenv("TEST_DB_HOST", "localhost"),
            port=os.getenv("TEST_DB_PORT", workspace_env.get("DB_TEST_PORT", "5433")),
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
        self.project_root = self._get_project_root()
        self.docker_compose_cmd = self._get_docker_compose_cmd()
        # Keep a local copy so Docker/migration helpers don't rely on module globals.
        self.db_config = DatabaseConfig.from_environment()

    def _run_psql_in_container(
        self, container_name: str, database: str, sql: str
    ) -> None:
        """Execute a SQL statement via psql inside the Postgres container.

        This is used to reset the test database deterministically between runs.
        """
        subprocess.run(
            [
                "docker",
                "exec",
                container_name,
                "psql",
                "-U",
                "postgres",
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    def _reset_test_database(self, container_name: str) -> None:
        """Drop + recreate the integration test database.

        We do this before running Alembic migrations because local runs can leave
        the test database in a partially-migrated state (e.g. if a previous test
        session crashed before teardown). That makes migrations non-deterministic
        and can cause failures like DuplicateTable.
        """
        db_name = self.db_config.name

        print(f"Resetting test database: {db_name}")

        # WITH (FORCE) terminates any remaining sessions atomically before
        # dropping the database, preventing the "being accessed by other users"
        # race condition that occurs when a dev backend container reconnects
        # immediately after a separate pg_terminate_backend call.
        # Requires PostgreSQL 13+ (we use postgres:15-alpine).
        self._run_psql_in_container(
            container_name,
            "postgres",
            f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE);",
        )
        self._run_psql_in_container(
            container_name,
            "postgres",
            f"CREATE DATABASE {db_name};",
        )

        # Ensure required extensions exist for migrations (many migrations use gen_random_uuid()).
        # NOTE: gen_random_uuid() is provided by pgcrypto.
        self._run_psql_in_container(
            container_name,
            db_name,
            'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";',
        )
        self._run_psql_in_container(
            container_name,
            db_name,
            'CREATE EXTENSION IF NOT EXISTS "pg_trgm";',
        )
        self._run_psql_in_container(
            container_name,
            db_name,
            "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
        )

    def _get_backend_directory(self) -> str:
        """Get the backend directory path."""
        return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    def _get_project_root(self) -> str:
        """Get the project root directory path."""
        return os.path.dirname(self.backend_dir)

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
        except subprocess.CalledProcessError, FileNotFoundError:
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
        except subprocess.CalledProcessError, FileNotFoundError:
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
            # If the container isn't running yet, bring up the test-backend profile.
            # If it's already running, we keep it (to avoid disrupting dev workflows),
            # but we still reset the *test database* so migrations are deterministic.
            if not self.is_container_running(f"name={BACKEND_POSTGRES_CONTAINER}"):
                subprocess.run(
                    self.docker_compose_cmd
                    + [
                        "-f",
                        DOCKER_COMPOSE_FILE,
                        "--profile",
                        "test-backend",
                        "--env-file",
                        ".env.test",
                        "up",
                        "-d",
                    ],
                    cwd=self.project_root,
                    check=True,
                    env={**os.environ, **workspace_env},
                )
            else:
                print("Test database container already running")

            # Wait for database to be ready
            self._wait_for_database_ready()

            container_name = (
                self.get_container_name(CONTAINER_NAME_FILTER)
                or BACKEND_POSTGRES_CONTAINER
            )

            # Reset the test DB to avoid partially-migrated state from previous runs.
            self._reset_test_database(container_name)

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
                + [
                    "-f",
                    DOCKER_COMPOSE_FILE,
                    "--profile",
                    "test-backend",
                    "down",
                    "-v",
                ],
                cwd=self.project_root,
                check=True,
                env={**os.environ, **workspace_env},
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
                "DATABASE_URL": self.db_config.get_async_url(),
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


# Global instances
_docker_manager = DockerManager()
_db_config = _docker_manager.db_config


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
    from app.infrastructure.database import (
        get_async_database_engine,
        get_database_engine,
    )

    get_settings.cache_clear()
    get_database_engine.cache_clear()
    get_async_database_engine.cache_clear()


@asynccontextmanager
async def _authenticated_client_context(
    async_connection: AsyncConnection,
    test_settings: Any,
    test_user: Any,
    *,
    start_lifespan: bool = False,
) -> AsyncGenerator[Any]:
    """Create an authenticated async client for integration tests."""
    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import FastapiProvider
    from httpx import ASGITransport, AsyncClient

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.auth.oauth_service import OAuthService
    from app.infrastructure.config import Settings
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
    from app.infrastructure.di.journal import JournalProvider
    from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
    from app.infrastructure.search.search_service import SearchService
    from app.main import create_app

    class TestDatabaseProvider(Provider):
        """Provides the test savepoint connection to the DI container."""

        def __init__(self, connection: AsyncConnection):
            super().__init__()
            self.connection = connection

        @provide(scope=Scope.REQUEST)
        def get_connection(self) -> AsyncConnection:
            return self.connection

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
            """Get search service (test stub)."""
            return SearchService()

        @provide(scope=Scope.REQUEST)
        def get_outbox_event_publisher(
            self, connection: AsyncConnection
        ) -> OutboxEventPublisher:
            """Get outbox event publisher for request scope."""
            return OutboxEventPublisher(connection)

    original_values = {"DATABASE_URL": os.environ.get("DATABASE_URL")}
    if start_lifespan:
        os.environ["DATABASE_URL"] = str(test_settings.database_url)
        clear_caches()

    app = create_app(settings=test_settings)
    test_container = make_async_container(
        TestDatabaseProvider(async_connection),
        InfrastructureProvider(),
        TestAuthProvider(),
        ContactProvider(),
        JournalProvider(),
        IntegrationProvider(),
        FastapiProvider(),
    )

    try:
        try:
            await app.state.dishka_container.close()
        except RuntimeError, AttributeError:
            pass

        app.state.dishka_container = test_container
        setup_fastapi_dishka(test_container, app)
        mcp_app = getattr(app.state, "mcp_app", None)
        if mcp_app is not None:
            mcp_app.state.dishka_container = test_container
            setup_starlette_dishka(test_container, mcp_app)

        @asynccontextmanager
        async def client_context() -> AsyncGenerator[AsyncClient]:
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                client.cookies.set(
                    "session",
                    _create_session_cookie_value(
                        {"user": test_user.model_dump(mode="json")},
                        test_settings.session_secret_key,
                    ),
                )
                yield client

        if start_lifespan:
            reset_sse_starlette_appstatus_event()
            async with app.router.lifespan_context(app):
                async with client_context() as client:
                    yield client
        else:
            async with client_context() as client:
                yield client
    finally:
        if not start_lifespan:
            await test_container.close()
        if start_lifespan:
            reset_sse_starlette_appstatus_event()
            restore_environment_variables(original_values)
            clear_caches()


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
    except psycopg2.Error, OSError:
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
async def async_engine(setup_test_database) -> AsyncGenerator[AsyncEngine]:
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
) -> AsyncGenerator[AsyncConnection]:
    """Create async database connection with transaction rollback.

    Database schema is expected to be prepared (migrated) before tests run.
    In local development this is typically done when starting the test
    database (e.g. via setup_test_database / DockerManager.start_database()).
    In CI, migrations are applied by the workflow before pytest is invoked.
    Each test gets its own savepoint so writes are rolled back without
    touching DDL.
    """
    async with async_engine.begin() as conn:
        nested_trans = await conn.begin_nested()
        try:
            yield conn
        finally:
            await nested_trans.rollback()


@pytest_asyncio.fixture
async def clean_database(
    async_connection: AsyncConnection,
) -> AsyncGenerator[AsyncConnection]:
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
        "REDIS_URL": os.environ.get("REDIS_URL"),
    }

    # Set environment variables for test database and allowed hosts
    os.environ["DATABASE_URL"] = _db_config.get_sync_url()
    os.environ["ALLOWED_HOSTS"] = '["*"]'
    os.environ["REDIS_URL"] = os.environ.get("REDIS_URL") or (
        "redis://localhost:" + workspace_env.get("REDIS_TEST_PORT", "6380")
    )

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


def _create_session_cookie_value(session_data: dict[str, Any], secret_key: str) -> str:
    """Create a Starlette SessionMiddleware-compatible session cookie value."""
    encoded_session = b64encode(json.dumps(session_data).encode("utf-8"))
    signer = TimestampSigner(secret_key)
    return signer.sign(encoded_session).decode("utf-8")


@pytest.fixture
def test_settings():
    """Create test settings that allow all hosts and use the correct test database."""
    from app.infrastructure.config import Settings

    return Settings(
        debug=True,
        database_url=get_test_database_url(),  # Use the same database URL as other integration tests
        redis_url=os.getenv(
            "REDIS_URL",
            "redis://localhost:" + workspace_env.get("REDIS_TEST_PORT", "6380"),
        ),  # Use test Redis port
        meilisearch_url=os.getenv(
            "MEILISEARCH_URL",
            "http://localhost:" + workspace_env.get("MEILI_TEST_PORT", "7701"),
        ),
        meilisearch_api_key=os.getenv("MEILISEARCH_API_KEY", "test_master_key"),
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
    from unittest.mock import MagicMock

    def _create_mock_service(search_results: dict[str, Any]):
        mock_service = MagicMock()
        mock_service.search_contacts.return_value = search_results
        mock_service.global_search.return_value = search_results
        return mock_service

    return _create_mock_service


@pytest.fixture
def authenticated_search_client(
    test_settings, mock_search_service, test_user, async_connection
):
    """
    Create a test client with authentication and search service mocking.

    Returns a tuple of (test_client, setup_search_mock).
    The setup_search_mock can be called with search results to set up the mock.
    """
    from typing import cast

    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import setup_dishka
    from fastapi.testclient import TestClient

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.config import Settings
    from app.infrastructure.search.search_service import SearchService

    # Use a mutable container to store the mock service so it can be updated
    mock_service_container = {"instance": None}

    class SearchServiceWrapper:
        """Wrapper that defers to mock or real service at runtime."""

        def __init__(self, mock_container: dict[str, Any]):
            self.mock_container = mock_container

        def _get_service(self):
            """Get the appropriate service (mock or real)."""
            if self.mock_container["instance"] is not None:
                return self.mock_container["instance"]
            return SearchService()

        def __getattr__(self, name):
            """Delegate all method calls to the appropriate service."""
            return getattr(self._get_service(), name)

    class TestAuthSearchProvider(Provider):
        """Test provider for authenticated search client."""

        @provide(scope=Scope.APP)
        def get_settings(self) -> Settings:
            """Get test settings for app scope."""
            return cast(Settings, test_settings)

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            return cast(SessionUser, test_user)

        @provide(scope=Scope.APP)
        def get_search_service(self) -> SearchService:
            # Return a wrapper that defers to mock or real service at runtime
            return cast(SearchService, SearchServiceWrapper(mock_service_container))

    def setup_search_mock(search_results: dict[str, Any]):
        """Setup search mock for testing."""
        mock_service_container["instance"] = mock_search_service(search_results)
        return mock_service_container["instance"]

    class TestDatabaseProvider(Provider):
        """Provides the test savepoint connection to the DI container."""

        def __init__(self, connection: AsyncConnection):
            super().__init__()
            self.connection = connection

        @provide(scope=Scope.REQUEST)
        def get_connection(self) -> AsyncConnection:
            return self.connection

    # Create app with test settings
    from dishka.integrations.fastapi import FastapiProvider

    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
    from app.infrastructure.di.journal import JournalProvider
    from app.main import create_app

    app = create_app(settings=test_settings)

    # Replace container with test container
    # TestAuthSearchProvider provides Settings, SessionUser, and SearchService
    # IMPORTANT: TestAuthSearchProvider must come AFTER ContactProvider because
    # ContactProvider also provides SearchService (duplicate in production code).
    # Later providers override earlier ones in Dishka.
    test_container = make_async_container(
        TestDatabaseProvider(async_connection),
        InfrastructureProvider(),
        ContactProvider(),
        JournalProvider(),
        IntegrationProvider(),
        TestAuthSearchProvider(),  # Must be after ContactProvider to override SearchService
        FastapiProvider(),
    )
    # Don't try to close the old container - just replace it
    app.state.dishka_container = test_container
    setup_dishka(test_container, app)

    test_client = TestClient(app)
    return test_client, setup_search_mock


@pytest_asyncio.fixture
async def authenticated_client(
    async_connection: AsyncConnection, test_settings, test_user
):
    """Create an authenticated test client for integration tests.

    Uses the test savepoint connection (async_connection) so that all DB writes
    during a test are rolled back when the savepoint is released, preventing
    state leakage between tests.
    """
    async with _authenticated_client_context(
        async_connection,
        test_settings,
        test_user,
    ) as client:
        yield client


@pytest_asyncio.fixture
async def authenticated_lifespan_client(
    async_connection: AsyncConnection, test_settings, test_user
) -> AsyncGenerator[Any]:
    """Provide an authenticated client factory that manages app lifespan."""

    @asynccontextmanager
    async def factory() -> AsyncGenerator[Any]:
        async with _authenticated_client_context(
            async_connection,
            test_settings,
            test_user,
            start_lifespan=True,
        ) as client:
            yield client

    yield factory


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
        self,
        from_contact_id: int,
        to_contact_id: int | None,
        relationship_type: Any,
        *,
        to_user: bool = False,
    ) -> dict[str, Any]:
        """Create a relationship via API and return the response data."""
        from core_shared.models.contacts.entities import RelationshipType

        # Convert enum to string if needed
        if isinstance(relationship_type, RelationshipType):
            relationship_type_str = relationship_type.value
        else:
            relationship_type_str = relationship_type

        attributes: dict[str, Any] = {
            "relationship_type": relationship_type_str,
            "from_contact_id": from_contact_id,
            "to_user": to_user,
        }
        if to_contact_id is not None:
            attributes["to_contact_id"] = to_contact_id

        request_data = {
            "data": {
                "type": "contact_relationships",
                "attributes": attributes,
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

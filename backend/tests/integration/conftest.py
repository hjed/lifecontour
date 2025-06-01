"""Integration test configuration with Docker PostgreSQL support."""

import asyncio
import os
import subprocess
import time
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

# Test database URL for async operations (using port 5433 for Docker)
ASYNC_TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/personal_management_test"


def start_test_database():
    """Start Docker PostgreSQL container for testing."""
    try:
        # Check if container is already running
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=backend-postgres-test-1", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True
        )

        if "backend-postgres-test-1" in result.stdout:
            print("Test database container already running")
            return

        # Start the container
        subprocess.run(
            ["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d"],
            cwd=os.path.dirname(os.path.dirname(__file__)),  # backend directory
            check=True
        )

        # Wait for database to be ready
        max_retries = 30
        for _i in range(max_retries):
            try:
                result = subprocess.run(
                    ["docker", "exec", "backend-postgres-test-1", "pg_isready", "-U", "postgres"],
                    capture_output=True,
                    check=True
                )
                if result.returncode == 0:
                    print("Test database is ready")
                    time.sleep(2)  # Give it a bit more time
                    return
            except subprocess.CalledProcessError:
                pass

            time.sleep(1)

        raise RuntimeError("Test database failed to start within timeout")

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to start test database: {e}") from e


def stop_test_database():
    """Stop Docker PostgreSQL container."""
    try:
        subprocess.run(
            ["docker", "compose", "-f", "docker-compose.test.yml", "down", "-v"],
            cwd=os.path.dirname(os.path.dirname(__file__)),  # backend directory
            check=True
        )
        print("Test database stopped")
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to stop test database: {e}")


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Setup and teardown test database for the entire test session."""
    start_test_database()
    yield
    stop_test_database()


@pytest_asyncio.fixture(scope="function")
async def async_engine(setup_test_database) -> AsyncGenerator[AsyncEngine, None]:
    """Create async database engine for testing."""
    engine = create_async_engine(
        ASYNC_TEST_DATABASE_URL,
        echo=False,  # Set to True for SQL debugging
        pool_pre_ping=True,
        pool_recycle=300,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def async_connection(async_engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    """Create async database connection with transaction rollback."""
    async with async_engine.begin() as conn:
        # Drop tables if they exist (in reverse dependency order)
        await conn.execute(text("DROP TABLE IF EXISTS contact_tags CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS contact_notes CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS contact_addresses CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS contact_methods CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS contact_field_history CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS contact_edit_event CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS contacts CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS tags CASCADE"))

        # Create tables
        await conn.execute(text("""
            CREATE TABLE contacts (
                id SERIAL PRIMARY KEY,
                first_name VARCHAR(100) NOT NULL,
                last_name VARCHAR(100),
                middle_name VARCHAR(100),
                nick_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))

        await conn.execute(text("""
            CREATE TABLE contact_methods (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                method_type VARCHAR(50) NOT NULL,
                value VARCHAR(255) NOT NULL,
                label VARCHAR(100),
                is_primary BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))

        await conn.execute(text("""
            CREATE UNIQUE INDEX contact_methods_primary_unique
            ON contact_methods (contact_id, method_type)
            WHERE is_primary = true
        """))

        await conn.execute(text("""
            CREATE UNIQUE INDEX contact_methods_email_unique
            ON contact_methods (value)
            WHERE method_type = 'email'
        """))

        await conn.execute(text("""
            CREATE TABLE contact_addresses (
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
            )
        """))

        await conn.execute(text("""
            CREATE UNIQUE INDEX contact_addresses_primary_unique
            ON contact_addresses (contact_id)
            WHERE is_primary = true
        """))

        await conn.execute(text("""
            CREATE TABLE contact_notes (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))

        await conn.execute(text("""
            CREATE TABLE tags (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                parent_id INTEGER REFERENCES tags(id) ON DELETE SET NULL,
                color VARCHAR(7),
                description TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))

        await conn.execute(text("""
            CREATE TABLE contact_tags (
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY (contact_id, tag_id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE contact_field_history (
                id SERIAL PRIMARY KEY,
                entity_type VARCHAR(50) NOT NULL,
                entity_id INTEGER NOT NULL,
                field_name VARCHAR(100) NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_by VARCHAR(100) DEFAULT 'system',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        await conn.execute(text("""
            CREATE TABLE contact_edit_event (
                id SERIAL PRIMARY KEY,
                event_id VARCHAR(255) NOT NULL UNIQUE,
                event_type VARCHAR(100) NOT NULL,
                aggregate_id INTEGER NOT NULL,
                event_data JSONB NOT NULL,
                occurred_at TIMESTAMP NOT NULL,
                correlation_id VARCHAR(255)
            )
        """))

        # Start a nested transaction for the test
        nested_trans = await conn.begin_nested()
        try:
            yield conn
        finally:
            # Always rollback the nested transaction
            await nested_trans.rollback()


@pytest_asyncio.fixture
async def clean_database(async_connection: AsyncConnection) -> AsyncGenerator[AsyncConnection, None]:
    """Provide a clean database connection for each test."""
    # Since we're using transaction rollback, each test starts with a clean state
    yield async_connection

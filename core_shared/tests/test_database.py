"""
Tests for database utilities.

Tests database URL generation and engine creation without requiring
an actual database connection.
"""

import os
from unittest.mock import patch

from core_shared.database import (
    create_engine_from_env,
    create_engine_from_url,
    get_database_url,
)


class TestGetDatabaseUrl:
    """Test database URL generation."""

    def test_get_database_url_from_env_var(self) -> None:
        """Test getting database URL from DATABASE_URL environment variable."""
        expected_url = "postgresql://user:pass@host:5432/db"

        with patch.dict(os.environ, {"DATABASE_URL": expected_url}):
            url = get_database_url()
            assert url == expected_url

    def test_get_database_url_from_components(self) -> None:
        """Test building database URL from individual components."""
        # Clear DATABASE_URL to force component-based building
        with patch.dict(os.environ, {}, clear=True):
            url = get_database_url(
                host="testhost",
                port=5433,
                database="testdb",
                username="testuser",
                password="testpass",
            )

            expected = "postgresql://testuser:testpass@testhost:5433/testdb"
            assert url == expected

    def test_get_database_url_defaults(self) -> None:
        """Test database URL with default values."""
        # Clear all database environment variables
        with patch.dict(os.environ, {}, clear=True):
            url = get_database_url()
            expected = (
                "postgresql://postgres:postgres@localhost:5432/personal_management"
            )
            assert url == expected

    def test_get_database_url_from_env_components(self) -> None:
        """Test building URL from environment variable components."""
        env_vars = {
            "DATABASE_HOST": "envhost",
            "DATABASE_PORT": "5434",
            "DATABASE_NAME": "envdb",
            "DATABASE_USER": "envuser",
            "DATABASE_PASSWORD": "envpass",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            url = get_database_url()
            expected = "postgresql://envuser:envpass@envhost:5434/envdb"
            assert url == expected


class TestCreateEngineFromUrl:
    """Test engine creation from URL."""

    def test_create_engine_from_url_defaults(self) -> None:
        """Test creating engine with default parameters."""
        url = "postgresql://user:pass@localhost:5432/testdb"
        engine = create_engine_from_url(url)

        assert engine is not None
        # SQLAlchemy masks passwords in URL strings for security
        assert "postgresql://user:" in str(engine.url)
        assert "@localhost:5432/testdb" in str(engine.url)
        # Check pool configuration (using type: ignore for mypy)
        assert engine.pool.size() == 5  # type: ignore[attr-defined]
        assert engine.pool._max_overflow == 10  # type: ignore[attr-defined]

    def test_create_engine_from_url_custom_params(self) -> None:
        """Test creating engine with custom parameters."""
        url = "postgresql://user:pass@localhost:5432/testdb"
        engine = create_engine_from_url(
            url,
            pool_size=10,
            max_overflow=20,
            pool_timeout=60,
            pool_recycle=7200,
            echo=True,
        )

        assert engine is not None
        # SQLAlchemy masks passwords in URL strings for security
        assert "postgresql://user:" in str(engine.url)
        assert "@localhost:5432/testdb" in str(engine.url)
        # Check pool configuration (using type: ignore for mypy)
        assert engine.pool.size() == 10  # type: ignore[attr-defined]
        assert engine.pool._max_overflow == 20  # type: ignore[attr-defined]
        assert engine.echo is True


class TestCreateEngineFromEnv:
    """Test engine creation from environment."""

    def test_create_engine_from_env_defaults(self) -> None:
        """Test creating engine from environment with defaults."""
        env_vars = {"DATABASE_URL": "postgresql://user:pass@localhost:5432/testdb"}

        with patch.dict(os.environ, env_vars, clear=True):
            engine = create_engine_from_env()

            assert engine is not None
            # SQLAlchemy masks passwords in URL strings for security
            assert "postgresql://user:" in str(engine.url)
            assert "@localhost:5432/testdb" in str(engine.url)
            assert engine.pool.size() == 5  # type: ignore[attr-defined]

    def test_create_engine_from_env_debug_echo(self) -> None:
        """Test that DEBUG environment variable controls echo."""
        env_vars = {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/testdb",
            "DEBUG": "true",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            engine = create_engine_from_env()
            assert engine.echo is True

        env_vars["DEBUG"] = "false"
        with patch.dict(os.environ, env_vars, clear=True):
            engine = create_engine_from_env()
            assert engine.echo is False

    def test_create_engine_from_env_custom_params(self) -> None:
        """Test creating engine from environment with custom parameters."""
        env_vars = {"DATABASE_URL": "postgresql://user:pass@localhost:5432/testdb"}

        with patch.dict(os.environ, env_vars, clear=True):
            engine = create_engine_from_env(pool_size=15, max_overflow=25, echo=True)

            assert engine is not None
            assert engine.pool.size() == 15  # type: ignore[attr-defined]
            assert engine.pool._max_overflow == 25  # type: ignore[attr-defined]
            assert engine.echo is True

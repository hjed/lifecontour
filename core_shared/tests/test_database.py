"""
Tests for database utilities.

Tests async engine and session factory creation without requiring
an actual database connection.
"""

from core_shared.database.engine import (
    create_async_engine_from_url,
    create_session_factory,
)


class TestCreateAsyncEngineFromUrl:
    """Test async engine creation from URL."""

    def test_create_async_engine_from_url_basic(self) -> None:
        """Test creating async engine from basic URL."""
        url = "postgresql://user:pass@localhost:5432/testdb"
        engine = create_async_engine_from_url(url)

        # Verify engine properties
        assert engine is not None
        assert "asyncpg" in str(engine.url)
        assert engine.url.username == "user"
        assert engine.url.password == "pass"
        assert engine.url.host == "localhost"
        assert engine.url.port == 5432
        assert engine.url.database == "testdb"

    def test_create_async_engine_from_url_with_options(self) -> None:
        """Test creating async engine with custom options."""
        url = "postgresql://user:pass@localhost:5432/testdb"
        engine = create_async_engine_from_url(
            url,
            pool_size=10,
            max_overflow=20,
            pool_timeout=60,
            pool_recycle=7200,
            echo=True,
        )

        # Verify pool configuration
        assert engine is not None
        assert engine.pool.size() == 10  # type: ignore[attr-defined]
        assert engine.pool._max_overflow == 20  # type: ignore[attr-defined]
        assert engine.pool._timeout == 60  # type: ignore[attr-defined]
        assert engine.pool._recycle == 7200
        assert engine.echo is True

    def test_create_async_engine_from_url_already_async(self) -> None:
        """Test creating async engine with already async URL."""
        url = "postgresql+asyncpg://user:pass@localhost:5432/testdb"
        engine = create_async_engine_from_url(url)

        assert engine is not None
        assert "asyncpg" in str(engine.url)
        assert engine.url.username == "user"
        assert engine.url.password == "pass"
        assert engine.url.host == "localhost"
        assert engine.url.port == 5432
        assert engine.url.database == "testdb"


class TestCreateSessionFactory:
    """Test session factory creation."""

    def test_create_session_factory_basic(self) -> None:
        """Test creating session factory from basic URL."""
        url = "postgresql://user:pass@localhost:5432/testdb"
        session_factory = create_session_factory(url)

        # Verify session factory properties
        assert session_factory is not None
        assert hasattr(session_factory, "bind")
        assert "asyncpg" in str(session_factory.bind.url)

    def test_create_session_factory_converts_sync_url(self) -> None:
        """Test that session factory converts sync URL to async."""
        url = "postgresql://user:pass@localhost:5432/testdb"
        session_factory = create_session_factory(url)

        # Should convert to asyncpg
        assert "asyncpg" in str(session_factory.bind.url)  # type: ignore[attr-defined]

    def test_create_session_factory_preserves_async_url(self) -> None:
        """Test that session factory preserves async URL."""
        url = "postgresql+asyncpg://user:pass@localhost:5432/testdb"
        session_factory = create_session_factory(url)

        # Should keep asyncpg
        assert "asyncpg" in str(session_factory.bind.url)  # type: ignore[attr-defined]

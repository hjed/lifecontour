"""Shared test fixtures for event consumer tests.

Provides reusable mock engine, connection, and search indexer
fixtures to reduce duplication across consumer test modules.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.stream_client import StreamClient


@pytest.fixture
def mock_stream_client() -> MagicMock:
    """Create a mock StreamClient."""
    return MagicMock(spec=StreamClient)


@pytest.fixture
def mock_db_connection() -> AsyncMock:
    """Create a mock async database connection.

    ``info`` is a real dict so the connection works with ``unit_of_work``,
    which tracks unit-of-work nesting depth on ``connection.info``.
    """
    conn = AsyncMock()
    conn.info = {}
    return conn


@pytest.fixture
def mock_db_engine(mock_db_connection: AsyncMock) -> MagicMock:
    """Create a mock async database engine whose ``begin()`` and ``connect()``
    context managers both yield ``mock_db_connection``.

    Mirrors both consumer patterns: ``async with engine.begin() as conn:`` and
    the inbound consumer's ``async with engine.connect() as conn, unit_of_work(conn):``.
    """
    engine = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db_connection)
    ctx.__aexit__ = AsyncMock(return_value=None)
    engine.begin = MagicMock(return_value=ctx)
    engine.connect = MagicMock(return_value=ctx)
    return engine


@pytest.fixture
def mock_search_indexer() -> MagicMock:
    """Create a mock SearchIndexer with an async ``process_event``."""
    indexer = MagicMock()
    indexer.process_event = AsyncMock()
    return indexer

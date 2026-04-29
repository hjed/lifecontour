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
    """Create a mock async database connection."""
    return AsyncMock()


@pytest.fixture
def mock_db_engine(mock_db_connection: AsyncMock) -> MagicMock:
    """Create a mock async database engine whose ``begin()`` context manager
    yields ``mock_db_connection``.

    This mirrors the ``async with engine.begin() as conn:`` pattern
    used in consumers.
    """
    engine = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db_connection)
    ctx.__aexit__ = AsyncMock(return_value=None)
    engine.begin = MagicMock(return_value=ctx)
    return engine


@pytest.fixture
def mock_search_indexer() -> MagicMock:
    """Create a mock SearchIndexer with an async ``process_event``."""
    indexer = MagicMock()
    indexer.process_event = AsyncMock()
    return indexer

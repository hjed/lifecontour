"""
Conftest for integration unit tests.

Provides fixtures for testing integration services without
importing the full FastAPI application.
"""

import pytest


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    from unittest.mock import MagicMock

    settings = MagicMock()
    settings.redis_url = "redis://localhost:6379"
    settings.redis_database = 0
    return settings

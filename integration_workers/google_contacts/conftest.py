"""
Pytest configuration for Google Contacts worker tests.

Sets up environment variables and fixtures needed for testing.
"""

import os
import pytest


# Set up environment variables before any imports
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables."""
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    os.environ.setdefault("GOOGLE_CLIENT_ID", "test_client_id")
    os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test_client_secret")
    os.environ.setdefault("ENCRYPTION_KEY", "test_encryption_key_32_characters!")
    os.environ.setdefault("WORKER_ID", "test-worker")
    os.environ.setdefault("LOG_LEVEL", "INFO")


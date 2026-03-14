"""
Pytest configuration for Google Contacts worker tests.

Sets up environment variables and fixtures needed for testing.
"""

import os

# Set up environment variables immediately during import to allow safe module collection
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test_client_id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("ENCRYPTION_KEY", "test_encryption_key_32_characters!")
os.environ.setdefault("WORKER_ID", "test-worker")
os.environ.setdefault("LOG_LEVEL", "INFO")

from typing import Any

import pytest


@pytest.fixture
def valid_person_data() -> dict[str, Any]:
    """Provide a valid person data dictionary from Google Contacts."""
    return {
        "resourceName": "people/c1",
        "etag": "etag1",
        "names": [{"givenName": "John", "familyName": "Doe"}],
        "emailAddresses": [{"value": "john.doe@example.com"}],
        "phoneNumbers": [{"value": "+1234567890"}],
        "photos": [{"url": "http://example.com/photo.jpg"}],
        "birthdays": [{"date": {"year": 1990, "month": 1, "day": 1}}],
        "addresses": [
            {
                "formattedValue": "123 Main St, Anytown, USA",
                "streetAddress": "123 Main St",
                "city": "Anytown",
                "country": "USA",
            }
        ],
        "organizations": [{"name": "Example Corp", "title": "Software Engineer"}],
        "userDefined": [{"key": "custom_field", "value": "custom_value"}],
    }

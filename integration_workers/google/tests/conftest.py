"""
Pytest configuration for Google Contacts worker tests.

Sets up environment variables and fixtures needed for testing.
"""

import json
import os
import subprocess
from pathlib import Path


def _get_workspace_ports() -> dict[str, str]:
    """Load workspace-specific ports from workspace_env.py for test isolation."""
    project_root = Path(__file__).parent.parent.parent.parent
    script = project_root / "scripts" / "workspace_env.py"
    try:
        result = subprocess.run(
            ["python3", str(script), "json"], check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)
    except Exception as e:
        raise RuntimeError(f"Failed to load workspace environment from {script}: {e}")


_ws = _get_workspace_ports()

# Set up environment variables immediately during import to allow safe module collection.
# Uses workspace-derived ports to avoid conflicts with other workspaces.
_db_port = _ws.get("DB_TEST_PORT", "5433")
_redis_port = _ws.get("REDIS_TEST_PORT", "6380")
os.environ.setdefault(
    "DATABASE_URL",
    f"postgresql+asyncpg://postgres:postgres@localhost:{_db_port}/personal_management_test",
)
os.environ.setdefault("REDIS_URL", f"redis://localhost:{_redis_port}")
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

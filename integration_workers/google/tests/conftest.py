"""
Pytest configuration for Google Contacts worker tests.

Sets up environment variables and fixtures needed for testing.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import cast


def _get_workspace_ports() -> dict[str, str]:
    """Load workspace-specific ports from workspace_env.py for test isolation."""
    project_root = Path(__file__).parent.parent.parent.parent
    script = project_root / "scripts" / "workspace_env.py"
    try:
        result = subprocess.run(
            ["python3", str(script), "json"], check=True, capture_output=True, text=True
        )
        return cast(dict[str, str], json.loads(result.stdout))
    except Exception as e:
        raise RuntimeError(
            f"Failed to load workspace environment from {script}: {e}"
        ) from e


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

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

# Register the shared worker unit-test fixtures (mock_redis, worker_settings,
# session_factory_mock, arq_ctx). pytest_plugins is only honoured in the
# top-level conftest, which is why it lives here.
pytest_plugins = ["core_shared.testing"]


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


# ── Google API error fixtures ───────────────────────────────────────────

# The body Google returns when a push targets an event whose type forbids the
# change. A contact-linked birthday accepts only colorId, summary and
# reminders, and rejects description, location and dates outright:
# https://developers.google.com/workspace/calendar/api/guides/event-types
_EVENT_TYPE_RESTRICTION_MESSAGE = (
    "Attempt made to modify 'birthday' event in a way that is not valid for "
    "this event type."
)


@pytest.fixture
def google_http_error() -> Callable[[int, bytes], HttpError]:
    """Build an ``HttpError`` the way googleapiclient raises one.

    The real class rather than a stand-in, because the code under test
    classifies these errors by their rendered form — a mock would assert
    nothing about whether that rendering carries the reason code.
    """

    def _build(status: int, content: bytes) -> HttpError:
        resp = MagicMock()
        resp.status = status
        resp.reason = "Bad Request" if status == 400 else "Error"
        return HttpError(
            resp=resp,
            content=content,
            uri="https://www.googleapis.com/calendar/v3/calendars/cal/events/evt",
        )

    return _build


@pytest.fixture
def event_type_restriction_content() -> bytes:
    """The 400 body Google returns for a write an event's type forbids."""
    return json.dumps(
        {
            "error": {
                "code": 400,
                "message": _EVENT_TYPE_RESTRICTION_MESSAGE,
                "errors": [
                    {
                        "domain": "calendar",
                        "reason": "eventTypeRestriction",
                        "message": _EVENT_TYPE_RESTRICTION_MESSAGE,
                        "extendedHelp": (
                            "https://developers.google.com/workspace/calendar/"
                            "api/guides/event-types#birthday"
                        ),
                    }
                ],
            }
        }
    ).encode()


@pytest.fixture
def event_type_restriction_error(
    google_http_error: Callable[[int, bytes], HttpError],
    event_type_restriction_content: bytes,
) -> HttpError:
    """The rejection a push to a Google birthday event comes back with."""
    return google_http_error(400, event_type_restriction_content)

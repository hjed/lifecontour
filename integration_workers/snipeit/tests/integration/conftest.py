"""Pytest configuration for Snipe-IT worker integration tests.

The database session fixtures and migrations are shared across every worker and
live in ``core_shared.testing.integration``. They are imported here (not
registered via ``pytest_plugins``) so the autouse ``apply_migrations`` stays
scoped to this integration subtree. The Snipe-IT-specific HTTP fixtures
(``MockTransport`` and friends) remain below.
"""

import json as _json
import os
from typing import Any

import httpx
import pytest
import pytest_asyncio
from core_shared.testing.integration import (
    apply_migrations,
    async_connection,
    async_engine,
    db_session,
    get_async_database_url,
)

# Set required environment variables for worker settings before imports happen.
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = get_async_database_url()
if "ENCRYPTION_KEY" not in os.environ:
    os.environ["ENCRYPTION_KEY"] = "testkey"

__all__ = ["apply_migrations", "async_connection", "async_engine", "db_session"]


class MockTransport(httpx.AsyncBaseTransport):
    """In-memory httpx transport that serves queued responses by URL substring.

    Shared by the checkout/checkin outbound-sync integration tests to drive the
    Snipe-IT API client without a live server. An activity report request with
    no queued response gets an empty report, since every checkout first looks
    for an existing Snipe-IT checkout to link.

    A response queued with a ``method`` only answers that HTTP method, so a
    ``GET /hardware/42`` cannot be served to ``POST /hardware/42/checkin``.
    """

    def __init__(self) -> None:
        self.responses: list[tuple[str, str | None, int, object, dict[str, str]]] = []
        self.requests: list[httpx.Request] = []

    def add_response(
        self,
        url_pattern: str,
        status_code: int = 200,
        json_data: object = None,
        headers: dict[str, str] | None = None,
        method: str | None = None,
    ) -> None:
        self.responses.append(
            (url_pattern, method, status_code, json_data, headers or {})
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        for i, (pattern, method, status, data, hdrs) in enumerate(self.responses):
            if pattern in url and method in (None, request.method):
                self.responses.pop(i)
                # Bytes are served verbatim, e.g. to simulate a non-JSON body.
                if isinstance(data, bytes):
                    content = data
                else:
                    content = _json.dumps(data).encode() if data is not None else b""
                return httpx.Response(
                    status_code=status,
                    content=content,
                    headers={**hdrs, "content-type": "application/json"},
                    request=request,
                )
        if "reports/activity" in url:
            return httpx.Response(
                status_code=200,
                json={"total": 0, "rows": []},
                request=request,
            )
        raise ValueError(f"No mock response configured for {url}")


@pytest.fixture
def mock_transport() -> MockTransport:
    return MockTransport()


@pytest_asyncio.fixture
async def integration_client(mock_transport: MockTransport) -> Any:
    """Snipe-IT API client wired to the in-memory ``mock_transport``."""
    from snipeit_api_client import SnipeItAPIClient

    client = SnipeItAPIClient.create(
        base_url="https://snipeit.example.com/api/v1/",
        api_key="test-api-key",
    )
    client._client = httpx.AsyncClient(
        transport=mock_transport,
        base_url="https://snipeit.example.com/api/v1/",
        headers={"Authorization": "Bearer test-api-key"},
    )
    yield client
    await client._client.aclose()


@pytest.fixture
def snipeit_sync_service(integration_client: Any) -> Any:
    """A ``SnipeItSyncService`` for outbound sync tests (user mapped to id 5)."""
    from snipeit_sync_service import SnipeItSyncService

    return SnipeItSyncService(
        api_client=integration_client,
        user_id="user-123",
        snipeit_user_id="5",
    )

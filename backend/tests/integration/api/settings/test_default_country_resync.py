"""Changing the default country re-imports the user's Google contacts (#1820).

The default fills in Google addresses that have no country. A contact whose
etag has not moved is never re-pulled, so a new default would only reach a
contact the next time it changed in Google; a full sync applies it to every
contact at once.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.exceptions import JobEnqueueError

pytestmark = pytest.mark.integration

_ENQUEUE = (
    "app.core.integrations.task_queue_service.TaskQueueService.enqueue_google_sync"
)


@pytest.fixture
def enqueue() -> Iterator[AsyncMock]:
    with patch(_ENQUEUE, new_callable=AsyncMock, return_value="job-1") as mock:
        yield mock


async def _connect_google(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO user_google_auth (
                user_id, google_account_email, encrypted_access_token,
                encrypted_refresh_token, expires_at, created_at, updated_at
            ) VALUES ('test-user-123', 'me@example.com', 'x', 'y',
                      now(), now(), now())
            """
        )
    )


async def test_a_new_default_country_queues_a_full_contacts_sync(
    authenticated_client: AsyncClient,
    clean_database: AsyncConnection,
    enqueue: AsyncMock,
) -> None:
    await _connect_google(clean_database)

    response = await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "NZ"}
    )

    assert response.status_code == 200
    enqueue.assert_awaited_once_with(
        google_account_email="me@example.com",
        user_id="test-user-123",
        sync_type="full",
    )


@pytest.mark.parametrize(
    "second",
    [{"default_country": "NZ"}, {"timezone": "Pacific/Auckland"}],
    ids=["unchanged-country", "timezone-only"],
)
async def test_a_save_that_does_not_change_the_country_queues_nothing(
    authenticated_client: AsyncClient,
    clean_database: AsyncConnection,
    enqueue: AsyncMock,
    second: dict[str, str],
) -> None:
    await _connect_google(clean_database)
    await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "NZ"}
    )
    enqueue.reset_mock()

    response = await authenticated_client.patch("/api/user-settings", json=second)

    assert response.status_code == 200
    enqueue.assert_not_awaited()


async def test_without_google_nothing_is_queued(
    authenticated_client: AsyncClient,
    clean_database: AsyncConnection,
    enqueue: AsyncMock,
) -> None:
    response = await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "NZ"}
    )

    assert response.status_code == 200
    enqueue.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [JobEnqueueError("queue down"), ConnectionError("redis down")],
    ids=["enqueue-error", "connection-error"],
)
async def test_a_failed_enqueue_still_saves_the_country(
    authenticated_client: AsyncClient,
    clean_database: AsyncConnection,
    enqueue: AsyncMock,
    failure: Exception,
) -> None:
    """The resync is best-effort: the next periodic sync still picks it up."""
    await _connect_google(clean_database)
    enqueue.side_effect = failure

    response = await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "NZ"}
    )

    assert response.status_code == 200
    get_response = await authenticated_client.get("/api/user-settings")
    assert get_response.json()["data"]["attributes"]["default_country"] == "NZ"

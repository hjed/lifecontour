"""Saving the default country re-imports the user's Google contacts (#1820).

The default fills in Google addresses that have no country. A contact whose
etag has not moved is never re-pulled, so a new default would only reach a
contact the next time it changed in Google. Saving it therefore clears the
contacts sync token in the same transaction - the next sync is a full one,
which re-applies every person - and queues that sync now, best-effort.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
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
    await connection.execute(
        text(
            """
            INSERT INTO user_google_integration
                (user_id, google_account_email, contacts_sync_token,
                 created_at, updated_at)
            VALUES ('test-user-123', 'me@example.com', 'token-1', now(), now())
            """
        )
    )


async def _sync_token(connection: AsyncConnection) -> str | None:
    result = await connection.execute(
        text(
            "SELECT contacts_sync_token FROM user_google_integration "
            "WHERE user_id = 'test-user-123'"
        )
    )
    token = result.scalar_one()
    return str(token) if token is not None else None


@pytest.mark.parametrize("country", ["NZ", None], ids=["set", "cleared"])
async def test_saving_the_default_country_forces_a_full_contacts_sync(
    authenticated_client: AsyncClient,
    clean_database: AsyncConnection,
    enqueue: AsyncMock,
    country: str | None,
) -> None:
    await _connect_google(clean_database)

    response = await authenticated_client.patch(
        "/api/user-settings", json={"default_country": country}
    )

    assert response.status_code == 200
    assert await _sync_token(clean_database) is None
    enqueue.assert_awaited_once_with(
        google_account_email="me@example.com",
        user_id="test-user-123",
        sync_type="smart",
    )


async def test_re_saving_the_same_country_forces_it_again(
    authenticated_client: AsyncClient,
    clean_database: AsyncConnection,
    enqueue: AsyncMock,
) -> None:
    """A save is the recovery for a sync that never ran, so it never no-ops."""
    await _connect_google(clean_database)
    await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "NZ"}
    )
    await clean_database.execute(
        text("UPDATE user_google_integration SET contacts_sync_token = 'token-2'")
    )
    enqueue.reset_mock()

    await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "NZ"}
    )

    assert await _sync_token(clean_database) is None
    enqueue.assert_awaited_once()


async def test_a_timezone_save_leaves_the_contacts_sync_alone(
    authenticated_client: AsyncClient,
    clean_database: AsyncConnection,
    enqueue: AsyncMock,
) -> None:
    await _connect_google(clean_database)

    response = await authenticated_client.patch(
        "/api/user-settings", json={"timezone": "Pacific/Auckland"}
    )

    assert response.status_code == 200
    assert await _sync_token(clean_database) == "token-1"
    enqueue.assert_not_awaited()


async def test_without_google_nothing_is_queued(
    authenticated_client: AsyncClient,
    enqueue: AsyncMock,
) -> None:
    response = await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "NZ"}
    )

    assert response.status_code == 200
    enqueue.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [JobEnqueueError("queue down"), RedisConnectionError("redis down")],
    ids=["enqueue-error", "redis-connection-error"],
)
async def test_a_failed_enqueue_still_saves_and_forces_the_next_sync(
    authenticated_client: AsyncClient,
    clean_database: AsyncConnection,
    enqueue: AsyncMock,
    failure: Exception,
) -> None:
    """The cleared token makes whichever sync runs next a full one."""
    await _connect_google(clean_database)
    enqueue.side_effect = failure

    response = await authenticated_client.patch(
        "/api/user-settings", json={"default_country": "NZ"}
    )

    assert response.status_code == 200
    assert await _sync_token(clean_database) is None
    get_response = await authenticated_client.get("/api/user-settings")
    assert get_response.json()["data"]["attributes"]["default_country"] == "NZ"


async def test_a_task_queue_that_cannot_start_still_saves(
    authenticated_client: AsyncClient,
    clean_database: AsyncConnection,
) -> None:
    """Redis down when the queue is first built must not fail the save."""
    await _connect_google(clean_database)

    with patch(
        "app.api.settings.controllers._task_queue_service",
        new_callable=AsyncMock,
        side_effect=RedisConnectionError("redis down"),
    ):
        response = await authenticated_client.patch(
            "/api/user-settings", json={"default_country": "NZ"}
        )

    assert response.status_code == 200
    assert await _sync_token(clean_database) is None

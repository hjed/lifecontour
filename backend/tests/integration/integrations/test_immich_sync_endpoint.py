"""
Integration tests for Immich sync trigger endpoint.

Tests the POST /api/integrations/immich/sync endpoint with a real database,
validating SyncJob persistence and connection-state checking.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest.mark.asyncio
async def test_trigger_immich_sync_creates_sync_job(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    """Manual sync trigger should enqueue a job."""
    # Setup: insert Immich auth credentials for the test user
    await clean_database.execute(
        text(
            "INSERT INTO user_immich_auth "
            "(user_id, server_url, encrypted_api_key, created_at, updated_at) "
            "VALUES ('test-user-123', 'https://immich.example.com', "
            "'encrypted_key_data', now(), now())"
        )
    )

    with patch(
        "app.core.integrations.task_queue_service.TaskQueueService.enqueue_immich_sync",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        mock_enqueue.return_value = "test-immich-job-123"

        # Also mock get_sync_job_details for the response
        with patch(
            "app.core.integrations.task_queue_service.TaskQueueService.get_sync_job_details",
            new_callable=AsyncMock,
        ) as mock_details:
            mock_details.return_value = {
                "job_id": "test-immich-job-123",
                "user_id": "test-user-123",
                "integration_source": "immich",
                "sync_type": "smart",
                "status": "queued",
                "created_at": "2026-01-01T00:00:00",
                "started_at": None,
                "completed_at": None,
                "error_message": None,
                "contacts_processed": None,
                "contacts_created": None,
                "contacts_updated": None,
                "contacts_deleted": None,
                "progress": None,
            }

            response = await authenticated_client.post(
                "/api/integrations/immich/sync",
                json={"sync_type": "smart"},
            )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == "test-immich-job-123"
    assert data["type"] == "sync-job"
    assert data["attributes"]["status"] == "queued"
    assert data["attributes"]["syncType"] == "smart"

    mock_enqueue.assert_awaited_once_with(
        user_id="test-user-123",
        sync_type="smart",
    )


@pytest.mark.asyncio
async def test_trigger_immich_sync_not_connected(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    """Sync trigger should return 400 when Immich is not connected."""
    # No Immich auth record → not connected
    response = await authenticated_client.post(
        "/api/integrations/immich/sync",
        json={"sync_type": "smart"},
    )

    assert response.status_code == 400
    body = response.json()
    assert "errors" in body
    error_detail = body["errors"][0].get("detail", "")
    assert "not connected" in error_detail.lower()


@pytest.mark.asyncio
async def test_trigger_immich_sync_force_full(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    """force_full_sync=True should override sync_type to 'full'."""
    await clean_database.execute(
        text(
            "INSERT INTO user_immich_auth "
            "(user_id, server_url, encrypted_api_key, created_at, updated_at) "
            "VALUES ('test-user-123', 'https://immich.example.com', "
            "'encrypted_key_data', now(), now())"
        )
    )

    with patch(
        "app.core.integrations.task_queue_service.TaskQueueService.enqueue_immich_sync",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        mock_enqueue.return_value = "test-immich-job-456"

        with patch(
            "app.core.integrations.task_queue_service.TaskQueueService.get_sync_job_details",
            new_callable=AsyncMock,
        ) as mock_details:
            mock_details.return_value = {
                "job_id": "test-immich-job-456",
                "user_id": "test-user-123",
                "integration_source": "immich",
                "sync_type": "full",
                "status": "queued",
                "created_at": "2026-01-01T00:00:00",
                "started_at": None,
                "completed_at": None,
                "error_message": None,
                "contacts_processed": None,
                "contacts_created": None,
                "contacts_updated": None,
                "contacts_deleted": None,
                "progress": None,
            }

            response = await authenticated_client.post(
                "/api/integrations/immich/sync",
                json={"sync_type": "smart", "force_full_sync": True},
            )

    assert response.status_code == 200
    mock_enqueue.assert_awaited_once_with(
        user_id="test-user-123",
        sync_type="full",
    )


@pytest.mark.asyncio
async def test_trigger_immich_sync_connection_error(
    authenticated_client,
    clean_database: AsyncConnection,
) -> None:
    """Sync trigger should return 503 when task queue is unavailable."""
    await clean_database.execute(
        text(
            "INSERT INTO user_immich_auth "
            "(user_id, server_url, encrypted_api_key, created_at, updated_at) "
            "VALUES ('test-user-123', 'https://immich.example.com', "
            "'encrypted_key_data', now(), now())"
        )
    )

    with patch(
        "app.core.integrations.task_queue_service.TaskQueueService.enqueue_immich_sync",
        new_callable=AsyncMock,
        side_effect=ConnectionError("Redis connection lost"),
    ):
        response = await authenticated_client.post(
            "/api/integrations/immich/sync",
            json={"sync_type": "smart"},
        )

    assert response.status_code == 503
    body = response.json()
    assert "errors" in body
    error_detail = body["errors"][0].get("detail", "")
    assert "unavailable" in error_detail.lower()

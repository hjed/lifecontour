import pytest
from httpx import AsyncClient

from app.infrastructure.config import Settings

pytestmark = pytest.mark.integration

WEBHOOK_BASE_URL = "https://pms.example.com"


@pytest.fixture
def test_settings(test_settings: Settings) -> Settings:
    """The shared test settings, with a public base URL for webhook URLs."""
    test_settings.webhook_base_url = WEBHOOK_BASE_URL
    return test_settings


async def _save_settings(client: AsyncClient) -> None:
    response = await client.put(
        "/api/integrations/snipeit/settings",
        json={"base_url": "https://snipeit.example.com"},
    )
    assert response.status_code == 200


async def _webhook_url(client: AsyncClient) -> str:
    response = await client.get("/api/integrations/snipeit/webhook-url")
    assert response.status_code == 200
    return str(response.json()["data"]["attributes"]["webhook_url"])


async def test_webhook_url_contains_the_users_token(
    authenticated_client: AsyncClient,
) -> None:
    """The webhook URL carries a token that the webhook endpoint accepts."""
    await _save_settings(authenticated_client)

    webhook_url = await _webhook_url(authenticated_client)
    prefix = f"{WEBHOOK_BASE_URL}/api/integrations/snipeit/webhook/"
    assert webhook_url.startswith(prefix)
    token = webhook_url.removeprefix(prefix)
    assert len(token) == 43

    webhook = await authenticated_client.post(
        webhook_url.removeprefix(WEBHOOK_BASE_URL),
        json={"text": "Oh hai! It looks like your webhook is working!"},
    )
    assert webhook.status_code == 200


async def test_webhook_url_not_found_without_settings(
    authenticated_client: AsyncClient,
) -> None:
    """Without Snipe-IT settings there is no token, so no webhook URL."""
    response = await authenticated_client.get("/api/integrations/snipeit/webhook-url")

    assert response.status_code == 404
    assert response.json()["errors"][0]["detail"] == (
        "No Snipe-IT settings found for this user"
    )


async def test_get_snipeit_settings_not_found(authenticated_client: AsyncClient):
    """Test GET settings returns 404 when not configured."""
    response = await authenticated_client.get("/api/integrations/snipeit/settings")

    assert response.status_code == 404
    data = response.json()
    assert "errors" in data
    assert data["errors"][0]["detail"] == "No Snipe-IT settings found for this user"


async def test_upsert_and_get_snipeit_settings(authenticated_client: AsyncClient):
    """Test PUT saves settings and GET retrieves them in JSON API format."""
    # Put settings
    put_payload = {
        "base_url": "https://snipeit.example.com",
        "snipeit_user_id": "42",
    }
    put_response = await authenticated_client.put(
        "/api/integrations/snipeit/settings",
        json=put_payload,
    )

    assert put_response.status_code == 200
    put_data = put_response.json()
    assert "data" in put_data
    assert put_data["data"]["type"] == "snipeit_settings"
    assert "id" in put_data["data"]
    attributes = put_data["data"]["attributes"]
    assert attributes["base_url"] == "https://snipeit.example.com/"
    assert attributes["snipeit_user_id"] == "42"

    # Get settings to verify
    get_response = await authenticated_client.get("/api/integrations/snipeit/settings")

    assert get_response.status_code == 200
    get_data = get_response.json()
    get_attributes = get_data["data"]["attributes"]
    assert get_attributes["base_url"] == "https://snipeit.example.com/"
    assert get_attributes["snipeit_user_id"] == "42"


async def test_trigger_gear_sync(authenticated_client: AsyncClient):
    """Test Snipe-IT gear sync endpoint."""
    from unittest.mock import AsyncMock, patch

    with (
        patch(
            "app.core.integrations.task_queue_service.TaskQueueService.enqueue_snipeit_sync",
            new_callable=AsyncMock,
            return_value="job_123",
        ),
        patch(
            "app.core.integrations.task_queue_service.TaskQueueService.get_sync_job_details",
            new_callable=AsyncMock,
            return_value={
                "job_id": "job_123",
                "status": "queued",
                "sync_type": "smart",
                "created_at": "2023-01-01T00:00:00Z",
                "started_at": "2023-01-01T00:00:00Z",
                "completed_at": "2023-01-01T00:00:00Z",
                "error_message": None,
                "contacts_processed": 0,
                "contacts_created": 0,
                "contacts_updated": 0,
                "contacts_deleted": 0,
                "progress": None,
            },
        ),
    ):
        response = await authenticated_client.post(
            "/api/integrations/snipeit/gear/sync",
            json={"sync_type": "smart", "force_full_sync": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["id"] == "job_123"

    # Test force_full_sync=True coerces sync_type to full
    with (
        patch(
            "app.core.integrations.task_queue_service.TaskQueueService.enqueue_snipeit_sync",
            new_callable=AsyncMock,
            return_value="job_123_full",
        ) as mock_enqueue,
        patch(
            "app.core.integrations.task_queue_service.TaskQueueService.get_sync_job_details",
            new_callable=AsyncMock,
            return_value={
                "job_id": "job_123_full",
                "status": "queued",
                "sync_type": "full",
                "created_at": "2023-01-01T00:00:00Z",
                "started_at": "2023-01-01T00:00:00Z",
                "completed_at": "2023-01-01T00:00:00Z",
                "error_message": None,
                "contacts_processed": 0,
                "contacts_created": 0,
                "contacts_updated": 0,
                "contacts_deleted": 0,
                "progress": None,
            },
        ),
    ):
        response = await authenticated_client.post(
            "/api/integrations/snipeit/gear/sync",
            json={"sync_type": "smart", "force_full_sync": True},
        )
        assert response.status_code == 200
        # Verify the enqueue was called with full
        mock_enqueue.assert_called_once()
        assert mock_enqueue.call_args[1].get("sync_type") == "full"


async def test_trigger_maintenance_sync(authenticated_client: AsyncClient):
    """Test Snipe-IT maintenance sync endpoint."""
    from unittest.mock import AsyncMock, patch

    with (
        patch(
            "app.core.integrations.task_queue_service.TaskQueueService.enqueue_snipeit_maintenance_sync",
            new_callable=AsyncMock,
            return_value="job_124",
        ),
        patch(
            "app.core.integrations.task_queue_service.TaskQueueService.get_sync_job_details",
            new_callable=AsyncMock,
            return_value={
                "job_id": "job_124",
                "status": "queued",
                "sync_type": "smart",
                "created_at": "2023-01-01T00:00:00Z",
                "started_at": "2023-01-01T00:00:00Z",
                "completed_at": "2023-01-01T00:00:00Z",
                "error_message": None,
                "contacts_processed": 0,
                "contacts_created": 0,
                "contacts_updated": 0,
                "contacts_deleted": 0,
                "progress": None,
            },
        ),
    ):
        response = await authenticated_client.post(
            "/api/integrations/snipeit/maintenance/sync",
            json={"sync_type": "smart", "force_full_sync": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["id"] == "job_124"

    # Test force_full_sync=True coerces sync_type to full
    with (
        patch(
            "app.core.integrations.task_queue_service.TaskQueueService.enqueue_snipeit_maintenance_sync",
            new_callable=AsyncMock,
            return_value="job_124_full",
        ) as mock_enqueue,
        patch(
            "app.core.integrations.task_queue_service.TaskQueueService.get_sync_job_details",
            new_callable=AsyncMock,
            return_value={
                "job_id": "job_124_full",
                "status": "queued",
                "sync_type": "full",
                "created_at": "2023-01-01T00:00:00Z",
                "started_at": "2023-01-01T00:00:00Z",
                "completed_at": "2023-01-01T00:00:00Z",
                "error_message": None,
                "contacts_processed": 0,
                "contacts_created": 0,
                "contacts_updated": 0,
                "contacts_deleted": 0,
                "progress": None,
            },
        ),
    ):
        response = await authenticated_client.post(
            "/api/integrations/snipeit/maintenance/sync",
            json={"sync_type": "smart", "force_full_sync": True},
        )
        assert response.status_code == 200
        # Verify the enqueue was called with full
        mock_enqueue.assert_called_once()
        assert mock_enqueue.call_args[1].get("sync_type") == "full"


async def test_trigger_checkout_sync(authenticated_client: AsyncClient):
    """Test Snipe-IT checkout sync endpoint respects request sync_type."""
    response = await authenticated_client.post(
        "/api/integrations/snipeit/checkout/sync",
        json={"sync_type": "smart", "force_full_sync": False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["id"] == "dummy_checkout_sync"
    assert data["data"]["attributes"]["syncType"] == "smart"


async def test_trigger_checkout_sync_force_full(authenticated_client: AsyncClient):
    """Test Snipe-IT checkout sync endpoint with force_full_sync."""
    response = await authenticated_client.post(
        "/api/integrations/snipeit/checkout/sync",
        json={"sync_type": "smart", "force_full_sync": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["attributes"]["syncType"] == "full"

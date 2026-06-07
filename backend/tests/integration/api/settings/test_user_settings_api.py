import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_get_user_settings_defaults_to_utc(authenticated_client: AsyncClient):
    """GET returns the default timezone (UTC) when none is configured."""
    response = await authenticated_client.get("/api/user-settings")

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["type"] == "user_settings"
    assert data["data"]["attributes"]["timezone"] == "UTC"


async def test_put_and_get_user_settings(authenticated_client: AsyncClient):
    """PUT saves the timezone and GET returns the saved value."""
    put_response = await authenticated_client.put(
        "/api/user-settings",
        json={"timezone": "Australia/Sydney"},
    )

    assert put_response.status_code == 200
    put_data = put_response.json()
    assert put_data["data"]["attributes"]["timezone"] == "Australia/Sydney"

    get_response = await authenticated_client.get("/api/user-settings")
    assert get_response.status_code == 200
    assert get_response.json()["data"]["attributes"]["timezone"] == "Australia/Sydney"


async def test_put_user_settings_upserts(authenticated_client: AsyncClient):
    """A second PUT updates the existing timezone."""
    await authenticated_client.put(
        "/api/user-settings", json={"timezone": "Australia/Sydney"}
    )
    second = await authenticated_client.put(
        "/api/user-settings", json={"timezone": "America/New_York"}
    )

    assert second.status_code == 200
    assert second.json()["data"]["attributes"]["timezone"] == "America/New_York"

    get_response = await authenticated_client.get("/api/user-settings")
    assert get_response.json()["data"]["attributes"]["timezone"] == "America/New_York"


async def test_put_user_settings_rejects_invalid_timezone(
    authenticated_client: AsyncClient,
):
    """PUT rejects an unknown timezone name with a validation error."""
    response = await authenticated_client.put(
        "/api/user-settings", json={"timezone": "Not/A_Zone"}
    )

    assert response.status_code == 400
    assert "errors" in response.json()

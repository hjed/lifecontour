import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_get_user_settings_reports_an_unset_timezone_as_null(
    authenticated_client: AsyncClient,
):
    """GET answers ``null`` when the user has never configured a timezone.

    Substituting the ``UTC`` default here would make "never set" look exactly
    like "deliberately chose UTC", and the frontend cannot tell them apart: it
    would anchor every unconfigured user's date writes at UTC midnight rather
    than falling back to the browser's zone, which is a calendar day out for
    anyone ahead of UTC (issue #1401). The default still applies everywhere the
    backend resolves a zone for itself.
    """
    response = await authenticated_client.get("/api/user-settings")

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["type"] == "user_settings"
    assert data["data"]["attributes"]["timezone"] is None


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

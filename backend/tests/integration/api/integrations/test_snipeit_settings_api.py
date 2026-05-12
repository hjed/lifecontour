import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


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

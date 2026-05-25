"""Integration tests for Immich authentication endpoints."""

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connect_immich_success(
    authenticated_client: AsyncClient,
    async_connection,
    respx_mock,
) -> None:
    """Test successful connection of Immich integration."""
    server_url = "https://immich.example.com"
    api_key = "test_immich_api_key"

    # Mock Immich about endpoint
    respx_mock.get(f"{server_url}/api/server/about").mock(
        return_value=httpx.Response(200, json={"version": "1.100.0"})
    )

    response = await authenticated_client.post(
        "/api/integrations/immich/connect",
        json={"server_url": server_url, "api_key": api_key},
    )

    assert response.status_code == 200

    # Verify db was updated
    result = await async_connection.execute(
        text("SELECT * FROM user_immich_auth WHERE user_id = :user_id"),
        {"user_id": "test-user-123"},
    )
    row = result.fetchone()
    assert row is not None
    assert row.server_url == server_url
    assert row.encrypted_api_key is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connect_immich_invalid_credentials(
    authenticated_client: AsyncClient,
    respx_mock,
) -> None:
    """Test connecting Immich with invalid credentials."""
    server_url = "https://immich.example.com"
    api_key = "invalid_api_key"

    # Mock Immich about endpoint to return unauthorized
    respx_mock.get(f"{server_url}/api/server/about").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )

    response = await authenticated_client.post(
        "/api/integrations/immich/connect",
        json={"server_url": server_url, "api_key": api_key},
    )

    assert response.status_code == 400
    assert "Invalid server URL or API key" in response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disconnect_immich_success(
    authenticated_client: AsyncClient,
    async_connection,
) -> None:
    """Test disconnecting Immich integration."""
    # First insert a row
    await async_connection.execute(
        text(
            """
            INSERT INTO user_immich_auth (user_id, server_url, encrypted_api_key)
            VALUES (:user_id, :url, :key)
            """
        ),
        {
            "user_id": "test-user-123",
            "url": "https://immich.example.com",
            "key": b"encrypted_key",
        },
    )

    response = await authenticated_client.post("/api/integrations/immich/disconnect")

    assert response.status_code == 204

    # Verify db was updated
    result = await async_connection.execute(
        text("SELECT * FROM user_immich_auth WHERE user_id = :user_id"),
        {"user_id": "test-user-123"},
    )
    assert result.fetchone() is None

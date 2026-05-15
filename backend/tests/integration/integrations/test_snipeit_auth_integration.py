"""
Integration tests for Snipe-IT OAuth auth endpoints.

Tests the full stack: controller → DI → token service → database.
Each test uses the authenticated_client fixture which provides
transaction rollback isolation via savepoints.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest.fixture
def test_settings(test_settings):
    """Override test_settings with Snipe-IT OAuth config populated."""
    test_settings.snipeit_client_id = "test-snipeit-client-id"
    test_settings.snipeit_client_secret = "test-snipeit-client-secret"
    test_settings.snipeit_encryption_key = Fernet.generate_key().decode()
    return test_settings


@pytest.mark.asyncio
class TestSnipeItAuthAPI:
    """Integration tests for the Snipe-IT OAuth REST API endpoints."""

    # ------------------------------------------------------------------ #
    # POST /api/integrations/snipeit/oauth/authorize
    # ------------------------------------------------------------------ #

    async def test_authorize_generates_authorization_url_with_correct_params(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        """POST /oauth/authorize returns URL targeting the user's Snipe-IT base_url."""
        # Seed snipeit_settings for the test user
        await async_connection.execute(
            text("""
                INSERT INTO snipeit_settings (user_id, base_url)
                VALUES (:user_id, :base_url)
            """),
            {
                "user_id": "test-user-123",
                "base_url": "https://snipeit.example.com",
            },
        )

        response = await authenticated_client.post(
            "/api/integrations/snipeit/oauth/authorize",
            json={"redirect_url": "/integrations"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "authorization_url" in body
        assert "state" in body
        assert body["authorization_url"].startswith(
            "https://snipeit.example.com/oauth/authorize"
        )
        assert "response_type=code" in body["authorization_url"]
        assert "state=" in body["authorization_url"]
        assert "client_id=test-snipeit-client-id" in body["authorization_url"]

    async def test_authorize_requires_configured_settings(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        """POST /oauth/authorize returns 400 when no snipeit_settings exist."""
        response = await authenticated_client.post(
            "/api/integrations/snipeit/oauth/authorize",
            json={"redirect_url": "/integrations"},
        )

        assert response.status_code == 400
        body = response.json()

        detail = body.get("detail") or body.get("errors", [{}])[0].get("detail", "")
        assert "Base URL" in detail

    # ------------------------------------------------------------------ #
    # POST /api/integrations/snipeit/oauth/callback
    # ------------------------------------------------------------------ #

    async def test_callback_rejects_invalid_state(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        """POST /oauth/callback returns 400 for mismatched CSRF state."""
        response = await authenticated_client.post(
            "/api/integrations/snipeit/oauth/callback",
            json={"code": "test-code", "state": "invalid-state"},
        )

        assert response.status_code == 400
        body = response.json()

        detail = body.get("detail") or body.get("errors", [{}])[0].get("detail", "")
        assert "state" in detail.lower()

    async def test_callback_exchanges_code_and_saves_tokens(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        respx_mock: object,
    ) -> None:
        """POST /oauth/callback exchanges code for tokens and saves them."""
        # 1. Setup Snipe-IT Base URL
        await async_connection.execute(
            text("""
                INSERT INTO snipeit_settings (user_id, base_url)
                VALUES (:user_id, :base_url)
            """),
            {
                "user_id": "test-user-123",
                "base_url": "https://snipeit.example.com",
            },
        )

        # 2. Inject state into session
        response = await authenticated_client.post(
            "/api/integrations/snipeit/oauth/authorize",
            json={"redirect_url": "/integrations"},
        )
        assert response.status_code == 200
        state = response.json()["state"]

        # 3. Mock external Snipe-IT request with respx
        import httpx

        respx_mock.post("https://snipeit.example.com/oauth/token").mock(  # type: ignore[attr-defined]
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "fake-access-token",
                    "refresh_token": "fake-refresh-token",
                    "expires_in": 3600,
                },
            )
        )

        # 4. Trigger callback
        response = await authenticated_client.post(
            "/api/integrations/snipeit/oauth/callback",
            json={"code": "auth-code-123", "state": state},
        )

        # 5. Verify response
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True

        # 6. Verify tokens were saved in database
        check = await async_connection.execute(
            text("SELECT 1 FROM user_snipe_it_auth WHERE user_id = :uid"),
            {"uid": "test-user-123"},
        )
        assert check.fetchone() is not None

    # ------------------------------------------------------------------ #
    # DELETE /api/integrations/snipeit/oauth/disconnect
    # ------------------------------------------------------------------ #

    async def test_disconnect_removes_auth_record(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        """DELETE /oauth/disconnect removes auth row, provider reports DISCONNECTED."""
        # Seed an auth record
        await async_connection.execute(
            text("""
                INSERT INTO user_snipe_it_auth (
                    user_id, encrypted_access_token, encrypted_refresh_token,
                    token_expires_at
                ) VALUES (
                    :user_id, :token, :token,
                    NOW() + INTERVAL '1 hour'
                )
            """),
            {
                "user_id": "test-user-123",
                "token": b"fake-encrypted-token",
            },
        )

        # Verify the record exists
        check = await async_connection.execute(
            text("SELECT 1 FROM user_snipe_it_auth WHERE user_id = :uid"),
            {"uid": "test-user-123"},
        )
        assert check.fetchone() is not None

        # Disconnect
        response = await authenticated_client.delete(
            "/api/integrations/snipeit/oauth/disconnect",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "disconnected" in body["message"].lower()

        # Verify auth record was deleted
        check2 = await async_connection.execute(
            text("SELECT 1 FROM user_snipe_it_auth WHERE user_id = :uid"),
            {"uid": "test-user-123"},
        )
        assert check2.fetchone() is None

    async def test_disconnect_no_connection_succeeds(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        """DELETE /oauth/disconnect when not connected returns success."""
        response = await authenticated_client.delete(
            "/api/integrations/snipeit/oauth/disconnect",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True

    # ------------------------------------------------------------------ #
    # Integration registry status after connect/disconnect
    # ------------------------------------------------------------------ #

    async def test_registry_returns_disconnected_when_no_auth(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        """GET /api/integrations shows snipeit as disconnected when no auth row."""
        response = await authenticated_client.get("/api/integrations")

        assert response.status_code == 200
        body = response.json()
        snipeit = next((d for d in body["data"] if d["id"] == "snipeit"), None)
        assert snipeit is not None
        assert snipeit["attributes"]["status"] == "disconnected"

    async def test_registry_returns_connected_when_auth_exists(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        """GET /api/integrations shows snipeit as connected when auth row exists."""
        # Seed an auth record
        await async_connection.execute(
            text("""
                INSERT INTO user_snipe_it_auth (
                    user_id, encrypted_access_token, encrypted_refresh_token,
                    token_expires_at
                ) VALUES (
                    :user_id, :token, :token,
                    NOW() + INTERVAL '1 hour'
                )
            """),
            {
                "user_id": "test-user-123",
                "token": b"fake-encrypted-token",
            },
        )

        response = await authenticated_client.get("/api/integrations")

        assert response.status_code == 200
        body = response.json()
        snipeit = next((d for d in body["data"] if d["id"] == "snipeit"), None)
        assert snipeit is not None
        assert snipeit["attributes"]["status"] == "connected"

    async def test_registry_returns_token_expired_when_needs_reauth(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        """GET /api/integrations shows snipeit as token_expired when needs_reauth."""
        await async_connection.execute(
            text("""
                INSERT INTO user_snipe_it_auth (
                    user_id, encrypted_access_token, encrypted_refresh_token,
                    token_expires_at, needs_reauth
                ) VALUES (
                    :user_id, :token, :token,
                    NOW() - INTERVAL '1 hour', true
                )
            """),
            {
                "user_id": "test-user-123",
                "token": b"fake-encrypted-token",
            },
        )

        response = await authenticated_client.get("/api/integrations")

        assert response.status_code == 200
        body = response.json()
        snipeit = next((d for d in body["data"] if d["id"] == "snipeit"), None)
        assert snipeit is not None
        assert snipeit["attributes"]["status"] == "token_expired"
        assert snipeit["attributes"]["needs_reauth"] is True

"""
Integration tests for Snipe-IT OAuth auth endpoints.

Tests the full stack: controller → DI → token service → database.
Each test uses the authenticated_client fixture which provides
transaction rollback isolation via savepoints.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.conftest import (
    _authenticated_client_context,
    get_test_database_url,
    workspace_env,
)


@pytest.fixture
def snipeit_test_settings():
    """Test settings with Snipe-IT OAuth config populated."""
    from app.infrastructure.config import Settings

    return Settings(
        debug=True,
        database_url=get_test_database_url(),
        redis_url=os.getenv(
            "REDIS_URL",
            "redis://localhost:" + workspace_env.get("REDIS_TEST_PORT", "6380"),
        ),
        meilisearch_url=os.getenv(
            "MEILISEARCH_URL",
            "http://localhost:" + workspace_env.get("MEILI_TEST_PORT", "7701"),
        ),
        meilisearch_api_key=os.getenv("MEILISEARCH_API_KEY", "test_master_key"),
        allowed_hosts=["*"],
        cors_origins=["*"],
        snipeit_client_id="test-snipeit-client-id",
        snipeit_client_secret="test-snipeit-client-secret",
        snipeit_encryption_key=Fernet.generate_key().decode(),
    )


@pytest.fixture
def test_user():
    """Create a test user for authentication."""
    from app.infrastructure.auth.models import SessionUser

    return SessionUser(
        id="test-user-123",
        email="test@example.com",
        name="Test User",
        avatar_url="https://example.com/avatar.jpg",
        provider="test",
    )


@pytest_asyncio.fixture
async def authenticated_client(
    async_connection: AsyncConnection,
    snipeit_test_settings: object,
    test_user: object,
) -> AsyncGenerator[AsyncClient, None]:
    """Authenticated client with Snipe-IT OAuth config enabled."""
    async with _authenticated_client_context(
        async_connection, snipeit_test_settings, test_user
    ) as client:
        yield client


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

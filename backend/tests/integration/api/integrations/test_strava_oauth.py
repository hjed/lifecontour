"""
Integration tests for Strava OAuth endpoints and registry provider.

Tests verify the Strava integration lifecycle: registry visibility,
OAuth authorization, callback token storage, and disconnection against
a real database with savepoint rollback.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
class TestStravaIntegrationRegistry:
    """Tests for Strava visibility in the integration registry."""

    async def test_strava_appears_in_integrations_list(
        self, authenticated_client
    ) -> None:
        """GET /api/integrations includes a Strava entry with 'disconnected' status."""
        response = await authenticated_client.get("/api/integrations")
        assert response.status_code == 200

        data = response.json()["data"]
        strava_entries = [entry for entry in data if entry["id"] == "strava"]
        assert len(strava_entries) == 1

        strava = strava_entries[0]
        assert strava["attributes"]["name"] == "Strava"
        assert strava["attributes"]["status"] == "disconnected"
        assert "activity_import" in strava["attributes"]["capabilities"]

    async def test_strava_connected_status_after_storing_tokens(
        self, authenticated_client, async_connection
    ) -> None:
        """After inserting tokens into user_strava_auth, registry shows 'connected'."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        fernet = Fernet(key)

        now = datetime.now(UTC)
        await async_connection.execute(
            text("""
                INSERT INTO user_strava_auth (
                    user_id, athlete_id, encrypted_access_token,
                    encrypted_refresh_token, expires_at,
                    needs_reauth, created_at, updated_at
                )
                VALUES (
                    :user_id, :athlete_id, :access_token,
                    :refresh_token, :expires_at,
                    FALSE, :now, :now
                )
            """),
            {
                "user_id": "test-user-123",
                "athlete_id": 12345,
                "access_token": fernet.encrypt(b"test-access"),
                "refresh_token": fernet.encrypt(b"test-refresh"),
                "expires_at": now + timedelta(hours=6),
                "now": now,
            },
        )

        response = await authenticated_client.get("/api/integrations")
        assert response.status_code == 200

        data = response.json()["data"]
        strava_entries = [entry for entry in data if entry["id"] == "strava"]
        assert len(strava_entries) == 1
        assert strava_entries[0]["attributes"]["status"] == "connected"


@pytest.mark.asyncio
class TestStravaOAuthAuthorize:
    """Tests for POST /api/integrations/strava/oauth/authorize."""

    async def test_authorize_returns_strava_url(
        self, authenticated_client, test_settings
    ) -> None:
        """Authorize endpoint returns a Strava OAuth URL with correct scope."""
        # Set Strava client ID in test settings so endpoint doesn't 500
        test_settings.strava_client_id = "test-strava-client-id"

        response = await authenticated_client.post(
            "/api/integrations/strava/oauth/authorize",
            json={"redirect_url": "/integrations"},
        )
        assert response.status_code == 200

        data = response.json()
        assert "authorization_url" in data
        assert "state" in data

        auth_url = data["authorization_url"]
        assert "strava.com/oauth/authorize" in auth_url
        assert "client_id=test-strava-client-id" in auth_url
        assert "scope=activity%3Aread_all" in auth_url
        assert "response_type=code" in auth_url

    async def test_authorize_fails_without_client_id(
        self, authenticated_client, test_settings
    ) -> None:
        """Authorize endpoint returns 500 when Strava is not configured."""
        test_settings.strava_client_id = ""

        response = await authenticated_client.post(
            "/api/integrations/strava/oauth/authorize",
            json={"redirect_url": "/integrations"},
        )
        assert response.status_code == 500
        errors = response.json()["errors"]
        assert len(errors) == 1
        assert "not configured" in errors[0]["detail"]


@pytest.mark.asyncio
class TestStravaOAuthCallback:
    """Tests for POST /api/integrations/strava/oauth/callback."""

    async def test_callback_exchanges_code_and_stores_tokens(
        self, authenticated_client, test_settings, async_connection
    ) -> None:
        """Callback exchanges the code with Strava and stores encrypted tokens."""
        from unittest.mock import MagicMock

        test_settings.strava_client_id = "test-client-id"
        test_settings.strava_client_secret = "test-client-secret"
        test_settings.strava_encryption_key = (
            "KzC1vYhL3bQpT_x5Ue8q0Wl1MvX-oVwYwK9cQx7lKHg="
        )

        # First, call authorize to set up the session state
        auth_response = await authenticated_client.post(
            "/api/integrations/strava/oauth/authorize",
            json={"redirect_url": "/integrations"},
        )
        assert auth_response.status_code == 200
        state = auth_response.json()["state"]

        # Carry the session cookie forward so the CSRF state is available
        session_cookie = auth_response.cookies.get("session")
        if session_cookie:
            authenticated_client.cookies.set("session", session_cookie)

        # Mock the Strava token exchange HTTP call.
        # httpx Response methods (json, raise_for_status) are synchronous,
        # so we use MagicMock, not AsyncMock.
        mock_token_response = MagicMock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            "access_token": "strava-access-token",
            "refresh_token": "strava-refresh-token",
            "expires_at": int((datetime.now(UTC) + timedelta(hours=6)).timestamp()),
            "athlete": {"id": 67890},
        }
        mock_token_response.raise_for_status = MagicMock()

        with patch(
            "app.api.integrations.strava_controllers.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_token_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            response = await authenticated_client.post(
                "/api/integrations/strava/oauth/callback",
                json={"code": "auth-code-from-strava", "state": state},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Strava connected successfully"

        # Verify tokens were stored in the database
        result = await async_connection.execute(
            text("SELECT athlete_id FROM user_strava_auth WHERE user_id = :uid"),
            {"uid": "test-user-123"},
        )
        row = result.fetchone()
        assert row is not None
        assert row.athlete_id == 67890

    async def test_callback_rejects_invalid_state(
        self, authenticated_client, test_settings
    ) -> None:
        """Callback returns 400 when the CSRF state doesn't match."""
        test_settings.strava_client_id = "test-client-id"

        response = await authenticated_client.post(
            "/api/integrations/strava/oauth/callback",
            json={"code": "some-code", "state": "invalid-state-value"},
        )
        assert response.status_code == 400
        errors = response.json()["errors"]
        assert len(errors) == 1
        assert "state" in errors[0]["detail"].lower()


@pytest.mark.asyncio
class TestStravaOAuthDisconnect:
    """Tests for DELETE /api/integrations/strava/oauth/disconnect."""

    async def test_disconnect_clears_tokens(
        self, authenticated_client, test_settings, async_connection
    ) -> None:
        """Disconnect removes the user_strava_auth row."""
        from cryptography.fernet import Fernet

        test_settings.strava_encryption_key = (
            "KzC1vYhL3bQpT_x5Ue8q0Wl1MvX-oVwYwK9cQx7lKHg="
        )

        key = "KzC1vYhL3bQpT_x5Ue8q0Wl1MvX-oVwYwK9cQx7lKHg="
        fernet = Fernet(key.encode())
        now = datetime.now(UTC)

        # Insert tokens manually
        await async_connection.execute(
            text("""
                INSERT INTO user_strava_auth (
                    user_id, athlete_id, encrypted_access_token,
                    encrypted_refresh_token, expires_at,
                    needs_reauth, created_at, updated_at
                )
                VALUES (
                    :user_id, :athlete_id, :access_token,
                    :refresh_token, :expires_at,
                    FALSE, :now, :now
                )
            """),
            {
                "user_id": "test-user-123",
                "athlete_id": 99999,
                "access_token": fernet.encrypt(b"access-to-revoke"),
                "refresh_token": fernet.encrypt(b"refresh-token"),
                "expires_at": now + timedelta(hours=6),
                "now": now,
            },
        )

        # Mock the Strava deauthorize call
        with patch(
            "app.api.integrations.strava_controllers.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = AsyncMock(status_code=200)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            response = await authenticated_client.delete(
                "/api/integrations/strava/oauth/disconnect",
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "disconnected" in data["message"].lower()

        # Verify tokens were removed
        result = await async_connection.execute(
            text("SELECT 1 FROM user_strava_auth WHERE user_id = :uid"),
            {"uid": "test-user-123"},
        )
        assert result.fetchone() is None

    async def test_disconnect_when_not_connected_returns_success(
        self, authenticated_client, test_settings
    ) -> None:
        """Disconnect gracefully succeeds even when not connected."""
        test_settings.strava_encryption_key = (
            "KzC1vYhL3bQpT_x5Ue8q0Wl1MvX-oVwYwK9cQx7lKHg="
        )

        response = await authenticated_client.delete(
            "/api/integrations/strava/oauth/disconnect",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

"""
Integration tests for the GET /api/integrations registry endpoint.

Tests the full stack: controller → DI → service → provider → database.
Each test uses the authenticated_client fixture which provides transaction
rollback isolation via savepoints.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest.mark.asyncio
class TestIntegrationRegistryAPI:
    """Integration tests for the integration registry REST API."""

    async def test_list_integrations_returns_google_disconnected(
        self, authenticated_client: AsyncClient
    ) -> None:
        """No user_google_auth rows → Google shows as disconnected."""
        response = await authenticated_client.get("/api/integrations")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]) >= 1

        google = next((d for d in body["data"] if d["id"] == "google"), None)
        assert google is not None
        assert google["type"] == "integration"
        assert google["attributes"]["name"] == "Google"
        assert google["attributes"]["status"] == "disconnected"
        assert google["attributes"]["needs_reauth"] is False
        assert google["attributes"]["needs_reconsent"] is False
        assert "contacts_sync" in google["attributes"]["capabilities"]
        assert "calendar_sync" in google["attributes"]["capabilities"]

    async def test_list_integrations_returns_google_connected(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        """Valid tokens with full scopes → Google shows as connected."""
        # Seed user_google_auth for test-user-123
        await async_connection.execute(
            text("""
                INSERT INTO user_google_auth (
                    user_id, google_account_email,
                    encrypted_access_token, encrypted_refresh_token,
                    expires_at, granted_scopes, needs_reauth
                ) VALUES (
                    :user_id, 'test@gmail.com',
                    :token, :token,
                    NOW() + INTERVAL '1 hour',
                    'https://www.googleapis.com/auth/contacts https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly',
                    false
                )
            """),
            {
                "user_id": "test-user-123",
                "token": b"encrypted-test-token",
            },
        )

        response = await authenticated_client.get("/api/integrations")

        assert response.status_code == 200
        body = response.json()
        google = next((d for d in body["data"] if d["id"] == "google"), None)
        assert google is not None
        assert google["attributes"]["status"] == "connected"
        assert google["attributes"]["needs_reauth"] is False
        assert google["attributes"]["needs_reconsent"] is False

    async def test_list_integrations_returns_google_token_expired(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        """needs_reauth=True → Google shows as token_expired."""
        await async_connection.execute(
            text("""
                INSERT INTO user_google_auth (
                    user_id, google_account_email,
                    encrypted_access_token, encrypted_refresh_token,
                    expires_at, granted_scopes, needs_reauth
                ) VALUES (
                    :user_id, 'test@gmail.com',
                    :token, :token,
                    NOW() - INTERVAL '1 hour',
                    'https://www.googleapis.com/auth/contacts https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly',
                    true
                )
            """),
            {
                "user_id": "test-user-123",
                "token": b"encrypted-test-token",
            },
        )

        response = await authenticated_client.get("/api/integrations")

        assert response.status_code == 200
        body = response.json()
        google = next((d for d in body["data"] if d["id"] == "google"), None)
        assert google is not None
        assert google["attributes"]["status"] == "token_expired"
        assert google["attributes"]["needs_reauth"] is True

    async def test_list_integrations_json_api_format(
        self, authenticated_client: AsyncClient
    ) -> None:
        """Response follows JSON API format with data array and typed entries."""
        response = await authenticated_client.get("/api/integrations")

        assert response.status_code == 200
        body = response.json()

        # Root must have "data" key
        assert "data" in body
        assert isinstance(body["data"], list)

        # Each entry must have id, type, and attributes
        for entry in body["data"]:
            assert "id" in entry
            assert "type" in entry
            assert entry["type"] == "integration"
            assert "attributes" in entry

            attrs = entry["attributes"]
            assert "name" in attrs
            assert "status" in attrs
            assert "capabilities" in attrs
            assert "sync_summary" in attrs
            assert "needs_reauth" in attrs
            assert "needs_reconsent" in attrs

            # Sync summary structure
            summary = attrs["sync_summary"]
            assert "sync_count" in summary
            assert "error_count" in summary

    async def test_list_integrations_requires_authentication(
        self,
        authenticated_client: AsyncClient,
        test_settings: object,
    ) -> None:
        """Unauthenticated requests should be rejected.

        Note: The authenticated_client fixture always sends a valid session
        cookie, so we create a separate client to test the unauthenticated case.
        Uses the same pattern as test_authentication_requirements.py.
        """
        from starlette.testclient import TestClient

        from app.main import create_app

        app = create_app(settings=test_settings)  # type: ignore[arg-type]
        client = TestClient(app)
        response = client.get("/api/integrations", headers={"Host": "localhost"})

        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

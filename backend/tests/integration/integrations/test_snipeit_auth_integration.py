"""
Integration tests for Snipe-IT API key auth endpoints.

Tests the full stack: controller → DI → token service → database.

The connect endpoint now commits in the service layer via ``unit_of_work``
(issue #945), which under the test fixture is emulated with a SAVEPOINT on the
shared ``async_connection``. Writes therefore stay visible to later reads on
that same connection (read-after-write within a test) and are rolled back at
teardown for isolation — so tests seed and verify DB state through
``async_connection``, not an independent engine connection (which can't see
the savepoint-scoped writes).
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest.fixture
def test_settings(test_settings):
    """Override test_settings with Snipe-IT encryption key populated."""
    test_settings.snipeit_encryption_key = Fernet.generate_key().decode()
    return test_settings


@pytest.mark.asyncio
class TestSnipeItConnect:
    """Tests for POST /api/integrations/snipeit/connect."""

    async def test_connect_stores_encrypted_api_key(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        """POST /connect encrypts and stores the API key."""
        response = await authenticated_client.post(
            "/api/integrations/snipeit/connect",
            json={"api_key": "test-api-key-abc123"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "connected" in body["message"].lower()

        # Verify key was saved on the shared test connection (where the
        # service's unit-of-work savepoint committed it).
        result = await async_connection.execute(
            text(
                "SELECT encrypted_api_key FROM user_snipe_it_auth WHERE user_id = :uid"
            ),
            {"uid": "test-user-123"},
        )
        row = result.fetchone()
        assert row is not None
        assert row.encrypted_api_key is not None
        assert row.encrypted_api_key != b"test-api-key-abc123"

    async def test_connect_rejects_empty_api_key(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        """POST /connect returns 400 when API key is empty."""
        response = await authenticated_client.post(
            "/api/integrations/snipeit/connect",
            json={"api_key": "   "},
        )

        assert response.status_code == 400
        body = response.json()
        detail = body.get("detail") or body.get("errors", [{}])[0].get("detail", "")
        assert "required" in detail.lower()

    async def test_connect_upserts_existing_key(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        """POST /connect performs upsert when a key already exists."""
        # Pre-seed an existing auth row on the shared test connection so the
        # DI-injected request sees it.
        await async_connection.execute(
            text("""
                INSERT INTO user_snipe_it_auth (
                    user_id, encrypted_api_key
                ) VALUES (
                    :user_id, :api_key
                )
            """),
            {
                "user_id": "test-user-123",
                "api_key": b"old-encrypted-key",
            },
        )

        # Call connect — should upsert, not conflict
        response = await authenticated_client.post(
            "/api/integrations/snipeit/connect",
            json={"api_key": "new-key"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify only one row exists and key was updated
        result = await async_connection.execute(
            text(
                "SELECT COUNT(*) as cnt, MAX(encrypted_api_key) as key"
                " FROM user_snipe_it_auth WHERE user_id = :uid"
            ),
            {"uid": "test-user-123"},
        )
        row = result.fetchone()
        assert row is not None
        assert row.cnt == 1
        # Key should have changed from the pre-seeded value
        assert row.key != b"old-encrypted-key"


@pytest.mark.asyncio
class TestSnipeItDisconnect:
    """Tests for DELETE /api/integrations/snipeit/connect."""

    async def test_disconnect_removes_auth_record(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        """DELETE /connect removes a pre-seeded auth row.

        Pre-seeds via the shared test connection so the DI-injected request
        sees the row, then calls disconnect. We verify via the response body
        (the token service reports deletion).
        """
        # Pre-seed an existing auth row
        await async_connection.execute(
            text("""
                INSERT INTO user_snipe_it_auth (
                    user_id, encrypted_api_key
                ) VALUES (
                    :user_id, :api_key
                )
            """),
            {
                "user_id": "test-user-123",
                "api_key": b"key-to-remove",
            },
        )

        # Disconnect — should find and delete the seeded row
        response = await authenticated_client.delete(
            "/api/integrations/snipeit/connect",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        # "disconnected" confirms the token service found and deleted the row
        assert "disconnected" in body["message"].lower()

    async def test_disconnect_no_connection_succeeds(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        """DELETE /connect when not connected returns success."""
        response = await authenticated_client.delete(
            "/api/integrations/snipeit/connect",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True


@pytest.mark.asyncio
class TestSnipeItRegistryStatus:
    """Tests for GET /api/integrations registry status.

    These tests seed data on the shared test connection (visible to the
    DI-injected request on the same connection) and then query the registry
    endpoint.
    """

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
        await async_connection.execute(
            text("""
                INSERT INTO user_snipe_it_auth (
                    user_id, encrypted_api_key
                ) VALUES (
                    :user_id, :api_key
                )
            """),
            {
                "user_id": "test-user-123",
                "api_key": b"fake-encrypted-api-key",
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
                    user_id, encrypted_api_key, needs_reauth
                ) VALUES (
                    :user_id, :api_key, true
                )
            """),
            {
                "user_id": "test-user-123",
                "api_key": b"fake-encrypted-api-key",
            },
        )

        response = await authenticated_client.get("/api/integrations")

        assert response.status_code == 200
        body = response.json()
        snipeit = next((d for d in body["data"] if d["id"] == "snipeit"), None)
        assert snipeit is not None
        assert snipeit["attributes"]["status"] == "token_expired"
        assert snipeit["attributes"]["needs_reauth"] is True

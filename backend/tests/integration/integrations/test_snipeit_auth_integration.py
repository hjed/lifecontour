"""
Integration tests for Snipe-IT API key auth endpoints.

Tests the full stack: controller → DI → token service → database.

NOTE: The connect endpoint calls ``commit()`` explicitly so the
worker can immediately read the key. This destroys the savepoint
isolation that the standard ``authenticated_client`` fixture uses.

For tests that verify DB state after commit, we use the ``async_engine``
to open independent connections. An ``autouse`` cleanup fixture deletes
leaked data between tests.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
def test_settings(test_settings):
    """Override test_settings with Snipe-IT encryption key populated."""
    test_settings.snipeit_encryption_key = Fernet.generate_key().decode()
    return test_settings


@pytest.fixture(autouse=True)
async def clean_snipeit_auth(async_engine: AsyncEngine):
    """Clean up Snipe-IT auth data before and after each test.

    Required because the connect endpoint commits outside the
    test savepoint, leaking data between tests.
    """
    async with async_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM sync_jobs WHERE integration_source = 'snipeit'")
        )
        await conn.execute(text("DELETE FROM user_snipe_it_auth"))

    yield

    async with async_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM sync_jobs WHERE integration_source = 'snipeit'")
        )
        await conn.execute(text("DELETE FROM user_snipe_it_auth"))


@pytest.mark.asyncio
class TestSnipeItConnect:
    """Tests for POST /api/integrations/snipeit/connect."""

    async def test_connect_stores_encrypted_api_key(
        self,
        authenticated_client: AsyncClient,
        async_engine: AsyncEngine,
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

        # Verify key was saved using an independent connection
        async with async_engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT encrypted_api_key FROM user_snipe_it_auth"
                    " WHERE user_id = :uid"
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
        async_engine: AsyncEngine,
    ) -> None:
        """POST /connect performs upsert when a key already exists.

        Pre-seeds a row and then calls connect once. This avoids calling
        connect twice in the same test (the first commit() destroys the
        savepoint and breaks subsequent DI-injected requests).
        """
        # Pre-seed an existing auth row
        async with async_engine.begin() as conn:
            await conn.execute(
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
        async with async_engine.begin() as conn:
            result = await conn.execute(
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
        async_engine: AsyncEngine,
    ) -> None:
        """DELETE /connect removes a pre-seeded auth row.

        We pre-seed via the engine, then call disconnect. Since the
        DI-injected connection can see the committed seed, the delete
        executes correctly. We verify via response body (the token
        service reports deletion) rather than querying a separate
        connection that can't see savepoint-scoped changes.
        """
        # Pre-seed an existing auth row
        async with async_engine.begin() as conn:
            await conn.execute(
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

    These tests seed data via the raw engine (committed, visible to the
    DI connection) and then query the registry endpoint.
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
        async_engine: AsyncEngine,
    ) -> None:
        """GET /api/integrations shows snipeit as connected when auth row exists."""
        async with async_engine.begin() as conn:
            await conn.execute(
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
        async_engine: AsyncEngine,
    ) -> None:
        """GET /api/integrations shows snipeit as token_expired when needs_reauth."""
        async with async_engine.begin() as conn:
            await conn.execute(
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

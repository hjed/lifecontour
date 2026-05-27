"""
Integration tests for ImmichAuthService.

Verifies that API key storage and retrieval work correctly against
a real PostgreSQL database with the ``user_immich_auth`` table.
"""

from __future__ import annotations

from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from immich_auth_service import ImmichAuthService


@pytest.fixture
def valid_fernet_key() -> str:
    """Return a valid base64-encoded Fernet key."""
    return Fernet.generate_key().decode()


@pytest.fixture
def auth_service(valid_fernet_key: str) -> ImmichAuthService:
    """Return a configured auth service instance."""
    return ImmichAuthService(valid_fernet_key)


class TestImmichAuthServiceIntegration:
    """Integration tests for ImmichAuthService against real database."""

    @pytest.mark.asyncio
    async def test_get_api_key_returns_none_when_no_row(
        self,
        auth_service: ImmichAuthService,
        async_connection: Any,
    ) -> None:
        """get_api_key returns None when no auth row exists for user."""
        result = await auth_service.get_api_key("nonexistent-user", async_connection)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_server_url_returns_none_when_no_row(
        self,
        auth_service: ImmichAuthService,
        async_connection: Any,
    ) -> None:
        """get_server_url returns None when no auth row exists for user."""
        result = await auth_service.get_server_url("nonexistent-user", async_connection)
        assert result is None

    @pytest.mark.asyncio
    async def test_roundtrip_store_and_retrieve_api_key(
        self,
        auth_service: ImmichAuthService,
        async_connection: Any,
    ) -> None:
        """Store encrypted credentials and retrieve the decrypted API key."""
        user_id = "test-user-immich-roundtrip"
        api_key = "my-secret-immich-key"
        server_url = "https://immich.example.com"

        encrypted_key = auth_service.encrypt(api_key)

        # Insert directly into the table
        await async_connection.execute(
            text("""
                INSERT INTO user_immich_auth
                    (user_id, server_url, encrypted_api_key, created_at, updated_at)
                VALUES (:user_id, :server_url, :encrypted_api_key, now(), now())
            """),
            {
                "user_id": user_id,
                "server_url": server_url,
                "encrypted_api_key": encrypted_key,
            },
        )

        # Retrieve and verify
        retrieved_key = await auth_service.get_api_key(user_id, async_connection)
        assert retrieved_key == api_key

        retrieved_url = await auth_service.get_server_url(user_id, async_connection)
        assert retrieved_url == server_url

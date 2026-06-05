"""
Integration tests for Strava webhook endpoints.

Tests verify the hub.challenge validation handshake and POST event
handling against a real database with savepoint rollback.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text


@pytest.mark.asyncio
class TestStravaWebhookValidation:
    """Tests for GET /api/integrations/strava/webhook."""

    async def test_webhook_get_validation_handshake(
        self, authenticated_client, async_connection, test_settings
    ) -> None:
        """GET with valid hub.mode/challenge/verify_token returns challenge."""
        test_settings.strava_encryption_key = (
            "KzC1vYhL3bQpT_x5Ue8q0Wl1MvX-oVwYwK9cQx7lKHg="
        )
        fernet = Fernet(test_settings.strava_encryption_key.encode())
        now = datetime.now(UTC)

        # Insert auth data with a webhook verify token
        await async_connection.execute(
            text("""
                INSERT INTO user_strava_auth (
                    user_id, athlete_id, encrypted_access_token,
                    encrypted_refresh_token, expires_at,
                    needs_reauth, strava_webhook_subscription_id,
                    strava_webhook_verify_token,
                    created_at, updated_at
                )
                VALUES (
                    :user_id, :athlete_id, :access_token,
                    :refresh_token, :expires_at,
                    FALSE, :sub_id, :verify_token,
                    :now, :now
                )
            """),
            {
                "user_id": "test-user-123",
                "athlete_id": 12345,
                "access_token": fernet.encrypt(b"test-access"),
                "refresh_token": fernet.encrypt(b"test-refresh"),
                "expires_at": now + timedelta(hours=6),
                "sub_id": 99999,
                "verify_token": "test-verify-token-abc",
                "now": now,
            },
        )

        response = await authenticated_client.get(
            "/api/integrations/strava/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "challenge-value-xyz",
                "hub.verify_token": "test-verify-token-abc",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["hub.challenge"] == "challenge-value-xyz"

    async def test_webhook_get_rejects_wrong_token(
        self, authenticated_client, async_connection, test_settings
    ) -> None:
        """GET with wrong verify token returns 403."""
        test_settings.strava_encryption_key = (
            "KzC1vYhL3bQpT_x5Ue8q0Wl1MvX-oVwYwK9cQx7lKHg="
        )
        fernet = Fernet(test_settings.strava_encryption_key.encode())
        now = datetime.now(UTC)

        await async_connection.execute(
            text("""
                INSERT INTO user_strava_auth (
                    user_id, athlete_id, encrypted_access_token,
                    encrypted_refresh_token, expires_at,
                    needs_reauth, strava_webhook_subscription_id,
                    strava_webhook_verify_token,
                    created_at, updated_at
                )
                VALUES (
                    :user_id, :athlete_id, :access_token,
                    :refresh_token, :expires_at,
                    FALSE, :sub_id, :verify_token,
                    :now, :now
                )
            """),
            {
                "user_id": "test-user-123",
                "athlete_id": 12345,
                "access_token": fernet.encrypt(b"test-access"),
                "refresh_token": fernet.encrypt(b"test-refresh"),
                "expires_at": now + timedelta(hours=6),
                "sub_id": 99999,
                "verify_token": "correct-token",
                "now": now,
            },
        )

        response = await authenticated_client.get(
            "/api/integrations/strava/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "challenge-123",
                "hub.verify_token": "wrong-token",
            },
        )

        assert response.status_code == 403

    async def test_webhook_get_rejects_missing_params(
        self, authenticated_client
    ) -> None:
        """GET without required params returns 400."""
        response = await authenticated_client.get(
            "/api/integrations/strava/webhook",
            params={"hub.mode": "subscribe"},
        )
        assert response.status_code == 400

    async def test_webhook_get_validates_multiple_tokens_returns_200(
        self, authenticated_client, async_connection, test_settings
    ) -> None:
        """GET with multiple users/tokens validates successfully against the correct one."""
        test_settings.strava_encryption_key = (
            "KzC1vYhL3bQpT_x5Ue8q0Wl1MvX-oVwYwK9cQx7lKHg="
        )
        fernet = Fernet(test_settings.strava_encryption_key.encode())
        now = datetime.now(UTC)

        # Insert user 1 with token A
        await async_connection.execute(
            text("""
                INSERT INTO user_strava_auth (
                    user_id, athlete_id, encrypted_access_token,
                    encrypted_refresh_token, expires_at,
                    needs_reauth, strava_webhook_subscription_id,
                    strava_webhook_verify_token,
                    created_at, updated_at
                )
                VALUES (
                    :user_id, :athlete_id, :access_token,
                    :refresh_token, :expires_at,
                    FALSE, :sub_id, :verify_token,
                    :now, :now
                )
            """),
            {
                "user_id": "test-user-1",
                "athlete_id": 111,
                "access_token": fernet.encrypt(b"test-access"),
                "refresh_token": fernet.encrypt(b"test-refresh"),
                "expires_at": now + timedelta(hours=6),
                "sub_id": 11111,
                "verify_token": "token-user-1",
                "now": now,
            },
        )

        # Insert user 2 with token B
        await async_connection.execute(
            text("""
                INSERT INTO user_strava_auth (
                    user_id, athlete_id, encrypted_access_token,
                    encrypted_refresh_token, expires_at,
                    needs_reauth, strava_webhook_subscription_id,
                    strava_webhook_verify_token,
                    created_at, updated_at
                )
                VALUES (
                    :user_id, :athlete_id, :access_token,
                    :refresh_token, :expires_at,
                    FALSE, :sub_id, :verify_token,
                    :now, :now
                )
            """),
            {
                "user_id": "test-user-2",
                "athlete_id": 222,
                "access_token": fernet.encrypt(b"test-access"),
                "refresh_token": fernet.encrypt(b"test-refresh"),
                "expires_at": now + timedelta(hours=6),
                "sub_id": 22222,
                "verify_token": "token-user-2",
                "now": now,
            },
        )

        # Handshake for user 2
        response = await authenticated_client.get(
            "/api/integrations/strava/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "challenge-for-2",
                "hub.verify_token": "token-user-2",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["hub.challenge"] == "challenge-for-2"

    async def test_webhook_get_validates_when_subscription_id_is_null(
        self, authenticated_client, async_connection, test_settings
    ) -> None:
        """GET succeeds when subscription_id is NULL (pre-handshake window).

        During OAuth callback, the verify token is stored before Strava
        sends the validation GET, so subscription_id is still NULL.
        The handshake must still succeed.
        """
        test_settings.strava_encryption_key = (
            "KzC1vYhL3bQpT_x5Ue8q0Wl1MvX-oVwYwK9cQx7lKHg="
        )
        fernet = Fernet(test_settings.strava_encryption_key.encode())
        now = datetime.now(UTC)

        # Insert auth data with verify_token but NO subscription_id
        await async_connection.execute(
            text("""
                INSERT INTO user_strava_auth (
                    user_id, athlete_id, encrypted_access_token,
                    encrypted_refresh_token, expires_at,
                    needs_reauth, strava_webhook_subscription_id,
                    strava_webhook_verify_token,
                    created_at, updated_at
                )
                VALUES (
                    :user_id, :athlete_id, :access_token,
                    :refresh_token, :expires_at,
                    FALSE, NULL, :verify_token,
                    :now, :now
                )
            """),
            {
                "user_id": "test-user-123",
                "athlete_id": 12345,
                "access_token": fernet.encrypt(b"test-access"),
                "refresh_token": fernet.encrypt(b"test-refresh"),
                "expires_at": now + timedelta(hours=6),
                "verify_token": "pre-handshake-token",
                "now": now,
            },
        )

        response = await authenticated_client.get(
            "/api/integrations/strava/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "pre-handshake-challenge",
                "hub.verify_token": "pre-handshake-token",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["hub.challenge"] == "pre-handshake-challenge"


@pytest.mark.asyncio
class TestStravaWebhookPost:
    """Tests for POST /api/integrations/strava/webhook."""

    KNOWN_SUBSCRIPTION_ID = 99999

    async def _insert_subscription(self, async_connection, test_settings) -> None:
        """Insert auth row with a known subscription_id for validation."""
        test_settings.strava_encryption_key = (
            "KzC1vYhL3bQpT_x5Ue8q0Wl1MvX-oVwYwK9cQx7lKHg="
        )
        fernet = Fernet(test_settings.strava_encryption_key.encode())
        now = datetime.now(UTC)

        await async_connection.execute(
            text("""
                INSERT INTO user_strava_auth (
                    user_id, athlete_id, encrypted_access_token,
                    encrypted_refresh_token, expires_at,
                    needs_reauth, strava_webhook_subscription_id,
                    strava_webhook_verify_token,
                    created_at, updated_at
                )
                VALUES (
                    :user_id, :athlete_id, :access_token,
                    :refresh_token, :expires_at,
                    FALSE, :sub_id, :verify_token,
                    :now, :now
                )
            """),
            {
                "user_id": "test-user-123",
                "athlete_id": 12345,
                "access_token": fernet.encrypt(b"test-access"),
                "refresh_token": fernet.encrypt(b"test-refresh"),
                "expires_at": now + timedelta(hours=6),
                "sub_id": self.KNOWN_SUBSCRIPTION_ID,
                "verify_token": "test-verify-token",
                "now": now,
            },
        )

    async def test_webhook_post_activity_create_enqueues_and_returns_200(
        self, authenticated_client, async_connection, test_settings
    ) -> None:
        """POST activity create with known subscription enqueues and returns 200."""
        await self._insert_subscription(async_connection, test_settings)

        response = await authenticated_client.post(
            "/api/integrations/strava/webhook",
            json={
                "aspect_type": "create",
                "object_type": "activity",
                "object_id": 12345678,
                "owner_id": 67890,
                "subscription_id": self.KNOWN_SUBSCRIPTION_ID,
                "event_time": 1700000000,
            },
        )

        assert response.status_code == 200

    async def test_webhook_post_activity_update_returns_200(
        self, authenticated_client, async_connection, test_settings
    ) -> None:
        """POST activity update with known subscription returns 200."""
        await self._insert_subscription(async_connection, test_settings)

        response = await authenticated_client.post(
            "/api/integrations/strava/webhook",
            json={
                "aspect_type": "update",
                "object_type": "activity",
                "object_id": 12345678,
                "owner_id": 67890,
                "subscription_id": self.KNOWN_SUBSCRIPTION_ID,
                "event_time": 1700000000,
                "updates": {"title": "New Title"},
            },
        )
        assert response.status_code == 200

    async def test_webhook_post_activity_delete_returns_200(
        self, authenticated_client, async_connection, test_settings
    ) -> None:
        """POST activity delete with known subscription returns 200."""
        await self._insert_subscription(async_connection, test_settings)

        response = await authenticated_client.post(
            "/api/integrations/strava/webhook",
            json={
                "aspect_type": "delete",
                "object_type": "activity",
                "object_id": 12345678,
                "owner_id": 67890,
                "subscription_id": self.KNOWN_SUBSCRIPTION_ID,
                "event_time": 1700000000,
            },
        )
        assert response.status_code == 200

    async def test_webhook_post_non_activity_returns_200(
        self, authenticated_client
    ) -> None:
        """POST non-activity (athlete) event returns 200 without enqueue.

        Non-activity events are rejected before subscription_id check.
        """
        response = await authenticated_client.post(
            "/api/integrations/strava/webhook",
            json={
                "aspect_type": "update",
                "object_type": "athlete",
                "object_id": 67890,
                "owner_id": 67890,
                "subscription_id": 1,
                "event_time": 1700000000,
            },
        )
        assert response.status_code == 200

    async def test_webhook_post_unknown_subscription_id_returns_200_without_enqueue(
        self, authenticated_client, async_connection, test_settings
    ) -> None:
        """POST with unknown subscription_id returns 200 but skips enqueue."""
        await self._insert_subscription(async_connection, test_settings)

        with patch(
            "app.api.integrations.strava_controllers.ArqRedis.enqueue_job",
        ) as mock_enqueue:
            response = await authenticated_client.post(
                "/api/integrations/strava/webhook",
                json={
                    "aspect_type": "create",
                    "object_type": "activity",
                    "object_id": 12345678,
                    "owner_id": 67890,
                    "subscription_id": 11111,  # Not the known ID
                    "event_time": 1700000000,
                },
            )

        assert response.status_code == 200
        mock_enqueue.assert_not_called()

    async def test_webhook_post_enqueue_failure_returns_500(
        self, authenticated_client, async_connection, test_settings
    ) -> None:
        """POST returns 500 when ARQ enqueue fails, so Strava retries."""
        await self._insert_subscription(async_connection, test_settings)

        with patch(
            "app.api.integrations.strava_controllers.ArqRedis.enqueue_job",
            side_effect=ConnectionError("Redis down"),
        ):
            response = await authenticated_client.post(
                "/api/integrations/strava/webhook",
                json={
                    "aspect_type": "create",
                    "object_type": "activity",
                    "object_id": 12345678,
                    "owner_id": 67890,
                    "subscription_id": self.KNOWN_SUBSCRIPTION_ID,
                    "event_time": 1700000000,
                },
            )

        assert response.status_code == 500

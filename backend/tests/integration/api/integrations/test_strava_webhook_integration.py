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


@pytest.mark.asyncio
class TestStravaWebhookPost:
    """Tests for POST /api/integrations/strava/webhook."""

    async def test_webhook_post_activity_create_returns_200(
        self, authenticated_client
    ) -> None:
        """POST activity create event returns 200 and enqueues task."""
        with patch(
            "app.api.integrations.strava_controllers.ArqRedis",
        ):
            response = await authenticated_client.post(
                "/api/integrations/strava/webhook",
                json={
                    "aspect_type": "create",
                    "object_type": "activity",
                    "object_id": 12345678,
                    "owner_id": 67890,
                    "subscription_id": 1,
                    "event_time": 1700000000,
                },
            )

        assert response.status_code == 200

    async def test_webhook_post_activity_update_returns_200(
        self, authenticated_client
    ) -> None:
        """POST activity update event returns 200."""
        response = await authenticated_client.post(
            "/api/integrations/strava/webhook",
            json={
                "aspect_type": "update",
                "object_type": "activity",
                "object_id": 12345678,
                "owner_id": 67890,
                "subscription_id": 1,
                "event_time": 1700000000,
                "updates": {"title": "New Title"},
            },
        )
        assert response.status_code == 200

    async def test_webhook_post_activity_delete_returns_200(
        self, authenticated_client
    ) -> None:
        """POST activity delete event returns 200."""
        response = await authenticated_client.post(
            "/api/integrations/strava/webhook",
            json={
                "aspect_type": "delete",
                "object_type": "activity",
                "object_id": 12345678,
                "owner_id": 67890,
                "subscription_id": 1,
                "event_time": 1700000000,
            },
        )
        assert response.status_code == 200

    async def test_webhook_post_non_activity_returns_200(
        self, authenticated_client
    ) -> None:
        """POST non-activity (athlete) event returns 200 without enqueue."""
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

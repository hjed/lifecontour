"""
Integration tests for Google OAuth API endpoints.

Tests the real API endpoints with mocked Google OAuth services.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi.testclient import TestClient

from app.core.integrations.google_oauth import (
    GoogleAccount,
    GoogleAccountNotFoundError,
    GoogleOAuthConfigurationError,
    GoogleOAuthState,
    GoogleOAuthTokens,
)
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.di.contacts import ContactProvider
from app.infrastructure.di.database import DatabaseProvider
from app.infrastructure.di.infrastructure import InfrastructureProvider
from app.infrastructure.di.integrations import IntegrationProvider
from app.main import create_app


class TestGoogleOAuthEndpoints:
    """Integration tests for Google OAuth API endpoints."""

    @pytest.fixture
    def test_user(self) -> SessionUser:
        """Create a test user."""
        return SessionUser(
            id="123",
            email="test@example.com",
            name="Test User",
            provider="test",
        )

    @pytest.fixture
    def client(self, test_settings, test_user):
        """Create authenticated test client."""

        class TestAuthProvider(Provider):
            """Test provider for authenticated client."""

            @provide(scope=Scope.REQUEST)
            def get_session_user(self) -> SessionUser:
                return test_user  # type: ignore

        app = create_app(settings=test_settings)

        test_container = make_async_container(
            DatabaseProvider(test_settings),
            InfrastructureProvider(),
            TestAuthProvider(),
            ContactProvider(),
            IntegrationProvider(),
            FastapiProvider(),
        )

        try:
            app.state.dishka_container.close()
        except (RuntimeError, AttributeError):
            pass
        app.state.dishka_container = test_container
        setup_dishka(test_container, app)

        return TestClient(app)

    def test_initiate_google_oauth_success(self, client: TestClient):
        """Test successful OAuth initiation."""
        with (
            patch(
                "app.core.integrations.google_oauth.service.GoogleOAuthService.create_oauth_state"
            ) as mock_create_state,
            patch(
                "app.core.integrations.google_oauth.service.GoogleOAuthService.get_authorization_url"
            ) as mock_get_auth_url,
        ):
            mock_create_state.return_value = GoogleOAuthState(
                user_id="123",
                nonce="test-nonce",
                created_at=datetime.now(UTC),
                redirect_url="/integrations",
            )
            mock_get_auth_url.return_value = (
                "https://accounts.google.com/o/oauth2/v2/auth?test=params"
            )

            response = client.post(
                "/api/integrations/google/oauth/connect",
                json={"redirect_url": "/integrations"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "authorization_url" in data
            assert "accounts.google.com" in data["authorization_url"]

    def test_initiate_google_oauth_not_configured(self, client: TestClient):
        """Test OAuth initiation when not configured."""
        with (
            patch(
                "app.core.integrations.google_oauth.service.GoogleOAuthService.create_oauth_state"
            ) as mock_create_state,
            patch(
                "app.core.integrations.google_oauth.service.GoogleOAuthService.get_authorization_url"
            ) as mock_get_auth_url,
        ):
            mock_create_state.return_value = GoogleOAuthState(
                user_id="123",
                nonce="test-nonce",
                created_at=datetime.now(UTC),
            )
            mock_get_auth_url.side_effect = GoogleOAuthConfigurationError(
                "Not configured"
            )

            response = client.post(
                "/api/integrations/google/oauth/connect",
                json={},
            )

            assert response.status_code == 501
            data = response.json()
            assert "not configured" in data["errors"][0]["detail"].lower()

    def test_list_google_accounts_empty(self, client: TestClient):
        """Test listing accounts when none connected."""
        with patch(
            "app.core.integrations.google_oauth.service.GoogleOAuthService.get_accounts"
        ) as mock_get_accounts:
            mock_get_accounts.return_value = []

            response = client.get("/api/integrations/google/accounts")

            assert response.status_code == 200
            data = response.json()
            assert data["accounts"] == []

    def test_list_google_accounts_with_accounts(self, client: TestClient):
        """Test listing connected accounts."""
        mock_accounts = [
            GoogleAccount(
                id=1,
                user_id="123",
                email="user@gmail.com",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        ]

        with patch(
            "app.core.integrations.google_oauth.service.GoogleOAuthService.get_accounts"
        ) as mock_get_accounts:
            mock_get_accounts.return_value = mock_accounts

            response = client.get("/api/integrations/google/accounts")

            assert response.status_code == 200
            data = response.json()
            assert len(data["accounts"]) == 1
            assert data["accounts"][0]["email"] == "user@gmail.com"

    def test_disconnect_google_account_success(self, client: TestClient):
        """Test successful account disconnection."""
        with patch(
            "app.core.integrations.google_oauth.service.GoogleOAuthService.disconnect_account"
        ) as mock_disconnect:
            mock_disconnect.return_value = True

            response = client.delete("/api/integrations/google/accounts/user@gmail.com")

            assert response.status_code == 200
            data = response.json()
            assert "disconnected" in data["message"].lower()

    def test_disconnect_google_account_not_found(self, client: TestClient):
        """Test disconnecting non-existent account."""
        with patch(
            "app.core.integrations.google_oauth.service.GoogleOAuthService.disconnect_account"
        ) as mock_disconnect:
            mock_disconnect.side_effect = GoogleAccountNotFoundError(
                "nonexistent@gmail.com"
            )

            response = client.delete(
                "/api/integrations/google/accounts/nonexistent@gmail.com"
            )

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["errors"][0]["detail"].lower()

    def test_oauth_callback_success(self, client: TestClient):
        """Test successful OAuth callback."""
        mock_tokens = GoogleOAuthTokens(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=3600,
            token_type="Bearer",
            scope="contacts.readonly",
        )
        mock_account = GoogleAccount(
            id=1,
            user_id="123",
            email="user@gmail.com",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        with (
            patch(
                "app.core.integrations.google_oauth.service.GoogleOAuthService.decode_state"
            ) as mock_decode,
            patch(
                "app.core.integrations.google_oauth.service.GoogleOAuthService.exchange_code_for_tokens"
            ) as mock_exchange,
            patch(
                "app.core.integrations.google_oauth.service.GoogleOAuthService.get_user_email"
            ) as mock_get_email,
            patch(
                "app.core.integrations.google_oauth.service.GoogleOAuthService.save_account"
            ) as mock_save,
        ):
            mock_decode.return_value = GoogleOAuthState(
                user_id="123",
                nonce="test-nonce",
                created_at=datetime.now(UTC),
            )
            mock_exchange.return_value = mock_tokens
            mock_get_email.return_value = "user@gmail.com"
            mock_save.return_value = mock_account

            response = client.post(
                "/api/integrations/google/oauth/callback",
                json={"code": "auth-code", "state": "encoded-state"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["email"] == "user@gmail.com"
            assert "connected successfully" in data["message"].lower()

    def test_oauth_callback_user_mismatch(self, client: TestClient):
        """Test OAuth callback with user mismatch."""
        with patch(
            "app.core.integrations.google_oauth.service.GoogleOAuthService.decode_state"
        ) as mock_decode:
            mock_decode.return_value = GoogleOAuthState(
                user_id="different-user-456",
                nonce="test-nonce",
                created_at=datetime.now(UTC),
            )

            response = client.post(
                "/api/integrations/google/oauth/callback",
                json={"code": "auth-code", "state": "encoded-state"},
            )

            assert response.status_code == 403
            data = response.json()
            assert "does not match" in data["errors"][0]["detail"].lower()

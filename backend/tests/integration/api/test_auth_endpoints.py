"""
Integration tests for authentication API endpoints.

Tests OAuth authentication endpoints with real FastAPI application.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.main import create_app


@pytest.fixture
def test_settings(db_config):
    """Create test settings with OAuth providers configured."""
    return Settings(
        debug=True,
        database_url=db_config.get_async_url().replace(
            "postgresql+asyncpg://", "postgresql://"
        ),
        session_secret_key="test-session-secret",
        allowed_hosts=["*"],  # Allow all hosts for testing
        github_client_id="test_github_client_id",
        github_client_secret="test_github_client_secret",
        microsoft_client_id="test_microsoft_client_id",
        microsoft_client_secret="test_microsoft_client_secret",
        discord_client_id="test_discord_client_id",
        discord_client_secret="test_discord_client_secret",
    )


@pytest.fixture
def test_app(test_settings):
    """Create test FastAPI application."""
    return create_app(test_settings)


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


class TestAuthEndpoints:
    """Test authentication API endpoints."""

    def _create_oauth_test_client(self, test_settings: "Settings"):
        """Helper to create test client with OAuth service configured."""
        from dishka import Provider, Scope, make_async_container, provide
        from dishka.integrations.fastapi import setup_dishka

        from app.infrastructure.auth.models import SessionUser
        from app.infrastructure.auth.oauth_service import OAuthService
        from app.infrastructure.config import Settings

        class TestOAuthProvider(Provider):
            """Test provider for OAuth service."""

            @provide(scope=Scope.APP)
            def get_oauth_service(self) -> OAuthService:
                return OAuthService(test_settings)

            @provide(scope=Scope.APP)
            def get_settings(self) -> Settings:
                return test_settings

            @provide(scope=Scope.REQUEST)
            def get_session_user(self) -> SessionUser | None:
                # Return None for unauthenticated test scenarios
                return None

        # Create app with test settings
        app = create_app(test_settings)

        # Replace container with test container
        test_container = make_async_container(TestOAuthProvider())
        try:
            app.state.dishka_container.close()
        except RuntimeError:
            pass
        app.state.dishka_container = test_container
        setup_dishka(test_container, app)

        return TestClient(app)

    def test_get_auth_providers_no_providers(self, db_config):
        """Test getting available OAuth providers when none are configured."""
        # Create app with no OAuth providers
        settings = Settings(
            debug=True,
            session_secret_key="test-secret",
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            allowed_hosts=["*"],  # Allow all hosts for testing
        )
        app = create_app(settings)
        client = TestClient(app)

        response = client.get("/api/auth/providers")

        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert data["providers"] == []

    def test_get_auth_providers_with_providers(self, test_settings):
        """Test getting available OAuth providers when configured."""
        client = self._create_oauth_test_client(test_settings)

        response = client.get("/api/auth/providers")

        assert response.status_code == 200
        data = response.json()
        assert "providers" in data

        providers = data["providers"]
        provider_names = [p["name"] for p in providers]

        assert "github" in provider_names
        assert "microsoft" in provider_names
        assert "discord" in provider_names

        # Check provider structure
        github_provider = next(p for p in providers if p["name"] == "github")
        assert github_provider["display_name"] == "GitHub"
        assert "icon_url" in github_provider

    def test_get_auth_status_unauthenticated(self, client):
        """Test getting auth status when not authenticated."""
        response = client.get("/api/auth/status")

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False
        assert data["user"] is None

    def test_get_current_user_unauthenticated(self, client):
        """Test getting current user when not authenticated."""
        response = client.get("/api/auth/me")

        assert response.status_code == 401
        data = response.json()
        assert "errors" in data
        assert data["errors"][0]["status"] == "401"

    def test_logout_when_not_authenticated(self, client):
        """Test logout when not authenticated."""
        response = client.post("/api/auth/logout")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Successfully logged out"

    def test_authorize_invalid_provider(self, client):
        """Test OAuth authorization with invalid provider."""
        response = client.get("/api/auth/authorize/invalid_provider")

        assert response.status_code == 400

    def test_authorize_github_provider(self, test_settings):
        """Test OAuth authorization with GitHub provider."""
        client = self._create_oauth_test_client(test_settings)

        response = client.get("/api/auth/authorize/github", follow_redirects=False)

        # Should redirect to GitHub OAuth
        assert response.status_code == 307
        assert "location" in response.headers

        # Check that it's redirecting to GitHub
        location = response.headers["location"]
        assert "github.com" in location
        assert "oauth" in location

    def test_authorize_microsoft_provider(self, test_settings):
        """Test OAuth authorization with Microsoft provider."""
        client = self._create_oauth_test_client(test_settings)

        response = client.get("/api/auth/authorize/microsoft", follow_redirects=False)

        # Should redirect to Microsoft OAuth
        assert response.status_code == 307
        assert "location" in response.headers

        # Check that it's redirecting to Microsoft
        location = response.headers["location"]
        assert "login.microsoftonline.com" in location

    def test_authorize_discord_provider(self, test_settings):
        """Test OAuth authorization with Discord provider."""
        client = self._create_oauth_test_client(test_settings)

        response = client.get("/api/auth/authorize/discord", follow_redirects=False)

        # Should redirect to Discord OAuth
        assert response.status_code == 307
        assert "location" in response.headers

        # Check that it's redirecting to Discord
        location = response.headers["location"]
        assert "discord.com" in location

    def test_authorize_with_redirect_url(self, test_settings):
        """Test OAuth authorization with custom redirect URL."""
        client = self._create_oauth_test_client(test_settings)

        response = client.get(
            "/api/auth/authorize/github?redirect_url=/dashboard", follow_redirects=False
        )

        assert response.status_code == 307
        assert "location" in response.headers

    def test_oauth_callback_invalid_state(self, test_settings):
        """Test OAuth callback with invalid state parameter."""
        client = self._create_oauth_test_client(test_settings)

        response = client.get(
            "/api/auth/callback/github?code=test_code&state=invalid_state",
            follow_redirects=False,
        )

        # Should redirect to error page
        assert response.status_code == 307
        location = response.headers["location"]
        assert "error=auth_failed" in location

    def test_oauth_callback_missing_code(self, test_settings):
        """Test OAuth callback without authorization code."""
        client = self._create_oauth_test_client(test_settings)

        response = client.get(
            "/api/auth/callback/github?state=test_state", follow_redirects=False
        )

        # Should redirect to error page
        assert response.status_code == 307
        location = response.headers["location"]
        assert "error=auth_failed" in location

    @patch("app.infrastructure.auth.oauth_service.OAuthService.handle_callback")
    def test_oauth_callback_success(self, mock_handle_callback, test_settings):
        """Test successful OAuth callback."""
        from app.infrastructure.auth.models import OAuthUserInfo

        # Mock successful OAuth callback
        mock_handle_callback.return_value = OAuthUserInfo(
            id="12345",
            email="test@example.com",
            name="Test User",
            avatar_url="https://github.com/avatar.jpg",
            provider="github",
        )

        client = self._create_oauth_test_client(test_settings)

        # First, initiate OAuth flow to set up session
        auth_response = client.get("/api/auth/authorize/github", follow_redirects=False)

        # Extract session cookie from response
        session_cookie_value = None
        for cookie_name, cookie_value in auth_response.cookies.items():
            if cookie_name == "session":
                session_cookie_value = cookie_value
                break

        # Now test callback with session
        if session_cookie_value:
            response = client.get(
                "/api/auth/callback/github?code=test_code&state=test_state",
                cookies={"session": session_cookie_value},
                follow_redirects=False,
            )

            # Should redirect to success page
            assert response.status_code == 307

    def test_session_persistence(self, client):
        """Test that session data persists across requests."""
        # This test would require mocking the OAuth flow
        # and verifying that user data is stored in session
        pass

    def test_auth_error_handling(self, client):
        """Test authentication error handling."""
        # Test various error scenarios
        pass

    def test_cors_headers(self, test_settings):
        """Test CORS headers on auth endpoints."""
        # Create app with test settings that include CORS origins
        test_settings.cors_origins = ["http://localhost:3000", "http://localhost:8080"]
        client = self._create_oauth_test_client(test_settings)

        # Test CORS headers on a GET request with Origin header
        response = client.get(
            "/api/auth/status", headers={"Origin": "http://localhost:3000"}
        )
        assert response.status_code == 200

        # Check CORS headers are present
        assert "access-control-allow-origin" in response.headers
        assert "access-control-allow-credentials" in response.headers

    def test_session_security(self, client):
        """Test session security settings."""
        # Test that session cookies have proper security flags
        response = client.get("/api/auth/status")

        # Check for session cookie security
        for cookie in response.cookies:
            if cookie.name == "session":
                # In test mode, secure flag might not be set
                assert cookie.get("samesite") == "lax"

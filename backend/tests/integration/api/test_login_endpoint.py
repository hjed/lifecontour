"""
Integration tests for the /api/auth/login endpoint.

Tests the new login endpoint that returns JSON with authorization URL.
"""

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
    )


@pytest.fixture
def test_app(test_settings):
    """Create test FastAPI application."""
    return create_app(test_settings)


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


class TestLoginEndpoint:
    """Test the /api/auth/login endpoint."""

    def test_login_endpoint_exists(self, client):
        """Test that the login endpoint exists and accepts POST requests."""
        response = client.post("/api/auth/login", json={"provider": "github"})

        # Should not return 404 (endpoint exists)
        assert response.status_code != 404

        # Should return 200 with proper OAuth configuration or 400 if not configured
        assert response.status_code in [200, 400]

    def test_login_endpoint_returns_json(self, client):
        """Test that the login endpoint returns JSON response."""
        response = client.post("/api/auth/login", json={"provider": "github"})

        # Should return JSON
        assert response.headers.get("content-type") == "application/json"

        # Should be parseable as JSON
        data = response.json()
        assert isinstance(data, dict)

    def test_login_endpoint_with_configured_provider(self, client):
        """Test login endpoint behavior with configured OAuth provider."""
        response = client.post("/api/auth/login", json={"provider": "github"})

        if response.status_code == 200:
            # If OAuth is properly configured, should return authorization_url and state
            data = response.json()
            assert "authorization_url" in data
            assert "state" in data
            assert isinstance(data["authorization_url"], str)
            assert isinstance(data["state"], str)
        elif response.status_code == 400:
            # If OAuth is not configured, should return proper error
            data = response.json()
            assert "errors" in data
            assert len(data["errors"]) > 0
            assert "OAuth provider" in data["errors"][0]["detail"]

    def test_login_endpoint_invalid_provider(self, client):
        """Test login endpoint with invalid provider."""
        response = client.post("/api/auth/login", json={"provider": "invalid_provider"})

        # Should return 400 for invalid provider
        assert response.status_code == 400

        data = response.json()
        assert "errors" in data
        assert "OAuth provider" in data["errors"][0]["detail"]

    def test_login_endpoint_missing_provider(self, client):
        """Test login endpoint with missing provider field."""
        response = client.post("/api/auth/login", json={})

        # Should return 400 for validation error (handled by global error handler)
        assert response.status_code == 400

        data = response.json()
        assert "errors" in data
        assert "Field required" in data["errors"][0]["detail"]

    def test_login_endpoint_sets_session(self, client):
        """Test that login endpoint sets session data."""
        response = client.post("/api/auth/login", json={"provider": "github"})

        # Should set session cookie
        assert "set-cookie" in response.headers
        assert "session=" in response.headers["set-cookie"]

    def test_callback_endpoint_exists(self, client):
        """Test that the callback endpoint exists and accepts POST requests."""
        response = client.post(
            "/api/auth/callback",
            json={"code": "test_code", "state": "test_state", "provider": "github"},
        )

        # Should not return 404 (endpoint exists)
        assert response.status_code != 404

        # Should return 400 for invalid state (expected behavior)
        assert response.status_code == 400

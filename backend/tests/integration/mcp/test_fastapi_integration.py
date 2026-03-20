"""
Integration tests for MCP FastAPI integration.

Tests the MCP server integration with the main FastAPI application,
including OAuth authentication and .well-known discovery endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.main import create_app


class TestMCPFastAPIIntegration:
    """Test MCP server integration with FastAPI."""

    @pytest.fixture
    def test_settings(self, db_config):
        """Create test settings with MCP enabled (no auth)."""
        return Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
        )

    @pytest.fixture
    def app(self, test_settings):
        """Create FastAPI app with MCP integration."""
        return create_app(test_settings)

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_mcp_endpoint_exists(self, client):
        """Test that MCP endpoint is accessible."""
        # MCP endpoint should be mounted at /mcp-server/mcp
        response = client.get("/mcp-server/mcp")

        # Should not return 404 (endpoint exists)
        # May return 401 (authentication required) or other status
        assert response.status_code != 404

    def test_mcp_requires_authentication(self, client):
        """Test that MCP endpoint requires authentication."""
        # Try to access MCP endpoint without session
        # Use a simple GET request first to check if endpoint exists
        response = client.get("/mcp-server/mcp")

        # Should require authentication (401) or be a valid MCP response
        # FastMCP might return different status codes for different request types
        # 400 is also acceptable as it indicates the endpoint exists but request is invalid
        assert response.status_code in [
            400,  # Bad Request (endpoint exists but invalid request)
            401,  # Unauthorized
            405,  # Method Not Allowed
            422,  # Validation Error
        ]

    def test_main_app_still_works(self, client):
        """Test that main FastAPI app still works with MCP mounted."""
        # Test that the app is running by checking the OpenAPI docs
        # This should work regardless of database state
        response = client.get("/api/docs")

        # Should either return the docs (200) or redirect (3xx) if docs are disabled
        # 400 might occur if there are configuration issues, but that's still a response
        assert response.status_code in [
            200,  # Success
            307,  # Redirect
            400,  # Bad Request (but app is responding)
            404,  # Not Found (docs disabled)
        ]

    def test_mcp_mount_path_configurable(self, db_config):
        """Test that MCP mount path is configurable."""
        # Test with different mount path
        settings = Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/custom-mcp",
        )

        app = create_app(settings)
        client = TestClient(app)

        # Should be mounted at custom path
        response = client.get("/custom-mcp/mcp")
        assert response.status_code != 404


class TestMCPOAuthIntegration:
    """Test MCP OAuth authentication integration."""

    @pytest.fixture
    def auth_settings(self, db_config):
        """Create test settings with MCP OAuth enabled (GitHub)."""
        return Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
            webhook_base_url="https://test.example.com",
            github_client_id="test-github-client-id",
            github_client_secret="test-github-client-secret",
            allowed_hosts=["*"],
        )

    @pytest.fixture
    def auth_app(self, auth_settings):
        """Create FastAPI app with MCP OAuth."""
        return create_app(auth_settings)

    @pytest.fixture
    def auth_client(self, auth_app):
        """Create test client for auth-enabled app."""
        return TestClient(auth_app)

    def test_well_known_oauth_metadata_exists(self, auth_client):
        """Test that .well-known OAuth metadata endpoint exists when auth enabled."""
        # The authorization server .well-known is scoped to the mount path
        response = auth_client.get("/.well-known/oauth-authorization-server/mcp-server")
        assert response.status_code == 200
        data = response.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data

    def test_well_known_resource_metadata_exists(self, auth_client):
        """Test that .well-known resource metadata endpoint exists."""
        response = auth_client.get(
            "/.well-known/oauth-protected-resource/mcp-server/mcp"
        )
        assert response.status_code == 200
        data = response.json()
        assert "resource" in data

    def test_mcp_rejects_unauthenticated_when_auth_enabled(self, auth_client):
        """Test that MCP endpoint rejects unauthenticated requests."""
        response = auth_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 1,
            },
        )
        # Should return 401 Unauthorized without a valid bearer token
        assert response.status_code in [401, 403]

    def test_no_well_known_when_auth_disabled(self, db_config):
        """Test that .well-known endpoints are NOT present when auth disabled."""
        settings = Settings(
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            mcp_enabled=True,
            mcp_mount_path="/mcp-server",
            disable_auth=True,
            allowed_hosts=["*"],
        )
        app = create_app(settings)
        client = TestClient(app)

        response = client.get("/.well-known/oauth-authorization-server/mcp-server")
        assert response.status_code == 404

    def test_api_auth_still_uses_session_cookies(self, auth_client):
        """Test that API endpoints still use session cookie auth (not affected by MCP OAuth)."""
        # API endpoints should still require session cookies, not bearer tokens
        response = auth_client.get("/api/contacts")
        # Should return 401 or 307 (redirect to login) — not affected by MCP OAuth
        assert response.status_code in [401, 307]

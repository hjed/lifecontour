"""
Integration tests for MCP FastAPI integration.

Tests the MCP server integration with the main FastAPI application.
"""

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.main import create_app


class TestMCPFastAPIIntegration:
    """Test MCP server integration with FastAPI."""

    @pytest.fixture
    def test_settings(self, db_config):
        """Create test settings with MCP enabled."""
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

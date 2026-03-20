"""
Integration tests for authentication requirements on REST API and MCP endpoints.

Tests that both REST API and MCP endpoints require authentication using the real database.
These are integration tests because they test the full HTTP request/response cycle
with authentication middleware for both REST and MCP protocols.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class TestAuthenticationIntegration:
    """Integration tests for authentication requirements on REST API and MCP endpoints."""

    @pytest.fixture
    def client(self, db_config):
        """Create test client with proper test database configuration.

        Uses TestClient as a context manager so the app lifespan runs,
        which initialises MCP's StreamableHTTPSessionManager (required
        by the Streamable HTTP transport for POST /mcp requests).
        """
        from app.infrastructure.config import Settings

        # Use proper test database configuration for integration tests
        test_settings = Settings(
            debug=True,
            database_url=db_config.get_async_url().replace(
                "postgresql+asyncpg://", "postgresql://"
            ),
            allowed_hosts=["*"],
            cors_origins=["*"],
            mcp_enabled=True,  # Enable MCP to test both REST API and MCP authentication
            webhook_base_url="http://localhost:8000",
            github_client_id="test_github_client_id",
            github_client_secret="test_github_client_secret",
        )

        app = create_app(settings=test_settings)
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_list_contacts_requires_auth(self, client):
        """Test that listing contacts requires authentication."""
        response = client.get("/api/contacts", headers={"Host": "localhost"})
        assert response.status_code == 401
        data = response.json()
        assert "errors" in data
        assert "Authentication required" in data["errors"][0]["detail"]

    def test_get_contact_requires_auth(self, client):
        """Test that getting a contact requires authentication."""
        response = client.get("/api/contacts/1", headers={"Host": "localhost"})
        assert response.status_code == 401
        data = response.json()
        assert "errors" in data
        assert "Authentication required" in data["errors"][0]["detail"]

    def test_create_contact_requires_auth(self, client):
        """Test that creating a contact requires authentication."""
        contact_data = {
            "data": {
                "type": "contacts",
                "attributes": {"first_name": "John", "last_name": "Doe"},
            }
        }
        response = client.post(
            "/api/contacts", json=contact_data, headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        data = response.json()
        assert "errors" in data
        assert "Authentication required" in data["errors"][0]["detail"]

    def test_update_contact_requires_auth(self, client):
        """Test that updating a contact requires authentication."""
        contact_data = {
            "data": {
                "type": "contacts",
                "id": "1",
                "attributes": {"first_name": "Jane", "last_name": "Doe"},
            }
        }
        response = client.put(
            "/api/contacts/1", json=contact_data, headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        data = response.json()
        assert "errors" in data
        assert "Authentication required" in data["errors"][0]["detail"]

    def test_delete_contact_requires_auth(self, client):
        """Test that deleting a contact requires authentication."""
        response = client.delete("/api/contacts/1", headers={"Host": "localhost"})
        assert response.status_code == 401
        data = response.json()
        assert "errors" in data
        assert "Authentication required" in data["errors"][0]["detail"]

    def test_search_contacts_requires_auth(self, client):
        """Test that searching contacts requires authentication."""
        response = client.get(
            "/api/search/contacts?q=test", headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        data = response.json()
        assert "errors" in data
        assert "Authentication required" in data["errors"][0]["detail"]

    def test_global_search_requires_auth(self, client):
        """Test that global search requires authentication."""
        response = client.get(
            "/api/search/global?q=test", headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        data = response.json()
        assert "errors" in data
        assert "Authentication required" in data["errors"][0]["detail"]

    def test_search_suggestions_requires_auth(self, client):
        """Test that search suggestions require authentication."""
        response = client.get(
            "/api/search/suggestions?q=test", headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        data = response.json()
        assert "errors" in data
        assert "Authentication required" in data["errors"][0]["detail"]

    def test_search_health_does_not_require_auth(self, client):
        """Test that search health endpoint does not require authentication."""
        # Health endpoints should be accessible without authentication for monitoring
        response = client.get("/api/search/health", headers={"Host": "localhost"})
        # Should not return 401 - might return other errors but not authentication error
        assert response.status_code != 401

    def test_auth_endpoints_do_not_require_auth(self, client):
        """Test that auth endpoints themselves don't require authentication."""
        # These should be accessible without authentication
        response = client.get("/api/auth/providers", headers={"Host": "localhost"})
        assert response.status_code != 401

        response = client.get("/api/auth/status", headers={"Host": "localhost"})
        assert response.status_code != 401

    # MCP Authentication Tests
    def test_mcp_get_contact_requires_auth(self, client):
        """Test that MCP get_contact tool requires authentication."""
        mcp_request = {
            "method": "tools/call",
            "params": {"name": "get_contact", "arguments": {"contact_id": 1}},
        }
        response = client.post(
            "/mcp-server/mcp",
            json=mcp_request,
            headers={
                "Host": "localhost",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert response.status_code == 401

    def test_mcp_search_contacts_requires_auth(self, client):
        """Test that MCP search_contacts tool requires authentication."""
        mcp_request = {
            "method": "tools/call",
            "params": {"name": "search_contacts", "arguments": {"query": "test"}},
        }
        response = client.post(
            "/mcp-server/mcp",
            json=mcp_request,
            headers={
                "Host": "localhost",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert response.status_code == 401

    def test_mcp_create_contact_requires_auth(self, client):
        """Test that MCP create_contact tool requires authentication."""
        mcp_request = {
            "method": "tools/call",
            "params": {
                "name": "create_contact",
                "arguments": {"first_name": "John", "last_name": "Doe"},
            },
        }
        response = client.post(
            "/mcp-server/mcp",
            json=mcp_request,
            headers={
                "Host": "localhost",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert response.status_code == 401

    def test_mcp_list_contacts_requires_auth(self, client):
        """Test that MCP list_contacts tool requires authentication."""
        mcp_request = {
            "method": "tools/call",
            "params": {"name": "list_contacts", "arguments": {"page": 1}},
        }
        response = client.post(
            "/mcp-server/mcp",
            json=mcp_request,
            headers={
                "Host": "localhost",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert response.status_code == 401

    def test_mcp_global_search_requires_auth(self, client):
        """Test that MCP global_search tool requires authentication."""
        mcp_request = {
            "method": "tools/call",
            "params": {"name": "global_search", "arguments": {"query": "test"}},
        }
        response = client.post(
            "/mcp-server/mcp",
            json=mcp_request,
            headers={
                "Host": "localhost",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert response.status_code == 401

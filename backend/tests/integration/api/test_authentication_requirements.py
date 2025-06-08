"""
Integration tests for authentication requirements on API endpoints.

Tests that all protected endpoints require authentication and return 401 when not authenticated.
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_async_db_connection,
    get_contact_service,
    get_search_service,
)
from app.infrastructure.config import Settings
from app.main import create_app


class TestAuthenticationRequirements:
    """Test that API endpoints require authentication."""

    @pytest.fixture
    def client(self):
        """Create test client with mocked dependencies to avoid database connections."""
        # Create test settings that allow all hosts for testing
        test_settings = Settings(
            debug=True,
            allowed_hosts=["*"],  # Allow all hosts for testing
            cors_origins=["*"],
        )

        app = create_app(settings=test_settings)

        # Mock all dependencies that might try to connect to external services
        async def mock_db_connection():
            yield Mock()

        def mock_contact_service():
            return Mock()

        def mock_search_service():
            return Mock()

        app.dependency_overrides[get_async_db_connection] = mock_db_connection
        app.dependency_overrides[get_contact_service] = mock_contact_service
        app.dependency_overrides[get_search_service] = mock_search_service

        return TestClient(app)

    def test_list_contacts_requires_auth(self, client):
        """Test that listing contacts requires authentication."""
        response = client.get("/api/contacts", headers={"Host": "localhost"})
        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

    def test_get_contact_requires_auth(self, client):
        """Test that getting a contact requires authentication."""
        response = client.get("/api/contacts/1", headers={"Host": "localhost"})
        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

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
        assert "Authentication required" in response.json()["errors"][0]["detail"]

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
        assert "Authentication required" in response.json()["errors"][0]["detail"]

    def test_delete_contact_requires_auth(self, client):
        """Test that deleting a contact requires authentication."""
        response = client.delete("/api/contacts/1", headers={"Host": "localhost"})
        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

    def test_assign_tag_requires_auth(self, client):
        """Test that assigning a tag requires authentication."""
        tag_data = {"data": {"type": "tags", "id": "1"}}
        response = client.post(
            "/api/contacts/1/tags", json=tag_data, headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

    def test_remove_tag_requires_auth(self, client):
        """Test that removing a tag requires authentication."""
        response = client.delete(
            "/api/contacts/1/tags/1", headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

    def test_get_contact_tags_requires_auth(self, client):
        """Test that getting contact tags requires authentication."""
        response = client.get("/api/contacts/1/tags", headers={"Host": "localhost"})
        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

    def test_search_contacts_requires_auth(self, client):
        """Test that searching contacts requires authentication."""
        response = client.get(
            "/api/search/contacts?q=test", headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

    def test_global_search_requires_auth(self, client):
        """Test that global search requires authentication."""
        response = client.get(
            "/api/search/global?q=test", headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

    def test_search_suggestions_requires_auth(self, client):
        """Test that search suggestions require authentication."""
        response = client.get(
            "/api/search/suggestions?q=test", headers={"Host": "localhost"}
        )
        assert response.status_code == 401
        assert "Authentication required" in response.json()["errors"][0]["detail"]

    def test_search_health_does_not_require_auth(self, client):
        """Test that search health endpoint does not require authentication."""
        # Health endpoints should be accessible without authentication for monitoring
        response = client.get("/api/search/health", headers={"Host": "localhost"})
        # Should not return 401 - might return 503 if MeiliSearch is down, but not 401
        assert response.status_code != 401

    def test_auth_endpoints_do_not_require_auth(self, client):
        """Test that auth endpoints themselves don't require authentication."""
        # These should be accessible without authentication
        response = client.get("/api/auth/providers", headers={"Host": "localhost"})
        assert response.status_code != 401

        response = client.get("/api/auth/status", headers={"Host": "localhost"})
        assert response.status_code != 401

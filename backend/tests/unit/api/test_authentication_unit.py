"""
Unit tests for authentication requirements on API endpoints.

Tests that endpoints require authentication without needing Docker or database.
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_contact_service, get_search_service
from app.main import create_app


class TestAuthenticationUnit:
    """Unit tests for authentication requirements."""

    @pytest.fixture
    def client(self):
        """Create test client with mocked dependencies."""
        app = create_app()

        # Mock the dependencies to avoid database connections
        mock_contact_service = Mock()
        mock_search_service = Mock()

        app.dependency_overrides[get_contact_service] = lambda: mock_contact_service
        app.dependency_overrides[get_search_service] = lambda: mock_search_service

        return TestClient(app)

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

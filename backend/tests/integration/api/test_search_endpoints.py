"""
Integration tests for search API endpoints.

Tests the search endpoints with JSON API compliance.
"""

from unittest.mock import MagicMock

import pytest


@pytest.mark.integration
class TestSearchEndpoints:
    """Test search API endpoints with JSON API compliance."""

    def test_contact_search_json_api_format(self):
        """Test that contact search returns JSON API compliant format."""
        # Mock the search service to return predictable results
        mock_search_results = {
            "hits": [
                {
                    "id": 1,
                    "first_name": "John",
                    "last_name": "Doe",
                    "full_name": "John Doe",
                    "email": "john@example.com",
                    "phone": "+1234567890",
                    "tags": ["customer"],
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                    "_formatted": {"first_name": "<em>John</em>", "last_name": "Doe"},
                }
            ],
            "estimated_total_hits": 1,
            "processing_time_ms": 25,
            "facet_distribution": {"tags": {"customer": 1}},
        }

        # Override the dependency
        def mock_search_service():
            mock_service = MagicMock()
            mock_service.search_contacts.return_value = mock_search_results
            return mock_service

        import os

        from app.api.dependencies import get_search_service
        from app.infrastructure.config import get_settings
        from app.main import create_app

        # Set allowed hosts for testing
        original_allowed_hosts = os.environ.get("ALLOWED_HOSTS")
        os.environ["ALLOWED_HOSTS"] = '["*"]'
        get_settings.cache_clear()

        try:
            # Create a new app with the mocked dependency
            app = create_app()
            app.dependency_overrides[get_search_service] = mock_search_service

            from fastapi.testclient import TestClient

            test_client = TestClient(app)

            # Make request
            response = test_client.get("/api/search/contacts?q=john")

            # Assert response structure
            assert response.status_code == 200
            data = response.json()

            # Check JSON API structure
            assert "data" in data
            assert "meta" in data
            assert "links" in data

            # Check data array
            assert isinstance(data["data"], list)
            assert len(data["data"]) == 1

            # Check resource structure (now using contact resource format)
            resource = data["data"][0]
            assert resource["type"] == "contacts"  # Same as contact API
            assert resource["id"] == "1"  # Contact ID, not composite
            assert "attributes" in resource
            assert "meta" in resource
            assert "links" in resource

            # Check attributes (contact attributes format)
            attributes = resource["attributes"]
            assert attributes["first_name"] == "John"
            assert attributes["last_name"] == "Doe"
            assert attributes["created_at"] == "2024-01-01T00:00:00"
            assert attributes["updated_at"] == "2024-01-01T00:00:00"
            # Embedded data should be empty for search results
            assert attributes["contact_methods"] == []
            assert attributes["addresses"] == []
            assert attributes["notes"] == []

            # Check resource meta (search-specific metadata)
            resource_meta = resource["meta"]
            assert resource_meta["highlighted"] == {
                "first_name": "<em>John</em>",
                "last_name": "Doe",
            }
            assert "search_metadata" in resource_meta
            assert resource_meta["search_metadata"]["tags"] == ["customer"]
            assert resource_meta["search_metadata"]["email"] == "john@example.com"

            # Check links (should point to contact CRUD endpoints)
            links = resource["links"]
            assert "self" in links
            assert "/api/contacts/1" in links["self"]

            # Check response meta
            response_meta = data["meta"]
            assert response_meta["query"] == "john"
            assert response_meta["processing_time_ms"] == 25
            assert response_meta["total_count"] == 1
            assert response_meta["current_page"] == 1
            assert response_meta["per_page"] == 20
            assert response_meta["available_tags"] == ["customer"]

            # Check links
            links = data["links"]
            assert "self" in links
            assert "q=john" in links["self"]
        finally:
            # Restore original environment
            if original_allowed_hosts:
                os.environ["ALLOWED_HOSTS"] = original_allowed_hosts
            elif "ALLOWED_HOSTS" in os.environ:
                del os.environ["ALLOWED_HOSTS"]
            get_settings.cache_clear()

    def test_global_search_json_api_format(self):
        """Test that global search returns JSON API compliant format."""
        mock_search_results = {
            "hits": [
                {
                    "id": 1,
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "full_name": "Jane Smith",
                    "email": "jane@example.com",
                    "entity_type": "contact",
                }
            ],
            "estimated_total_hits": 1,
            "processing_time_ms": 30,
            "searched_entity_types": ["contact"],
            "available_entity_types": ["contact"],
        }

        # Override the dependency
        def mock_search_service():
            mock_service = MagicMock()
            mock_service.global_search.return_value = mock_search_results
            return mock_service

        import os

        from fastapi.testclient import TestClient

        from app.api.dependencies import get_search_service
        from app.infrastructure.config import get_settings
        from app.main import create_app

        # Set allowed hosts for testing
        original_allowed_hosts = os.environ.get("ALLOWED_HOSTS")
        os.environ["ALLOWED_HOSTS"] = '["*"]'
        get_settings.cache_clear()

        try:
            app = create_app()
            app.dependency_overrides[get_search_service] = mock_search_service
            test_client = TestClient(app)

            # Make request
            response = test_client.get("/api/search/global?q=jane")

            # Assert response structure
            assert response.status_code == 200
            data = response.json()

            # Check JSON API structure
            assert "data" in data
            assert "meta" in data
            assert "links" in data

            # Check data array
            assert isinstance(data["data"], list)
            assert len(data["data"]) == 1

            # Check resource structure (contacts should use contact resource format)
            resource = data["data"][0]
            assert (
                resource["type"] == "contacts"
            )  # Contact resources use "contacts" type
            assert resource["id"] == "1"  # Contact ID, not composite

            # Check response meta
            response_meta = data["meta"]
            assert response_meta["query"] == "jane"
            assert response_meta["searched_entity_types"] == ["contact"]
            assert response_meta["available_entity_types"] == ["contact"]
            assert "results_by_type" in response_meta
        finally:
            # Restore original environment
            if original_allowed_hosts:
                os.environ["ALLOWED_HOSTS"] = original_allowed_hosts
            elif "ALLOWED_HOSTS" in os.environ:
                del os.environ["ALLOWED_HOSTS"]
            get_settings.cache_clear()

    def test_contact_search_pagination(self):
        """Test that contact search pagination works with JSON API format."""
        mock_search_results = {
            "hits": [],
            "estimated_total_hits": 50,
            "processing_time_ms": 15,
            "facet_distribution": {},
        }

        def mock_search_service():
            mock_service = MagicMock()
            mock_service.search_contacts.return_value = mock_search_results
            return mock_service

        import os

        from fastapi.testclient import TestClient

        from app.api.dependencies import get_search_service
        from app.infrastructure.config import get_settings
        from app.main import create_app

        # Set allowed hosts for testing
        original_allowed_hosts = os.environ.get("ALLOWED_HOSTS")
        os.environ["ALLOWED_HOSTS"] = '["*"]'
        get_settings.cache_clear()

        try:
            app = create_app()
            app.dependency_overrides[get_search_service] = mock_search_service
            test_client = TestClient(app)

            # Make request with pagination
            response = test_client.get("/api/search/contacts?q=test&page=2&limit=10")

            assert response.status_code == 200
            data = response.json()

            # Check pagination meta
            meta = data["meta"]
            assert meta["current_page"] == 2
            assert meta["per_page"] == 10
            assert meta["total_count"] == 50
            assert meta["page_count"] == 5

            # Check pagination links
            links = data["links"]
            assert "page=2" in links["self"]
            assert "page=1" in links["first"]
            assert "page=5" in links["last"]
            assert "page=1" in links["prev"]
            assert "page=3" in links["next"]
        finally:
            # Restore original environment
            if original_allowed_hosts:
                os.environ["ALLOWED_HOSTS"] = original_allowed_hosts
            elif "ALLOWED_HOSTS" in os.environ:
                del os.environ["ALLOWED_HOSTS"]
            get_settings.cache_clear()

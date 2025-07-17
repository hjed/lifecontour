"""
Integration tests for search API endpoints.

Tests the search endpoints with JSON API compliance.
"""

import pytest


@pytest.mark.integration
class TestSearchEndpoints:
    """Test search API endpoints with JSON API compliance."""

    def test_contact_search_json_api_format(self, authenticated_search_client):
        """Test that contact search returns JSON API compliant format."""
        test_client, setup_search_mock = authenticated_search_client

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
                    "is_favourite": False,
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                    "_formatted": {"first_name": "<em>John</em>", "last_name": "Doe"},
                }
            ],
            "estimated_total_hits": 1,
            "processing_time_ms": 25,
            "facet_distribution": {"tags": {"customer": 1}},
        }

        # Setup the mock search service
        setup_search_mock(mock_search_results)

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

    def test_global_search_json_api_format(self, authenticated_search_client):
        """Test that global search returns JSON API compliant format."""
        test_client, setup_search_mock = authenticated_search_client

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

        # Setup the mock search service
        setup_search_mock(mock_search_results)

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
        assert resource["type"] == "contacts"  # Contact resources use "contacts" type
        assert resource["id"] == "1"  # Contact ID, not composite

        # Check response meta
        response_meta = data["meta"]
        assert response_meta["query"] == "jane"
        assert response_meta["searched_entity_types"] == ["contact"]
        assert response_meta["available_entity_types"] == ["contact"]
        assert "results_by_type" in response_meta

    def test_contact_search_pagination(self, authenticated_search_client):
        """Test that contact search pagination works with JSON API format."""
        test_client, setup_search_mock = authenticated_search_client

        mock_search_results = {
            "hits": [],
            "estimated_total_hits": 50,
            "processing_time_ms": 15,
            "facet_distribution": {},
        }

        # Setup the mock search service
        setup_search_mock(mock_search_results)

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

    def test_contact_search_with_favourite_filter_true(
        self, authenticated_search_client
    ):
        """Test contact search with favourite filter set to true."""
        test_client, setup_search_mock = authenticated_search_client

        # Mock the search service to return favourite contacts
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
                    "is_favourite": True,
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                }
            ],
            "estimated_total_hits": 1,
            "processing_time_ms": 25,
            "facet_distribution": {},
        }

        # Setup the mock search service
        setup_search_mock(mock_search_results)

        # Make request with favourite filter
        response = test_client.get("/api/search/contacts?q=john&favourite=true")

        # Assert response
        assert response.status_code == 200
        data = response.json()

        # Check that results contain favourite contacts
        assert len(data["data"]) == 1
        assert data["data"][0]["attributes"]["is_favourite"] is True

    def test_contact_search_with_favourite_filter_false(
        self, authenticated_search_client
    ):
        """Test contact search with favourite filter set to false."""
        test_client, setup_search_mock = authenticated_search_client

        # Mock the search service to return non-favourite contacts
        mock_search_results = {
            "hits": [
                {
                    "id": 2,
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "full_name": "Jane Smith",
                    "email": "jane@example.com",
                    "phone": "+1234567891",
                    "tags": ["customer"],
                    "is_favourite": False,
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                }
            ],
            "estimated_total_hits": 1,
            "processing_time_ms": 25,
            "facet_distribution": {},
        }

        # Setup the mock search service
        setup_search_mock(mock_search_results)

        # Make request with favourite filter
        response = test_client.get("/api/search/contacts?q=jane&favourite=false")

        # Assert response
        assert response.status_code == 200
        data = response.json()

        # Check that results contain non-favourite contacts
        assert len(data["data"]) == 1
        assert data["data"][0]["attributes"]["is_favourite"] is False

    def test_contact_search_with_combined_filters_including_favourite(
        self, authenticated_search_client
    ):
        """Test contact search with multiple filters including favourite."""
        test_client, setup_search_mock = authenticated_search_client

        # Mock the search service to return filtered results
        mock_search_results = {
            "hits": [
                {
                    "id": 1,
                    "first_name": "John",
                    "last_name": "Doe",
                    "full_name": "John Doe",
                    "email": "john@example.com",
                    "phone": "+1234567890",
                    "tags": ["vip"],
                    "is_favourite": True,
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                }
            ],
            "estimated_total_hits": 1,
            "processing_time_ms": 25,
            "facet_distribution": {},
        }

        # Setup the mock search service
        setup_search_mock(mock_search_results)

        # Make request with multiple filters
        response = test_client.get(
            "/api/search/contacts?q=john&favourite=true&tags=vip"
        )

        # Assert response
        assert response.status_code == 200
        data = response.json()

        # Check that results match the filters
        assert len(data["data"]) == 1
        contact_data = data["data"][0]
        contact_attributes = contact_data["attributes"]
        contact_meta = contact_data["meta"]

        assert contact_attributes["is_favourite"] is True
        assert "vip" in contact_meta["search_metadata"]["tags"]

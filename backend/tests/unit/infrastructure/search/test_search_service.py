"""
Unit tests for SearchService.

Tests the search service that provides high-level search functionality.
"""

from unittest.mock import MagicMock, patch

import pytest
from meilisearch.errors import MeilisearchError

from app.infrastructure.search.search_service import SearchService


class TestSearchService:
    """Test cases for SearchService."""

    @pytest.fixture
    def mock_meilisearch_client(self):
        """Create a mock MeiliSearch client."""
        client = MagicMock()
        return client

    @pytest.fixture
    def search_service(self, mock_meilisearch_client):
        """Create a SearchService instance with mock client."""
        with patch(
            "app.infrastructure.search.search_service.get_meilisearch_client",
            return_value=mock_meilisearch_client,
        ):
            return SearchService()

    @pytest.fixture
    def mock_search_results(self):
        """Create mock search results from MeiliSearch."""
        return {
            "hits": [
                {
                    "id": 1,
                    "first_name": "John",
                    "last_name": "Doe",
                    "full_name": "John Doe",
                    "email": "john@example.com",
                    "_formatted": {
                        "first_name": "<mark>John</mark>",
                        "last_name": "Doe",
                    },
                },
                {
                    "id": 2,
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "full_name": "Jane Smith",
                    "email": "jane@example.com",
                },
            ],
            "processingTimeMs": 15,
            "estimatedTotalHits": 2,
            "facetDistribution": {},
            "facetStats": {},
        }

    def test_search_contacts_basic_query(
        self, search_service, mock_meilisearch_client, mock_search_results
    ):
        """Test basic contact search functionality."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.return_value = mock_search_results

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            results = search_service.search_contacts("John")

        # Assert
        assert results["hits"] == mock_search_results["hits"]
        assert results["query"] == "John"
        assert results["processing_time_ms"] == 15
        assert results["estimated_total_hits"] == 2

        # Verify search was called with correct parameters
        mock_index.search.assert_called_once()
        call_args = mock_index.search.call_args
        assert call_args[0][0] == "John"  # query

        search_params = call_args[0][1]
        assert search_params["limit"] == 20
        assert search_params["offset"] == 0
        assert "attributesToHighlight" in search_params

    def test_search_contacts_with_filters(
        self, search_service, mock_meilisearch_client, mock_search_results
    ):
        """Test contact search with filters."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.return_value = mock_search_results

        filters = {"entity_type": "contact", "tags": ["VIP", "Customer"]}

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            search_service.search_contacts("John", filters=filters)

        # Assert
        call_args = mock_index.search.call_args
        search_params = call_args[0][1]

        # Check that filters were applied
        assert "filter" in search_params
        filter_str = search_params["filter"]
        assert "entity_type = 'contact'" in filter_str
        assert "tags IN ['VIP', 'Customer']" in filter_str

    def test_search_contacts_with_favourite_filter_true(
        self, search_service, mock_meilisearch_client, mock_search_results
    ):
        """Test contact search with favourite filter set to true."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.return_value = mock_search_results

        filters = {"is_favourite": True}

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            search_service.search_contacts("John", filters=filters)

        # Assert
        call_args = mock_index.search.call_args
        search_params = call_args[0][1]

        # Check that favourite filter was applied
        assert "filter" in search_params
        filter_str = search_params["filter"]
        assert "is_favourite = true" in filter_str

    def test_search_contacts_with_favourite_filter_false(
        self, search_service, mock_meilisearch_client, mock_search_results
    ):
        """Test contact search with favourite filter set to false."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.return_value = mock_search_results

        filters = {"is_favourite": False}

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            search_service.search_contacts("John", filters=filters)

        # Assert
        call_args = mock_index.search.call_args
        search_params = call_args[0][1]

        # Check that favourite filter was applied
        assert "filter" in search_params
        filter_str = search_params["filter"]
        assert "is_favourite = false" in filter_str

    def test_search_contacts_with_combined_filters_including_favourite(
        self, search_service, mock_meilisearch_client, mock_search_results
    ):
        """Test contact search with multiple filters including favourite."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.return_value = mock_search_results

        filters = {"is_favourite": True, "tags": ["VIP"], "entity_type": "contact"}

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            search_service.search_contacts("John", filters=filters)

        # Assert
        call_args = mock_index.search.call_args
        search_params = call_args[0][1]

        # Check that all filters were applied
        assert "filter" in search_params
        filter_str = search_params["filter"]
        assert "is_favourite = true" in filter_str
        assert "tags IN ['VIP']" in filter_str
        assert "entity_type = 'contact'" in filter_str
        # Filters should be combined with AND
        assert " AND " in filter_str

    def test_search_contacts_with_pagination(
        self, search_service, mock_meilisearch_client, mock_search_results
    ):
        """Test contact search with pagination parameters."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.return_value = mock_search_results

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            results = search_service.search_contacts("John", limit=10, offset=20)

        # Assert
        call_args = mock_index.search.call_args
        search_params = call_args[0][1]
        assert search_params["limit"] == 10
        assert search_params["offset"] == 20

        assert results["limit"] == 10
        assert results["offset"] == 20

    def test_search_contacts_with_sort(
        self, search_service, mock_meilisearch_client, mock_search_results
    ):
        """Test contact search with sort parameters."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.return_value = mock_search_results

        sort_criteria = ["last_name:asc", "created_at:desc"]

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            search_service.search_contacts("John", sort=sort_criteria)

        # Assert
        call_args = mock_index.search.call_args
        search_params = call_args[0][1]
        assert search_params["sort"] == sort_criteria

    def test_global_search(
        self, search_service, mock_meilisearch_client, mock_search_results
    ):
        """Test global search functionality."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.return_value = mock_search_results

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            results = search_service.global_search("John", entity_types=["contact"])

        # Assert
        assert results["hits"] == mock_search_results["hits"]
        assert results["searched_entity_types"] == ["contact"]
        assert results["available_entity_types"] == ["contact", "journal"]

    def test_global_search_no_entity_types(
        self, search_service, mock_meilisearch_client, mock_search_results
    ):
        """Test global search without specifying entity types."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.return_value = mock_search_results

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            results = search_service.global_search("John")

        # Assert
        # When no entity types specified, should search all available types
        assert results["searched_entity_types"] == ["contact", "journal"]

    def test_get_search_suggestions(self, search_service):
        """Test search suggestions functionality."""
        # Act
        suggestions = search_service.get_search_suggestions(
            "Joh", entity_type="contacts"
        )

        # Assert
        assert suggestions == []  # Currently returns empty list

    def test_get_search_health_success(self, search_service, mock_meilisearch_client):
        """Test search health check when everything is working."""
        # Arrange
        mock_health = {"status": "available"}
        mock_meilisearch_client.health.return_value = mock_health

        mock_indices_response = {
            "results": [{"uid": "pms_contacts", "primaryKey": "id"}]
        }
        mock_meilisearch_client.get_indexes.return_value = mock_indices_response

        mock_index = MagicMock()
        mock_index.get_stats.return_value = {
            "numberOfDocuments": 100,
            "isIndexing": False,
        }
        mock_meilisearch_client.index.return_value = mock_index

        # Act
        health = search_service.get_search_health()

        # Assert
        assert health["status"] == "available"
        assert health["meilisearch_health"] == mock_health
        assert len(health["indices"]) == 1
        assert health["indices"][0]["name"] == "pms_contacts"
        assert health["indices"][0]["documents_count"] == 100

    def test_get_search_health_error(self, search_service, mock_meilisearch_client):
        """Test search health check when there's an error."""
        # Arrange
        mock_meilisearch_client.health.side_effect = Exception("Connection failed")

        # Act
        health = search_service.get_search_health()

        # Assert
        assert health["status"] == "error"
        assert "error" in health
        assert health["indices"] == []

    def test_search_contacts_handles_meilisearch_error(
        self, search_service, mock_meilisearch_client
    ):
        """Test that MeiliSearch errors are properly raised."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.side_effect = MeilisearchError("Search failed")

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act & Assert
            with pytest.raises(MeilisearchError, match="Search failed"):
                search_service.search_contacts("John")

    def test_search_contacts_handles_unexpected_error(
        self, search_service, mock_meilisearch_client
    ):
        """Test that unexpected errors are properly raised."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.search.side_effect = Exception("Unexpected error")

        with patch(
            "app.infrastructure.search.search_service.get_index_name",
            return_value="pms_contacts",
        ):
            # Act & Assert
            with pytest.raises(Exception, match="Unexpected error"):
                search_service.search_contacts("John")
